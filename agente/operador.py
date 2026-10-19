"""Operador de impulso: lo que haría un trader pegado a la pantalla, cada pocos minutos.

    python -m agente.main --seleccionar   # antes de la apertura: elige qué valores vigilar hoy
    python -m agente.main --operar        # una pasada: gestiona stops y busca entradas
    python -m agente.main --bucle         # pasadas continuas mientras el mercado está abierto (Mac o servidor)

Cada pasada:
1. Paradas de seguridad: si el patrimonio cae PARADA_DRAWDOWN_PCT desde su máximo, se vende todo y se
   detiene (hay que reactivarlo a mano). Si hoy se pierde MAX_PERDIDA_DIARIA_PCT, no abre más posiciones hoy.
2. Stop dinámico de cada posición: guarda el máximo alcanzado y vende si cae TRAILING_PCT desde ahí
   (o lo que se mueve normalmente ese valor, con STOP_ATR). El stop se deja también puesto en el broker.
   Opcional: vende la mitad al ganar PARCIAL_PCT y cierra todo al final del día (CERRAR_AL_CIERRE).
3. Entradas: si hay hueco, busca rupturas con volumen en los valores vigilados y compra un
   PCT_POR_POSICION del patrimonio actual (reinversión automática de las ganancias).
   Opcional: solo con el mercado a favor (FILTRO_MERCADO) y fuera de los primeros/últimos minutos.
"""

from agente import momentum
from agente.brokers.base import Broker
from agente.config import Config
from agente.diario import Diario
from agente.indicadores import resumir


def _vender(broker: Broker, diario: Diario, p, motivo: str) -> None:
    orden = broker.vender_todo(p.simbolo)
    resultado = (p.precio_actual - p.precio_medio) * p.cantidad
    diario.registrar_operacion(broker.nombre, "vender", p.simbolo, p.valor, p.precio_actual, orden, motivo,
                               resultado=resultado)
    diario.guardar_maximo(p.simbolo, None)
    for clave in ("distancias", "parciales"):
        diario.estado.get(clave, {}).pop(p.simbolo, None)
    diario.registrar_salida(p.simbolo)
    print(f"VENTA {p.simbolo}: {motivo} | resultado {resultado:+.2f}")


def _sesion_ahora() -> tuple[int, int] | None:
    """(minutos desde la apertura, minutos hasta el cierre) ahora mismo, en Nueva York."""
    from datetime import datetime, timezone

    return momentum.minutos_sesion(datetime.now(timezone.utc).isoformat())


def seleccionar(cfg: Config, broker: Broker, diario: Diario, usar_ia: bool = True) -> list[str]:
    """Elige los valores a vigilar hoy: ranking de impulso en código y, si hay presupuesto, Claude afina."""
    resumenes = {}
    for s in cfg.universo:
        try:
            resumenes[s] = resumir(s, broker.historico(s, 70)).como_dict()
        except Exception as e:
            print(f"Aviso: sin datos de {s}: {e}")
    ranking = momentum.ranking_impulso(resumenes)
    elegidos, motivo = ranking[:cfg.vigilar_max], "ranking de impulso (sin IA)"

    if usar_ia and ranking and diario.gasto_ia_mes() < cfg.max_gasto_ia_mes:
        from agente.analista import Analista

        from agente.noticias import titulares

        noticias = titulares(ranking[:12])
        print(f"Noticias: {sum(len(t) for t in noticias.values())} titulares de {len(noticias)} valores")
        analista = Analista()
        try:
            sel = analista.seleccionar(resumenes, ranking, cfg.vigilar_max, noticias)
        except Exception as e:
            sel = None
            print(f"Aviso: Claude no disponible ({e}); se usa el ranking")
        finally:
            diario.sumar_gasto_ia(analista.gasto_usd)
        if sel:
            validos = [s.upper() for s in sel.vigilar if s.upper() in resumenes and s.upper() not in
                       {e.upper() for e in sel.evitar}]
            if validos:
                elegidos, motivo = validos[:cfg.vigilar_max], sel.motivo
            diario.registrar_decision({"seleccion": sel.model_dump(), "coste_usd": round(analista.gasto_usd, 4)})
        print(f"Coste de Claude: {analista.gasto_usd:.4f} $")

    diario.guardar_vigilancia(elegidos, motivo)
    print(f"Vigilar hoy: {', '.join(elegidos) or '(ninguno)'} — {motivo}")
    return elegidos


