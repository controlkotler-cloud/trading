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
    # mejoras "de trader" (desactivadas por defecto)
    filtro_mercado: bool = False      # solo compra si QQQ va por encima de su media intradía
    stop_atr: float = 0.0             # stop adaptado a lo que se mueve cada valor (x su rango medio)
    evitar_apertura_min: int = 0      # no comprar en los primeros minutos de la sesión
    evitar_cierre_min: int = 0        # ni en los últimos
    parcial_pct: float = 0.0          # vender la mitad al ganar este %, el resto sigue con el stop
    cerrar_al_cierre: bool = False    # no dormir con posiciones (evita saltos de la noche)


@dataclass
class Resultado:
    rentabilidad_pct: float
    referencia_pct: float  # comprar y mantener a partes iguales
    max_caida_pct: float
    operaciones: list[float] = field(default_factory=list)  # % de cada operación cerrada
    curva: list[float] = field(default_factory=list)
    dias: int = 1

    @property
    def aciertos_pct(self) -> float:
        return 100 * sum(r > 0 for r in self.operaciones) / len(self.operaciones) if self.operaciones else 0.0


def simular(series: dict[str, list[Vela]], p: Parametros, referencia: list[Vela] | None = None) -> Resultado:
    """referencia: velas del mercado general (QQQ) para el filtro de mercado."""
    coste = p.coste_pct / 100
    efectivo = p.capital
    pos: dict[str, dict] = {}         # simbolo -> {cantidad, entrada, maximo, distancia, parcial}
    pendientes: dict[str, float] = {}  # compras a ejecutar en la apertura de la siguiente vela -> distancia del stop
    ops, curva = [], []
    ultimo: dict[str, float] = {}
    tiempos = sorted({v.fecha for velas in series.values() for v in velas})
    por_tiempo = {s: {v.fecha: i for i, v in enumerate(velas)} for s, velas in series.items()}
    ref_idx = {v.fecha: i for i, v in enumerate(referencia)} if referencia else {}
    favorable = True

    for t in tiempos:
        if p.filtro_mercado and t in ref_idx:
            j = ref_idx[t]
            favorable = momentum.mercado_favorable(referencia[max(0, j - 60):j + 1])
        sesion = momentum.minutos_sesion(t)
        for s, velas in series.items():
            i = por_tiempo[s].get(t)
            if i is None:
                continue
            v = velas[i]
            # 1. compras pendientes: a la apertura
            if s in pendientes and s not in pos and len(pos) < p.max_posiciones:
                patrimonio = efectivo + sum(x["cantidad"] * ultimo.get(k, x["entrada"]) for k, x in pos.items())
                importe = momentum.tamano_posicion(patrimonio, efectivo, p.pct_por_posicion)
                if importe >= 1:
                    precio = v.apertura * (1 + coste)
                    pos[s] = {"cantidad": importe / precio, "entrada": precio, "maximo": v.apertura,
                              "distancia": pendientes[s], "parcial": False}
                    efectivo -= importe
            pendientes.pop(s, None)
            # 2. stop dinámico dentro de la vela; si no salta, venta parcial al llegar al objetivo
            if s in pos:
                x = pos[s]
                stop = x["maximo"] * (1 - x["distancia"] / 100)
                if v.minimo <= stop:
                    salida = min(stop, v.apertura) * (1 - coste)
                    efectivo += x["cantidad"] * salida
                    ops.append((salida / x["entrada"] - 1) * 100)
                    del pos[s]
                else:
                    objetivo = x["entrada"] * (1 + p.parcial_pct / 100)
                    if p.parcial_pct > 0 and not x["parcial"] and v.maximo >= objetivo:
                        salida = max(objetivo, v.apertura) * (1 - coste)
                        mitad = x["cantidad"] / 2
                        efectivo += mitad * salida
                        ops.append((salida / x["entrada"] - 1) * 100)
                        x["cantidad"] -= mitad
                        x["parcial"] = True
                    x["maximo"] = max(x["maximo"], v.cierre)
            # 3. cierre de la sesión: no dormir con posiciones
            ultima_vela = sesion is not None and sesion[1] <= 15
            if p.cerrar_al_cierre and ultima_vela and s in pos:
                x = pos.pop(s)
                salida = v.cierre * (1 - coste)
                efectivo += x["cantidad"] * salida
                ops.append((salida / x["entrada"] - 1) * 100)
            ultimo[s] = v.cierre
            # 4. señal al cierre de la vela -> compra en la siguiente
            if s in pos or len(pos) + len(pendientes) >= p.max_posiciones:
                continue
            if p.filtro_mercado and not favorable:
                continue
            if sesion is not None and not momentum.en_horario(*sesion, p.evitar_apertura_min, p.evitar_cierre_min):
                continue
            if p.cerrar_al_cierre and ultima_vela:
                continue
            ventana = velas[max(0, i - 80):i + 1]
            senal = momentum.senal_entrada(ventana, p.barras_ruptura, p.volumen_minimo)
            if senal.entrar:
                pendientes[s] = momentum.distancia_stop(ventana, p.trailing_pct, p.stop_atr)
        curva.append(efectivo + sum(x["cantidad"] * ultimo[k] for k, x in pos.items()))

    for s, x in pos.items():  # cerrar lo abierto al final para contabilizarlo
        salida = ultimo[s] * (1 - coste)
        ops.append((salida / x["entrada"] - 1) * 100)
    final = curva[-1] if curva else p.capital
    pico, max_caida = 0.0, 0.0
    for c in curva:
        pico = max(pico, c)
        max_caida = max(max_caida, (pico - c) / pico * 100)
    referencia_pct = sum(velas[-1].cierre / velas[0].apertura - 1 for velas in series.values()) / len(series) * 100
    dias = len({t[:10] for t in tiempos}) or 1
    return Resultado((final / p.capital - 1) * 100, referencia_pct, max_caida, ops, curva, dias)


