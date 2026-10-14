"""Ejecución del agente.

Modo momentum (MODO=momentum, por defecto): operar activamente durante la sesión.
    python -m agente.main --seleccionar   # antes de la apertura: valores a vigilar hoy (Claude)
    python -m agente.main --operar        # una pasada: stops dinámicos y entradas
    python -m agente.main --bucle         # pasadas continuas (Mac encendido o servidor)
    python -m agente.main --reactivar     # quita la parada total tras revisarla

Modo conservador (MODO=conservador): una decisión al día.
    python -m agente.main            # ciclo completo
    python -m agente.main --sin-ia   # vigilancia: solo límites y stop-loss, sin llamar a Claude
    python -m agente.main --estado   # muestra la situación y sale
    python -m agente.main --probar-claude  # comprueba que la clave de Claude funciona
"""

import argparse
import sys
from pathlib import Path

from agente import riesgo
from agente.brokers.base import Broker
from agente.config import Config, cargar_config
from agente.diario import Diario
from agente.disparadores import detectar
from agente.indicadores import resumir


def crear_broker(cfg: Config) -> Broker:
    if cfg.broker == "simulado":
        import os

        from agente.brokers.simulado import BrokerSimulado

        fuente = None
        if os.environ.get("ALPACA_API_KEY") and os.environ.get("ALPACA_SECRET_KEY"):
            from agente.brokers.alpaca import BrokerAlpaca

            fuente = BrokerAlpaca(paper=True)  # solo para leer precios
        return BrokerSimulado(cfg.carpeta_datos, capital_inicial=cfg.capital_simulado, fuente_datos=fuente)
    if cfg.broker == "alpaca":
        from agente.brokers.alpaca import BrokerAlpaca

        return BrokerAlpaca(paper=cfg.alpaca_paper)
    raise SystemExit(f"Broker desconocido: {cfg.broker}")


def confirmar(texto: str, cfg: Config) -> bool:
    if not cfg.confirmar_ordenes:
        return True
    if not sys.stdin.isatty():
        # Ejecución automática (p. ej. GitHub Actions) con confirmación activada: no se opera
        print(f"\nPROPUESTA SIN EJECUTAR (requiere confirmación y no hay nadie al teclado):\n{texto}")
        return False
    return input(f"\n{texto}\n¿Ejecutar? (s/n): ").strip().lower() in ("s", "si", "sí")


def mostrar_estado(broker: Broker, diario: Diario, cfg: Config) -> None:
    print(f"Broker: {broker.nombre}")
    print(f"Patrimonio: {broker.patrimonio():.2f} | Efectivo: {broker.efectivo():.2f}")
    for p in broker.posiciones():
        print(f"  {p.simbolo}: {p.cantidad:.4f} uds, valor {p.valor:.2f}, {p.pnl_pct:+.1f}%")
    ops = diario.operaciones_ultimos_dias(excluir_simbolo=cfg.nucleo_simbolo)
    if cfg.modo == "momentum":
        cerradas = [o for o in diario.operaciones() if o["accion"] == "vender" and o.get("resultado")]
        ganadoras = sum(1 for o in cerradas if float(o["resultado"]) > 0)
        total = sum(float(o["resultado"]) for o in cerradas)
        print(f"Modo momentum | operaciones últimos 7 días: {ops} | cerradas: {len(cerradas)} "
              f"(ganadoras {ganadoras}) | resultado acumulado {total:+.2f}")
        print(f"Vigilando hoy: {', '.join(diario.vigilancia()) or '-'}")
        if diario.parada_total():
            print(f"PARADA TOTAL: {diario.parada_total()}")
    else:
        print(f"Operaciones del agente últimos 7 días: {ops}/{cfg.max_operaciones_semana} (el núcleo no cuenta)")
    print(f"Gasto en Claude este mes: {diario.gasto_ia_mes():.3f} $ / {cfg.max_gasto_ia_mes:.2f} $")


def _vender(broker: Broker, diario: Diario, p, motivo: str) -> str:
    orden = broker.vender_todo(p.simbolo)
    resultado = (p.precio_actual - p.precio_medio) * p.cantidad
    diario.registrar_operacion(broker.nombre, "vender", p.simbolo, p.valor, p.precio_actual, orden,
                               motivo, resultado=resultado)
    return orden