def operar(cfg: Config, broker: Broker, diario: Diario) -> None:
    """Una pasada del operador."""
    if diario.parada_total():
        print(f"PARADA TOTAL activa: {diario.parada_total()}. Revisa y reactívala a mano (--reactivar).")
        return

    patrimonio = broker.patrimonio()
    inicio = diario.patrimonio_inicio_dia(patrimonio)
    pico = diario.pico_patrimonio(patrimonio)
    print(f"Patrimonio {patrimonio:.2f} | inicio del día {inicio:.2f} | máximo histórico {pico:.2f}")

    # 1. Parada por caída desde el máximo: se cierra todo
    caida = (1 - patrimonio / pico) * 100 if pico else 0
    if caida >= cfg.parada_drawdown_pct:
        for p in broker.posiciones():
            _vender(broker, diario, p, f"parada total: caída {caida:.1f}% desde el máximo")
        diario.activar_parada_total(f"caída del {caida:.1f}% desde el máximo ({pico:.2f} -> {patrimonio:.2f})")
        print("PARADA TOTAL activada.")
        return

    # 2. Cierre de la sesión: no dormir con posiciones (si está activado)
    sesion = _sesion_ahora()
    if cfg.cerrar_al_cierre and sesion and 0 < sesion[1] <= 6 and broker.mercado_abierto():
        for p in broker.posiciones():
            _vender(broker, diario, p, "cierre de la sesión: no se duerme con posiciones")
        print("Fin de la sesión: todo vendido.")
        return

    # 3. Stop dinámico de cada posición (y venta de la mitad al llegar al objetivo, si está activada)
    for p in broker.posiciones():
        anterior = diario.estado.get("maximos", {}).get(p.simbolo)
        distancia = diario.estado.get("distancias", {}).get(p.simbolo, cfg.trailing_pct)
        maximo = anterior if anterior is not None else max(p.precio_medio, p.precio_actual)
        maximo, stop, vender = momentum.actualizar_trailing(maximo, p.precio_actual, distancia)
        if vender:
            _vender(broker, diario, p, f"stop dinámico: {p.precio_actual:.2f} <= {stop:.2f} "
                                       f"(máximo {maximo:.2f}, -{distancia}%)")
            continue
        diario.guardar_maximo(p.simbolo, maximo)
        parciales = diario.estado.setdefault("parciales", {})
        mover_stop = False
        if cfg.parcial_pct > 0 and not parciales.get(p.simbolo) and p.pnl_pct >= cfg.parcial_pct:
            mitad = p.cantidad / 2
            try:
                orden = broker.vender(p.simbolo, mitad)
                diario.registrar_operacion(broker.nombre, "vender", p.simbolo, mitad * p.precio_actual, p.precio_actual,
                                           orden, f"asegura la mitad al {p.pnl_pct:+.1f}%",
                                           resultado=(p.precio_actual - p.precio_medio) * mitad)
                parciales[p.simbolo] = True
                diario._guardar_estado()
                p.cantidad -= mitad
                mover_stop = True
                print(f"VENTA PARCIAL {p.simbolo}: mitad al {p.pnl_pct:+.1f}%")
            except Exception as e:
                print(f"Aviso: no se pudo vender la mitad de {p.simbolo}: {e}")
        if mover_stop or anterior is None or maximo > anterior:  # el stop ha subido: moverlo también en el broker
            try:
                broker.poner_stop(p.simbolo, p.cantidad, stop)
            except Exception as e:
                print(f"Aviso: no se pudo dejar el stop de {p.simbolo} en el broker: {e}")
        print(f"  {p.simbolo}: {p.precio_actual:.2f} ({p.pnl_pct:+.1f}%) | máximo {maximo:.2f} | stop {stop:.2f}")

    # 4. Entradas
    perdida_hoy = (1 - broker.patrimonio() / inicio) * 100 if inicio else 0
    if perdida_hoy >= cfg.max_perdida_diaria_pct:
        print(f"Pérdida de hoy {perdida_hoy:.1f}% >= {cfg.max_perdida_diaria_pct}%: no se abren más posiciones hoy.")
        return
    if not broker.mercado_abierto():
        print("Mercado cerrado: no se buscan entradas.")
        return
    if (cfg.evitar_apertura_min or cfg.evitar_cierre_min) and sesion and not momentum.en_horario(*sesion, cfg.evitar_apertura_min, cfg.evitar_cierre_min):
        print(f"Fuera del horario de compras (primeros {cfg.evitar_apertura_min} min / últimos "
              f"{cfg.evitar_cierre_min} min): solo se vigilan los stops.")
        return
    posiciones = broker.posiciones()
    huecos = cfg.max_posiciones - len(posiciones)
    if huecos <= 0:
        print("Sin huecos: todas las posiciones ocupadas.")
        return
    if cfg.filtro_mercado:
        try:
            if not momentum.mercado_favorable(broker.intradia("QQQ", cfg.minutos_vela)):
                print("Mercado general (QQQ) por debajo de su media: hoy no se compra a contracorriente.")
                return
        except Exception as e:
            print(f"Aviso: sin datos de QQQ para el filtro de mercado: {e}")

    vigilar = diario.vigilancia() or seleccionar(cfg, broker, diario, usar_ia=False)
    print(f"Buscando entradas en: {', '.join(vigilar)} ({huecos} huecos libres)")
    tengo = {p.simbolo for p in posiciones}
    for s in vigilar:
        if huecos <= 0:
            break
        if s in tengo:
            continue
        espera = diario.minutos_desde_salida(s)
        if espera is not None and espera < cfg.espera_reentrada_min:
            print(f"  {s}: vendido hace {espera:.0f} min, espera {cfg.espera_reentrada_min} min")
            continue
        try:
            velas = momentum.velas_cerradas(broker.intradia(s, cfg.minutos_vela), cfg.minutos_vela)
        except Exception as e:
            print(f"Aviso: sin datos intradía de {s}: {e}")
            continue
        senal = momentum.senal_entrada(velas, cfg.barras_ruptura, cfg.volumen_minimo)
        if not senal.entrar:
            print(f"  {s}: {senal.motivo}")
            continue
        importe = momentum.tamano_posicion(broker.patrimonio(), broker.efectivo(), cfg.pct_por_posicion)
        if importe < 1:
            print("Sin efectivo suficiente para nuevas entradas.")
            break
        precio = velas[-1].cierre
        limite = precio * 1.002  # no perseguir el precio más de un 0,2 %
        try:
            orden = broker.comprar(s, importe, precio_limite=limite)
        except Exception as e:
            print(f"Aviso: no se pudo comprar {s}: {e}")
            continue
        diario.registrar_operacion(broker.nombre, "comprar", s, importe, precio, orden, senal.motivo)
        if cfg.stop_atr > 0:
            diario.estado.setdefault("distancias", {})[s] = momentum.distancia_stop(velas, cfg.trailing_pct, cfg.stop_atr)
        diario.guardar_maximo(s, precio)
        huecos -= 1
        print(f"COMPRA {s} por {importe:.2f} a ~{precio:.2f}: {senal.motivo}")