def descargar(simbolos: list[str], dias: int, minutos: int = 15) -> dict[str, list[Vela]]:
    series = {}
    usar_alpaca = os.environ.get("ALPACA_API_KEY") and os.environ.get("ALPACA_SECRET_KEY")
    for s in simbolos:
        try:
            if usar_alpaca:
                from agente.brokers.alpaca import BrokerAlpaca

                velas = BrokerAlpaca(paper=True).intradia(s, minutos, dias)
            else:
                import yfinance as yf

                df = yf.Ticker(s).history(period=f"{min(dias, 59)}d", interval=f"{minutos}m", auto_adjust=True)
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
        f"Trailing {p.trailing_pct}% | {p.max_posiciones} posiciones de {p.pct_por_posicion:.0%} | ruptura de "
        f"{p.barras_ruptura} velas | volumen x{p.volumen_minimo} | coste {p.coste_pct}%\n",
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


MEJORAS = [
    ("1. Filtro de mercado (QQQ al alza)", {"filtro_mercado": True}),
    ("2. Stop adaptado al valor (4x rango)", {"stop_atr": 4.0}),
    ("   (sensibilidad: 3x rango)", {"stop_atr": 3.0}),
    ("   (sensibilidad: 6x rango)", {"stop_atr": 6.0}),
    ("3. Sin compras 15' tras abrir ni 30' antes de cerrar", {"evitar_apertura_min": 15, "evitar_cierre_min": 30}),
    ("4. Vender la mitad al +3 %", {"parcial_pct": 3.0}),
    ("5. Cerrar todo al final del día", {"cerrar_al_cierre": True}),
]


