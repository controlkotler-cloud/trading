"""Backtest de la estrategia de impulso con stop dinámico, sobre velas intradía de 15 minutos.

    python -m agente.backtest_momentum                    # universo por defecto, últimos 60 días
    python -m agente.backtest_momentum NVDA TSLA --trailing 4 --coste 0.05

Simula exactamente las reglas del operador, con todas las posiciones compartiendo el mismo capital:
- La señal se calcula al cierre de una vela y la compra se hace a la APERTURA de la siguiente.
- El stop dinámico actúa dentro de la vela (como una orden stop puesta en el broker): si el mínimo
  toca el stop se vende a ese precio (o a la apertura si abrió por debajo, como pasa en la realidad).
- Cada compra y cada venta paga un coste (diferencia de precio + deslizamiento), 0,05 % por defecto.
- Se compara con comprar a partes iguales los mismos valores y no tocarlos.

Datos: Alpaca si hay claves (más historia), si no Yahoo (máximo 60 días en velas de 15 minutos).
"""

import argparse
import os
from dataclasses import dataclass, field

from agente import momentum
from agente.brokers.base import Vela


@dataclass
class Parametros:
    capital: float = 200.0
    max_posiciones: int = 3
    pct_por_posicion: float = 0.33
    trailing_pct: float = 3.0
    barras_ruptura: int = 20
    volumen_minimo: float = 1.5
    coste_pct: float = 0.05


@dataclass
class Resultado:
    rentabilidad_pct: float
    referencia_pct: float  # comprar y mantener a partes iguales
    max_caida_pct: float
    operaciones: list[float] = field(default_factory=list)  # % de cada operación cerrada
    curva: list[float] = field(default_factory=list)

    @property
    def aciertos_pct(self) -> float:
        return 100 * sum(r > 0 for r in self.operaciones) / len(self.operaciones) if self.operaciones else 0.0


def simular(series: dict[str, list[Vela]], p: Parametros) -> Resultado:
    coste = p.coste_pct / 100
    efectivo = p.capital
    pos: dict[str, dict] = {}       # simbolo -> {cantidad, entrada, maximo}
    pendientes: list[str] = []      # compras a ejecutar en la apertura de la siguiente vela
    ops, curva = [], []
    ultimo: dict[str, float] = {}
    indices = {s: 0 for s in series}
    tiempos = sorted({v.fecha for velas in series.values() for v in velas})
    por_tiempo = {s: {v.fecha: i for i, v in enumerate(velas)} for s, velas in series.items()}

    for t in tiempos:
        for s, velas in series.items():
            i = por_tiempo[s].get(t)
            if i is None:
                continue
            v = velas[i]
            indices[s] = i
            # 1. compras pendientes: a la apertura
            if s in pendientes and s not in pos and len(pos) < p.max_posiciones:
                patrimonio = efectivo + sum(x["cantidad"] * ultimo.get(k, x["entrada"]) for k, x in pos.items())
                importe = momentum.tamano_posicion(patrimonio, efectivo, p.pct_por_posicion)
                if importe >= 1:
                    precio = v.apertura * (1 + coste)
                    pos[s] = {"cantidad": importe / precio, "entrada": precio, "maximo": v.apertura}
                    efectivo -= importe
            if s in pendientes:
                pendientes.remove(s)
            # 2. stop dinámico dentro de la vela
            if s in pos:
                x = pos[s]
                stop = x["maximo"] * (1 - p.trailing_pct / 100)
                if v.minimo <= stop:
                    salida = min(stop, v.apertura) * (1 - coste)
                    efectivo += x["cantidad"] * salida
                    ops.append((salida / x["entrada"] - 1) * 100)
                    del pos[s]
                else:
                    x["maximo"] = max(x["maximo"], v.cierre)
            ultimo[s] = v.cierre
            # 3. señal al cierre de la vela -> compra en la siguiente
            if s not in pos and len(pos) + len(pendientes) < p.max_posiciones:
                senal = momentum.senal_entrada(velas[max(0, i - 80):i + 1], p.barras_ruptura, p.volumen_minimo)
                if senal.entrar:
                    pendientes.append(s)
        curva.append(efectivo + sum(x["cantidad"] * ultimo[k] for k, x in pos.items()))

    for s, x in pos.items():  # cerrar lo abierto al final para contabilizarlo
        salida = ultimo[s] * (1 - coste)
        ops.append((salida / x["entrada"] - 1) * 100)
    final = curva[-1] if curva else p.capital
    pico, max_caida = 0.0, 0.0
    for c in curva:
        pico = max(pico, c)
        max_caida = max(max_caida, (pico - c) / pico * 100)
    referencia = sum(velas[-1].cierre / velas[0].apertura - 1 for velas in series.values()) / len(series) * 100
    return Resultado((final / p.capital - 1) * 100, referencia, max_caida, ops, curva)