def bucle(cfg: Config, crear_broker, diario: Diario, segundos: int = 60, hasta_cierre: bool = False,
          max_minutos: float = 0) -> bool:
    """Pasadas continuas mientras el mercado está abierto. Para un Mac encendido o un servidor.

    hasta_cierre: termina en cuanto el mercado está cerrado (para una ejecución de GitHub Actions).
    max_minutos: termina tras ese tiempo (GitHub corta a las 6 h y la sesión dura 6,5 h).
    Devuelve True si paró por tiempo con el mercado aún abierto (hay que lanzar otra ejecución).
    """
    import time
    from datetime import datetime

    inicio = time.monotonic()
    print(f"Operador en marcha: una pasada cada {segundos} s.", flush=True)
    while True:
        if max_minutos and (time.monotonic() - inicio) / 60 >= max_minutos:
            print(f"Límite de {max_minutos:.0f} min alcanzado: se continúa en otra ejecución.", flush=True)
            return True
        broker = crear_broker(cfg)  # nuevo cada vez: datos frescos
        try:
            abierto = broker.mercado_abierto()
            if abierto:
                print(f"\n--- {datetime.now():%H:%M:%S} ---", flush=True)
                if not diario.vigilancia():
                    seleccionar(cfg, broker, diario)
                operar(cfg, broker, diario)
            elif hasta_cierre:
                print("Mercado cerrado: fin del bucle.")
                return False
        except Exception as e:  # un fallo puntual de red no debe parar el bucle
            print(f"Error en la pasada: {e}", flush=True)
        time.sleep(segundos)