def _partir(series: dict[str, list[Vela]]) -> tuple[dict, dict]:
    tiempos = sorted({v.fecha for velas in series.values() for v in velas})
    corte = tiempos[len(tiempos) // 2]
    a = {s: [v for v in velas if v.fecha < corte] for s, velas in series.items()}
    b = {s: [v for v in velas if v.fecha >= corte] for s, velas in series.items()}
    return {s: v for s, v in a.items() if len(v) > 100}, {s: v for s, v in b.items() if len(v) > 100}


def comparar(series: dict[str, list[Vela]], base: Parametros, referencia: list[Vela] | None) -> str:
    """Prueba cada mejora por separado y todas juntas, en el periodo completo y en cada mitad.

    Una mejora se da por buena solo si gana más que la versión actual en LAS DOS mitades (no vale
    que funcione solo en una: sería casualidad), o si gana casi lo mismo con bastante menos caída.
    """
    from dataclasses import replace

    mitad1, mitad2 = _partir(series)

    def fila(nombre: str, p: Parametros):
        r, r1, r2 = (simular(x, p, referencia) for x in (series, mitad1, mitad2))
        return nombre, r, r1, r2

    filas = [fila("Actual (sin mejoras)", base)]
    for nombre, cambios in MEJORAS:
        filas.append(fila(nombre, replace(base, **cambios)))
    _, b, b1, b2 = filas[0]
    buenas = {}
    for nombre, r, r1, r2 in filas[1:]:
        gana = r1.rentabilidad_pct > b1.rentabilidad_pct and r2.rentabilidad_pct > b2.rentabilidad_pct
        similar_menos_riesgo = (r1.rentabilidad_pct >= b1.rentabilidad_pct - 1 and r2.rentabilidad_pct >= b2.rentabilidad_pct - 1
                                and r.max_caida_pct <= 0.8 * b.max_caida_pct)
        if (gana or similar_menos_riesgo) and not nombre.startswith(" "):
            buenas[nombre] = dict(next(c for n, c in MEJORAS if n == nombre))
    juntas = {}
    for c in buenas.values():
        juntas.update(c)
    if juntas:
        filas.append(fila("=> Las que aprueban, juntas", replace(base, **juntas)))
    todas = {}
    for n, c in MEJORAS:
        if not n.startswith(" "):
            todas.update(c)
    filas.append(fila("Todas juntas (aprueben o no)", replace(base, **todas)))

    lineas = [
        f"\nComparativa de mejoras | {', '.join(series)} | {b.dias} sesiones | capital {base.capital:.0f}",
        f"Base: trailing {base.trailing_pct}% | {base.max_posiciones} posiciones de {base.pct_por_posicion:.0%} | "
        f"ruptura {base.barras_ruptura} velas | volumen x{base.volumen_minimo} | coste {base.coste_pct}%\n",
        f"{'Variante':<52}{'Total':>8}{'1ª mitad':>10}{'2ª mitad':>10}{'Caída':>8}{'Ops/día':>9}{'Aciertos':>10}",
    ]
    for nombre, r, r1, r2 in filas:
        lineas.append(f"{nombre:<52}{r.rentabilidad_pct:>+7.1f}%{r1.rentabilidad_pct:>+9.1f}%{r2.rentabilidad_pct:>+9.1f}%"
                      f"{r.max_caida_pct:>7.1f}%{len(r.operaciones) / r.dias:>9.1f}{r.aciertos_pct:>9.0f}%")
    lineas += ["", f"Comprar y mantener lo mismo: {b.referencia_pct:+.1f}%",
               "Aprueban (mejoran en las dos mitades, o igual con menos caída): "
               + (", ".join(buenas) if buenas else "ninguna"),
               "RESULTADO_JSON " + __import__("json").dumps(juntas)]
    return "\n".join(lineas)


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
    ap.add_argument("--minutos", type=int, default=cfg.minutos_vela, help="duración de cada vela")
    ap.add_argument("--barras", type=int, default=cfg.barras_ruptura, help="velas para el máximo a romper")
    ap.add_argument("--volumen", type=float, default=cfg.volumen_minimo, help="volumen mínimo (x la media)")
    ap.add_argument("--comparar", action="store_true", help="prueba cada mejora por separado y juntas")
    args = ap.parse_args(argv)

    series = descargar([s.upper() for s in args.simbolos], args.dias, args.minutos)
    if not series:
        raise SystemExit("No hay datos.")
    p = Parametros(args.capital, args.posiciones, args.pct, args.trailing, args.barras, args.volumen, args.coste)
    if args.comparar:
        referencia = series.get("QQQ") or descargar(["QQQ"], args.dias, args.minutos).get("QQQ")
        print(comparar(series, p, referencia))
    else:
        print(informe(series, p))


if __name__ == "__main__":
    main()