def descargar(simbolos: list[str], dias: int) -> dict[str, list[Vela]]:
    series = {}
    usar_alpaca = os.environ.get("ALPACA_API_KEY") and os.environ.get("ALPACA_SECRET_KEY")
    for s in simbolos:
        try:
            if usar_alpaca:
                from agente.brokers.alpaca import BrokerAlpaca

                velas = BrokerAlpaca(paper=True).intradia(s, 15, dias)
            else:
                import yfinance as yf

                df = yf.Ticker(s).history(period=f"{min(dias, 59)}d", interval="15m", auto_adjust=True)
                velas = [Vela(str(i), r.Open, r.High, r.Low, r.Close, r.Volume) for i, r in df.iterrows()]
        except Exception as e:
            print(f"{s}: sin datos ({e})")
            continue
        if len(velas) > 100:
            series[s] = velas
    return series


def informe(series: dict[str, list[Vela]], p: Parametros) -> str:
    r = simular(series, p)
    ops = r.operaciones
    media = sum(ops) / len(ops) if ops else 0
    ganan = [o for o in ops if o > 0]
    pierden = [o for o in ops if o <= 0]
    primera = min(v[0].fecha for v in series.values())
    ultima = max(v[-1].fecha for v in series.values())
    return "\n".join([
        f"\nBacktest momentum: {', '.join(series)} | {primera[:10]} -> {ultima[:10]}",
        f"Trailing {p.trailing_pct}% | {p.max_posiciones} posiciones de {p.pct_por_posicion:.0%} | coste {p.coste_pct}%\n",
        f"Rentabilidad de la estrategia: {r.rentabilidad_pct:+.1f}%  ({p.capital:.0f} -> {p.capital * (1 + r.rentabilidad_pct / 100):.0f})",
        f"Comprar y mantener lo mismo:   {r.referencia_pct:+.1f}%",
        f"Caída máxima:                  {r.max_caida_pct:.1f}%",
        f"Operaciones: {len(ops)} | aciertos {r.aciertos_pct:.0f}% | media {media:+.2f}% por operación",
        f"Ganadoras de media {sum(ganan) / len(ganan) if ganan else 0:+.2f}% | perdedoras {sum(pierden) / len(pierden) if pierden else 0:+.2f}%",
        "",
        "Cómo leerlo: 60 días es muy poco y el resultado depende mucho de si el mercado subió o bajó.",
        "Prueba varios trailing (2, 3, 4, 6) y varios grupos de valores. Si solo gana con un ajuste concreto,",
        "probablemente es casualidad. Si no bate a comprar y mantener, el esfuerzo no compensa.",
    ])


def main(argv: list[str] | None = None) -> None:
    from agente.config import cargar_config

    cfg = cargar_config()
    ap = argparse.ArgumentParser(description="Backtest de la estrategia de impulso intradía")
    ap.add_argument("simbolos", nargs="*", default=list(cfg.universo))
    ap.add_argument("--dias", type=int, default=60)
    ap.add_argument("--capital", type=float, default=cfg.capital_simulado)
    ap.add_argument("--trailing", type=float, default=cfg.trailing_pct)
    ap.add_argument("--posiciones", type=int, default=cfg.max_posiciones)
    ap.add_argument("--pct", type=float, default=cfg.pct_por_posicion)
    ap.add_argument("--coste", type=float, default=0.05)
    args = ap.parse_args(argv)

    series = descargar([s.upper() for s in args.simbolos], args.dias)
    if not series:
        raise SystemExit("No hay datos.")
    p = Parametros(args.capital, args.posiciones, args.pct, args.trailing, cfg.barras_ruptura,
                   cfg.volumen_minimo, args.coste)
    print(informe(series, p))


if __name__ == "__main__":
    main()
