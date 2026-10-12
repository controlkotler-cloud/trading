"""Ejecución del agente. Pensado para lanzarse una vez al día (a mano o programado).

    python -m agente.main            # ciclo completo
    python -m agente.main --sin-ia   # solo comprueba límites y stop-loss, sin llamar a Claude
    python -m agente.main --estado   # muestra la situación y sale
"""

import argparse
import sys

from agente import riesgo
from agente.brokers.base import Broker
from agente.config import Config, cargar_config
from agente.diario import Diario
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
    print(f"Operaciones últimos 7 días: {diario.operaciones_ultimos_dias()}/{cfg.max_operaciones_semana}")
    print(f"Gasto en Claude este mes: {diario.gasto_ia_mes():.3f} $ / {cfg.max_gasto_ia_mes:.2f} $")


def ciclo(cfg: Config, broker: Broker, diario: Diario, usar_ia: bool = True) -> None:
    patrimonio = broker.patrimonio()
    inicio = diario.patrimonio_inicio_dia(patrimonio)
    print(f"Patrimonio {patrimonio:.2f} (inicio del día {inicio:.2f})")

    # 1. Stop-loss: se ejecuta siempre, sin IA ni confirmación
    for p in riesgo.posiciones_a_cerrar_por_stop(broker.posiciones(), cfg):
        orden = broker.vender_todo(p.simbolo)
        diario.registrar_operacion(broker.nombre, "vender", p.simbolo, p.valor, p.precio_actual, orden,
                                   f"stop-loss {p.pnl_pct:.1f}%")
        print(f"STOP-LOSS: vendido {p.simbolo} ({p.pnl_pct:.1f}%)")

    # 2. Paradas generales
    v = riesgo.parada_general(broker.patrimonio(), inicio, cfg)
    if not v.permitido:
        print(v.motivo)
        return
    if not usar_ia:
        return
    if diario.gasto_ia_mes() >= cfg.max_gasto_ia_mes:
        print(f"Tope de gasto en IA alcanzado este mes ({diario.gasto_ia_mes():.2f} $). No se analiza.")
        return

    # 3. Indicadores
    resumenes = {}
    for s in cfg.simbolos_permitidos:
        try:
            resumenes[s] = resumir(s, broker.historico(s, 60)).como_dict()
        except Exception as e:  # un valor sin datos no debe parar el resto
            print(f"Aviso: sin datos de {s}: {e}")
    if not resumenes:
        print("No hay datos de ningún valor.")
        return

    posiciones = broker.posiciones()
    pos_dict = [{"simbolo": p.simbolo, "valor": round(p.valor, 2), "pnl_pct": round(p.pnl_pct, 2)} for p in posiciones]
    efectivo = broker.efectivo()

    # 4. Claude: cribado y decisión
    from agente.analista import Analista

    analista = Analista()
    try:
        cribado = analista.cribar(list(resumenes.values()), pos_dict, efectivo)
        decision = None
        if cribado and cribado.candidato and cribado.candidato.upper() in resumenes and cribado.accion_candidata != "ninguna":
            decision = analista.decidir(cribado, resumenes[cribado.candidato.upper()], pos_dict,
                                        efectivo, cfg.max_por_operacion)
    finally:
        diario.sumar_gasto_ia(analista.gasto_usd)

    diario.registrar_decision({
        "cribado": cribado.model_dump() if cribado else None,
        "decision": decision.model_dump() if decision else None,
        "coste_usd": round(analista.gasto_usd, 4),
    })
    print(f"Coste de Claude en este ciclo: {analista.gasto_usd:.4f} $")
    if cribado:
        print(f"Cribado: {cribado.motivo}")
    if not decision or decision.accion == "mantener":
        print("Decisión: mantener." + (f" {decision.razonamiento}" if decision else ""))
        return

    # 5. Validación de riesgo y ejecución
    simbolo = decision.simbolo.upper()
    ops = diario.operaciones_ultimos_dias()
    precio = resumenes.get(simbolo, {}).get("precio")
    if precio is None:
        print(f"Decisión descartada: {simbolo} no está entre los valores analizados")
        return
    if decision.accion == "comprar":
        v = riesgo.validar_compra(simbolo, decision.importe, efectivo, ops, posiciones, cfg)
        if not v.permitido:
            print(f"Compra bloqueada por riesgo: {v.motivo}")
            return
        limite = precio * 1.003  # no pagar más de un 0,3 % sobre el último cierre
        texto = (f"COMPRAR {simbolo} por {v.importe:.2f} (límite {limite:.2f}) | confianza {decision.confianza}/10\n"
                 f"Ventaja: {decision.ventaja}\nRiesgo: {decision.riesgo_principal}")
        if confirmar(texto, cfg):
            orden = broker.comprar(simbolo, v.importe, precio_limite=limite)
            diario.registrar_operacion(broker.nombre, "comprar", simbolo, v.importe, precio, orden, decision.ventaja)
            print(f"Orden enviada: {orden}")
    else:
        v = riesgo.validar_venta(simbolo, posiciones, ops, cfg)
        if not v.permitido:
            print(f"Venta bloqueada por riesgo: {v.motivo}")
            return
        pos = next(p for p in posiciones if p.simbolo == simbolo)
        if confirmar(f"VENDER todo {simbolo} (valor {pos.valor:.2f}, {pos.pnl_pct:+.1f}%)\n{decision.razonamiento}", cfg):
            orden = broker.vender_todo(simbolo)
            diario.registrar_operacion(broker.nombre, "vender", simbolo, pos.valor, pos.precio_actual, orden,
                                       decision.razonamiento[:200])
            print(f"Orden enviada: {orden}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Agente de trading con Claude")
    ap.add_argument("--sin-ia", action="store_true", help="solo límites y stop-loss")
    ap.add_argument("--estado", action="store_true", help="muestra la situación y sale")
    args = ap.parse_args(argv)

    cfg = cargar_config()
    if cfg.broker == "alpaca" and not cfg.alpaca_paper:
        print("⚠️  MODO DINERO REAL (Alpaca)")
    broker = crear_broker(cfg)
    diario = Diario(cfg.carpeta_datos)
    if args.estado:
        mostrar_estado(broker, diario, cfg)
        return
    ciclo(cfg, broker, diario, usar_ia=not args.sin_ia)


if __name__ == "__main__":
    sys.exit(main())
