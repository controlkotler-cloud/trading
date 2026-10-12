"""Operador de impulso: lo que haría un trader pegado a la pantalla, cada pocos minutos.

    python -m agente.main --seleccionar   # antes de la apertura: elige qué valores vigilar hoy
    python -m agente.main --operar        # una pasada: gestiona stops y busca entradas
    python -m agente.main --bucle         # pasadas continuas mientras el mercado está abierto (Mac o servidor)

Cada pasada:
1. Paradas de seguridad: si el patrimonio cae PARADA_DRAWDOWN_PCT desde su máximo, se vende todo y se
   detiene (hay que reactivarlo a mano). Si hoy se pierde MAX_PERDIDA_DIARIA_PCT, no abre más posiciones hoy.
2. Stop dinámico de cada posición: guarda el máximo alcanzado y vende si cae TRAILING_PCT desde ahí.
   El stop se deja también puesto en el broker para que actúe entre pasadas.
3. Entradas: si hay hueco, busca rupturas con volumen en los valores vigilados y compra un
   PCT_POR_POSICION del patrimonio actual (reinversión automática de las ganancias).
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
    diario.registrar_salida(p.simbolo)
    print(f"VENTA {p.simbolo}: {motivo} | resultado {resultado:+.2f}")


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

        analista = Analista()
        try:
            sel = analista.seleccionar(resumenes, ranking, cfg.vigilar_max)
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

    # 2. Stop dinámico de cada posición
    for p in broker.posiciones():
        anterior = diario.estado.get("maximos", {}).get(p.simbolo)
        maximo = anterior if anterior is not None else max(p.precio_medio, p.precio_actual)
        maximo, stop, vender = momentum.actualizar_trailing(maximo, p.precio_actual, cfg.trailing_pct)
        if vender:
            _vender(broker, diario, p, f"stop dinámico: {p.precio_actual:.2f} <= {stop:.2f} "
                                       f"(máximo {maximo:.2f}, -{cfg.trailing_pct}%)")
            continue
        diario.guardar_maximo(p.simbolo, maximo)
        if anterior is None or maximo > anterior:  # el stop ha subido: moverlo también en el broker
            try:
                broker.poner_stop(p.simbolo, p.cantidad, stop)
            except Exception as e:
                print(f"Aviso: no se pudo dejar el stop de {p.simbolo} en el broker: {e}")
        print(f"  {p.simbolo}: {p.precio_actual:.2f} ({p.pnl_pct:+.1f}%) | máximo {maximo:.2f} | stop {stop:.2f}")

    # 3. Entradas
    perdida_hoy = (1 - broker.patrimonio() / inicio) * 100 if inicio else 0
    if perdida_hoy >= cfg.max_perdida_diaria_pct:
        print(f"Pérdida de hoy {perdida_hoy:.1f}% >= {cfg.max_perdida_diaria_pct}%: no se abren más posiciones hoy.")
        return
    if not broker.mercado_abierto():
        print("Mercado cerrado: no se buscan entradas.")
        return
    posiciones = broker.posiciones()
    huecos = cfg.max_posiciones - len(posiciones)
    if huecos <= 0:
        print("Sin huecos: todas las posiciones ocupadas.")
        return

    vigilar = diario.vigilancia() or seleccionar(cfg, broker, diario, usar_ia=False)
    tengo = {p.simbolo for p in posiciones}
    for s in vigilar:
        if huecos <= 0:
            break
        if s in tengo:
            continue
        espera = diario.minutos_desde_salida(s)
        if espera is not None and espera < cfg.espera_reentrada_min:
            continue
        try:
            velas = broker.intradia(s, cfg.minutos_vela)
        except Exception as e:
            print(f"Aviso: sin datos intradía de {s}: {e}")
            continue
        senal = momentum.senal_entrada(velas, cfg.barras_ruptura, cfg.volumen_minimo)
        if not senal.entrar:
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
        diario.guardar_maximo(s, precio)
        huecos -= 1
        print(f"COMPRA {s} por {importe:.2f} a ~{precio:.2f}: {senal.motivo}")


def bucle(cfg: Config, crear_broker, diario: Diario, segundos: int = 60) -> None:
    """Pasadas continuas mientras el mercado está abierto. Para un Mac encendido o un servidor."""
    import time

    print(f"Operador en marcha: una pasada cada {segundos} s. Ctrl+C para parar.")
    while True:
        broker = crear_broker(cfg)  # nuevo cada vez: datos frescos
        try:
            if broker.mercado_abierto():
                if not diario.vigilancia():
                    seleccionar(cfg, broker, diario)
                operar(cfg, broker, diario)
        except Exception as e:  # un fallo puntual de red no debe parar el bucle
            print(f"Error en la pasada: {e}")
        time.sleep(segundos)