def ciclo(cfg: Config, broker: Broker, diario: Diario, usar_ia: bool = True) -> None:
    patrimonio = broker.patrimonio()
    inicio = diario.patrimonio_inicio_dia(patrimonio)
    print(f"Patrimonio {patrimonio:.2f} (inicio del día {inicio:.2f})")

    # 1. Stop-loss: se ejecuta siempre, sin IA ni confirmación (el núcleo no tiene stop)
    for p in riesgo.posiciones_a_cerrar_por_stop(broker.posiciones(), cfg):
        _vender(broker, diario, p, f"stop-loss {p.pnl_pct:.1f}%")
        print(f"STOP-LOSS: vendido {p.simbolo} ({p.pnl_pct:.1f}%)")

    # 1b. En el ciclo completo (tras el cierre), dejar stops puestos en el broker para mañana
    if usar_ia:
        satelite = [p for p in broker.posiciones() if p.simbolo != cfg.nucleo_simbolo]
        for msg in broker.proteger(satelite, cfg.stop_loss_pct):
            print(msg)

    # 2. Paradas generales
    v = riesgo.parada_general(broker.patrimonio(), inicio, cfg)
    if not v.permitido:
        print(v.motivo)
        return
    if not usar_ia:
        return

    # 3. Núcleo: reequilibrio sin IA (solo compras, para no generar impuestos)
    if cfg.nucleo_simbolo:
        valor_nucleo = sum(p.valor for p in broker.posiciones() if p.simbolo == cfg.nucleo_simbolo)
        importe = riesgo.compra_nucleo(broker.patrimonio(), valor_nucleo, broker.efectivo(), cfg)
        if importe:
            try:
                precio = broker.historico(cfg.nucleo_simbolo, 5)[-1].cierre
                limite = precio * 1.003
                if confirmar(f"NÚCLEO: comprar {cfg.nucleo_simbolo} por {importe:.2f} (límite {limite:.2f})", cfg):
                    orden = broker.comprar(cfg.nucleo_simbolo, importe, precio_limite=limite)
                    diario.registrar_operacion(broker.nombre, "comprar", cfg.nucleo_simbolo, importe, precio, orden,
                                               "núcleo: reequilibrio")
                    print(f"Núcleo: comprado {cfg.nucleo_simbolo} por {importe:.2f}")
            except Exception as e:
                print(f"Aviso: no se pudo comprar el núcleo {cfg.nucleo_simbolo}: {e}")

    # 4. Indicadores (gratis)
    resumenes = {}
    for s in cfg.simbolos_permitidos:
        if s == cfg.nucleo_simbolo:
            continue
        try:
            resumenes[s] = resumir(s, broker.historico(s, 60)).como_dict()
        except Exception as e:  # un valor sin datos no debe parar el resto
            print(f"Aviso: sin datos de {s}: {e}")
    if not resumenes:
        print("No hay datos de ningún valor.")
        return

    posiciones = broker.posiciones()
    pos_dict = [{"simbolo": p.simbolo, "valor": round(p.valor, 2), "pnl_pct": round(p.pnl_pct, 2),
                 "nucleo": p.simbolo == cfg.nucleo_simbolo} for p in posiciones]
    efectivo = broker.efectivo()

    # 5. Disparadores (gratis): solo se consulta a Claude si pasa algo
    disparos = detectar(resumenes, pos_dict, excluir=(cfg.nucleo_simbolo,))
    if not disparos:
        print("Sin avisos hoy: no se consulta a Claude (coste 0).")
        return
    d = disparos[0]
    print(f"Aviso en {d.simbolo}: {d.motivo}")
    if diario.gasto_ia_mes() >= cfg.max_gasto_ia_mes:
        print(f"Tope de gasto en IA alcanzado este mes ({diario.gasto_ia_mes():.2f} $). No se analiza.")
        return

    avisos_fiscales = []
    if cfg.regla_dos_meses and diario.venta_con_perdida_reciente(d.simbolo):
        avisos_fiscales.append(f"{d.simbolo} se vendió con pérdidas hace menos de 2 meses: recomprarlo ahora "
                               "impediría compensar esa pérdida en la renta (no se permitirá comprar)")
    if diario.compra_reciente(d.simbolo):
        avisos_fiscales.append(f"{d.simbolo} se compró hace menos de 2 meses: si se vende con pérdidas, "
                               "esa pérdida no se podrá compensar todavía en la renta")

    # 6. Claude: comité de inversión sobre el valor con aviso
    from agente.analista import Analista

    analista = Analista()
    try:
        decision = analista.decidir(d.simbolo, d.motivo, resumenes[d.simbolo], pos_dict, efectivo,
                                    cfg.max_por_operacion, avisos_fiscales)
    finally:
        diario.sumar_gasto_ia(analista.gasto_usd)

    diario.registrar_decision({
        "aviso": {"simbolo": d.simbolo, "motivo": d.motivo},
        "decision": decision.model_dump() if decision else None,
        "coste_usd": round(analista.gasto_usd, 4),
    })
    print(f"Coste de Claude en este ciclo: {analista.gasto_usd:.4f} $")
    if not decision or decision.accion == "mantener":
        print("Decisión: mantener." + (f" {decision.razonamiento}" if decision else ""))
        return

    # 7. Validación de riesgo, costes e impuestos; ejecución
    simbolo = decision.simbolo.upper()
    ops = diario.operaciones_ultimos_dias(excluir_simbolo=cfg.nucleo_simbolo)
    precio = resumenes.get(simbolo, {}).get("precio")
    if precio is None:
        print(f"Decisión descartada: {simbolo} no está entre los valores analizados")
        return
    if decision.accion == "comprar":
        v = riesgo.validar_ventaja(decision.rentabilidad_esperada_pct, decision.confianza, cfg)
        if v.permitido and cfg.regla_dos_meses and diario.venta_con_perdida_reciente(simbolo):
            v = riesgo.Veredicto(False, f"Regla de los 2 meses: {simbolo} se vendió con pérdidas hace menos de 61 días")
        if v.permitido:
            v = riesgo.validar_compra(simbolo, decision.importe, efectivo, ops, posiciones, cfg)
        if not v.permitido:
            print(f"Compra bloqueada: {v.motivo}")
            return
        limite = precio * 1.003  # no pagar más de un 0,3 % sobre el último cierre
        texto = (f"COMPRAR {simbolo} por {v.importe:.2f} (límite {limite:.2f}) | confianza {decision.confianza}/10 | "
                 f"esperado {decision.rentabilidad_esperada_pct:+.1f}% en {decision.horizonte_dias} días\n"
                 f"Ventaja: {decision.ventaja}\nRiesgo: {decision.riesgo_principal}")
        if confirmar(texto, cfg):
            orden = broker.comprar(simbolo, v.importe, precio_limite=limite)
            diario.registrar_operacion(broker.nombre, "comprar", simbolo, v.importe, precio, orden, decision.ventaja)
            print(f"Orden enviada: {orden}")
    else:
        v = riesgo.validar_venta(simbolo, posiciones, ops, cfg)
        if not v.permitido:
            print(f"Venta bloqueada: {v.motivo}")
            return
        pos = next(p for p in posiciones if p.simbolo == simbolo)
        if confirmar(f"VENDER todo {simbolo} (valor {pos.valor:.2f}, {pos.pnl_pct:+.1f}%)\n{decision.razonamiento}", cfg):
            orden = _vender(broker, diario, pos, decision.razonamiento[:200])
            print(f"Orden enviada: {orden}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Agente de trading con Claude")
    ap.add_argument("--sin-ia", action="store_true", help="solo límites y stop-loss")
    ap.add_argument("--estado", action="store_true", help="muestra la situación y sale")
    ap.add_argument("--probar-claude", action="store_true", help="comprueba la clave de Claude (coste < 0,01 $)")
    ap.add_argument("--seleccionar", action="store_true", help="momentum: elige los valores a vigilar hoy")
    ap.add_argument("--operar", action="store_true", help="momentum: una pasada del operador")
    ap.add_argument("--bucle", action="store_true", help="momentum: pasadas continuas")
    ap.add_argument("--segundos", type=int, default=60, help="segundos entre pasadas en --bucle")
    ap.add_argument("--hasta-cierre", action="store_true", help="--bucle termina al cerrar el mercado")
    ap.add_argument("--max-minutos", type=float, default=0,
                    help="--bucle termina tras estos minutos y crea el archivo 'continuar' si el mercado sigue abierto")
    ap.add_argument("--reactivar", action="store_true", help="quita la parada total")
    ap.add_argument("--reiniciar-simulado", action="store_true", help="vuelve a empezar el broker simulado")
    args = ap.parse_args(argv)

    cfg = cargar_config()
    if args.probar_claude:
        from agente.analista import probar_conexion

        print(probar_conexion())
        return
    if cfg.broker == "alpaca" and not cfg.alpaca_paper:
        print("⚠️  MODO DINERO REAL (Alpaca)")
    diario = Diario(cfg.carpeta_datos)
    if args.reiniciar_simulado:
        from pathlib import Path

        from datetime import datetime

        carpeta = Path(cfg.carpeta_datos)
        (carpeta / "simulado.json").unlink(missing_ok=True)
        sello = datetime.now().strftime("%Y%m%d-%H%M")
        for nombre in ("operaciones.csv", "decisiones.jsonl"):  # se archivan, no se borran
            if (carpeta / nombre).exists():
                (carpeta / "archivo").mkdir(exist_ok=True)
                (carpeta / nombre).rename(carpeta / "archivo" / f"{sello}-{nombre}")
        for clave in ("maximos", "salidas", "pico_patrimonio", "vigilancia", "parada_total", "dia", "inicio"):
            diario.estado.pop(clave, None)
        diario._guardar_estado()
        print(f"Broker simulado reiniciado con {cfg.capital_simulado:.2f}.")
        return
    if args.reactivar:
        diario.estado.pop("parada_total", None)
        diario.estado.pop("pico_patrimonio", None)
        diario._guardar_estado()
        print("Parada total retirada.")
        return
    broker = crear_broker(cfg)
    if args.estado:
        mostrar_estado(broker, diario, cfg)
        return

    if cfg.modo == "momentum":
        from agente import operador

        if args.bucle:
            if operador.bucle(cfg, crear_broker, diario, args.segundos, args.hasta_cierre, args.max_minutos):
                Path("continuar").touch()
        elif args.seleccionar:
            operador.seleccionar(cfg, broker, diario, usar_ia=not args.sin_ia)
        else:  # --operar, --sin-ia o sin opciones: una pasada (los stops nunca usan IA)
            operador.operar(cfg, broker, diario)
        return

    if args.seleccionar:
        print("Modo conservador: no hay selección diaria.")
        return
    ciclo(cfg, broker, diario, usar_ia=not (args.sin_ia or args.operar))


if __name__ == "__main__":
    sys.exit(main())
