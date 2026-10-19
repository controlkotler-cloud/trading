"""Auditoría: ¿por qué el agente real no se parece al backtest?

    python -m agente.auditoria datos/operaciones.csv [datos/decisiones.jsonl]

Reconstruye cada operación real con las mismas velas de 5 minutos que vio el agente y mide:
- Hora de entrada (¿en los últimos minutos de la sesión?) y si la posición pasó la noche.
- Recorrido a favor antes de salir: cuánto llegó a ganar en algún momento.
- Deslizamiento de la salida: a qué precio vendió frente al stop teórico (huecos de apertura, pasadas cada 2 min).
- Si la señal de compra existía con la vela YA CERRADA o solo con la vela a medio formar.
Después ejecuta el backtest sobre los mismos días y los mismos valores vigilados, para comparar.
"""

import argparse
import csv
import json
from datetime import timedelta
from pathlib import Path

from agente import momentum
from agente.backtest_momentum import Parametros, _utc, descargar, simular
from agente.brokers.base import Vela


def emparejar(operaciones: list[dict]) -> list[dict]:
    """Une cada compra con la venta siguiente del mismo valor (las ventas parciales cuentan como salida)."""
    abiertas: dict[str, dict] = {}
    cerradas = []
    for o in operaciones:
        s = o["simbolo"]
        if o["accion"] == "comprar":
            abiertas[s] = {"simbolo": s, "entrada_t": _utc(o["fecha"]), "entrada": float(o["precio"]),
                           "motivo": o.get("motivo", "")}
        elif o["accion"] == "vender" and s in abiertas:
            op = abiertas.pop(s)
            op.update(salida_t=_utc(o["fecha"]), salida=float(o["precio"]), motivo_salida=o.get("motivo", ""))
            cerradas.append(op)
    return cerradas + [dict(op, salida_t=None, salida=None) for op in abiertas.values()]


def analizar(op: dict, velas: list[Vela], minutos: int, trailing_pct: float, barras: int, volumen: float) -> dict:
    t_in, t_out = op["entrada_t"], op["salida_t"]
    paso = timedelta(minutes=minutos)
    inicio = [_utc(v.fecha) for v in velas]
    # vela en curso cuando compró y velas ya cerradas en ese momento
    cerradas = [v for v, t in zip(velas, inicio) if t + paso <= t_in]
    en_curso = [v for v, t in zip(velas, inicio) if t <= t_in < t + paso]
    senal_cerrada = momentum.senal_entrada(cerradas[-81:], barras, volumen).entrar if cerradas else False
    durante = [v for v, t in zip(velas, inicio) if t_in <= t + paso and (t_out is None or t <= t_out)]
    sesion = momentum.minutos_sesion(t_in.isoformat())
    r = {
        "simbolo": op["simbolo"], "entrada": t_in.strftime("%m-%d %H:%M"),
        "min_al_cierre": sesion[1] if sesion else None,
        "senal_vela_cerrada": senal_cerrada, "habia_vela_en_curso": bool(en_curso),
        "noche": t_out is not None and t_out.date() != t_in.date(),
        "resultado_pct": None if op["salida"] is None else round((op["salida"] / op["entrada"] - 1) * 100, 2),
        "max_a_favor_pct": round((max(v.maximo for v in durante) / op["entrada"] - 1) * 100, 2) if durante else None,
        "deslizamiento_pct": None,
    }
    if op["salida"] is not None and durante:
        maximo = max([op["entrada"]] + [v.cierre for v in durante[:-1]])
        stop = maximo * (1 - trailing_pct / 100)
        r["deslizamiento_pct"] = round((op["salida"] / stop - 1) * 100, 2)
    return r


def vigilancia_por_dia(ruta: Path) -> dict[str, list[str]]:
    dias = {}
    if ruta.exists():
        for linea in ruta.read_text().splitlines():
            d = json.loads(linea)
            if "seleccion" in d:
                dias[d["fecha"][:10]] = d["seleccion"]["vigilar"]
    return dias


def informe(ops: list[dict], series: dict[str, list[Vela]], p: Parametros, minutos: int,
            vigilados: list[str], referencia: list[Vela] | None) -> str:
    filas = [analizar(op, series[op["simbolo"]], minutos, p.trailing_pct, p.barras_ruptura, p.volumen_minimo)
             for op in ops if op["simbolo"] in series]
    cerradas = [f for f in filas if f["resultado_pct"] is not None]
    lineas = ["\nAUDITORÍA DE LAS OPERACIONES REALES", "",
              f"{'Valor':<6}{'Entrada (UTC)':<15}{'Min. al cierre':>15}{'Señal vela cerrada':>20}{'Noche':>7}"
              f"{'Máx. a favor':>14}{'Resultado':>11}{'Desliz.':>9}"]
    for f in filas:
        lineas.append(f"{f['simbolo']:<6}{f['entrada']:<15}{str(f['min_al_cierre']):>15}"
                      f"{'sí' if f['senal_vela_cerrada'] else 'NO':>20}{'sí' if f['noche'] else '':>7}"
                      f"{_pct(f['max_a_favor_pct']):>14}{_pct(f['resultado_pct']):>11}{_pct(f['deslizamiento_pct']):>9}")
    if cerradas:
        n = len(cerradas)
        sin_senal = sum(not f["senal_vela_cerrada"] for f in filas)
        tarde = sum(1 for f in filas if f["min_al_cierre"] is not None and f["min_al_cierre"] <= 30)
        noche = [f for f in cerradas if f["noche"]]
        desl = [f["deslizamiento_pct"] for f in cerradas if f["deslizamiento_pct"] is not None]
        lineas += [
            "",
            f"Compras SIN señal con la vela cerrada (compró con una vela a medio formar): {sin_senal} de {len(filas)}",
            f"Compras en los últimos 30 min de la sesión: {tarde} de {len(filas)}",
            f"Operaciones que pasaron la noche: {len(noche)} de {n}, resultado medio "
            f"{_pct(sum(f['resultado_pct'] for f in noche) / len(noche)) if noche else '-'}",
            f"Deslizamiento medio de la salida frente al stop teórico: {_pct(sum(desl) / len(desl)) if desl else '-'}",
            f"Recorrido a favor medio antes de salir: {_pct(sum(f['max_a_favor_pct'] for f in cerradas) / n)}",
        ]
    # backtest sobre los mismos días
    desde = min(op["entrada_t"] for op in ops).strftime("%Y-%m-%d 13:30:00+00:00")
    for nombre, universo in (("valores vigilados", vigilados), ("universo completo", list(series))):
        sub = {s: v for s, v in series.items() if s in universo}
        if not sub:
            continue
        r = simular(sub, p, referencia, desde=desde)
        lineas.append(f"\nBacktest mismos días ({nombre}, {len(sub)} valores): {r.rentabilidad_pct:+.2f}% | "
                      f"{len(r.operaciones)} operaciones | aciertos {r.aciertos_pct:.0f}% | "
                      f"media {sum(r.operaciones) / len(r.operaciones) if r.operaciones else 0:+.2f}%")
    reales = [f["resultado_pct"] for f in cerradas]
    if reales:
        lineas.append(f"Real: {len(reales)} operaciones cerradas | aciertos "
                      f"{100 * sum(x > 0 for x in reales) / len(reales):.0f}% | media {sum(reales) / len(reales):+.2f}%")
    return "\n".join(lineas)


def _pct(x) -> str:
    return "-" if x is None else f"{x:+.2f}%"


def main(argv: list[str] | None = None) -> None:
    from agente.config import cargar_config

    cfg = cargar_config()
    ap = argparse.ArgumentParser(description="Compara las operaciones reales con el backtest")
    ap.add_argument("operaciones", nargs="?", default="datos/operaciones.csv")
    ap.add_argument("decisiones", nargs="?", default="datos/decisiones.jsonl")
    args = ap.parse_args(argv)

    with open(args.operaciones) as f:
        ops = emparejar(list(csv.DictReader(f)))
    if not ops:
        raise SystemExit("No hay operaciones.")
    dias = (max(op["entrada_t"] for op in ops) - min(op["entrada_t"] for op in ops)).days + 6
    vig = sorted({s for lista in vigilancia_por_dia(Path(args.decisiones)).values() for s in lista}
                 | {op["simbolo"] for op in ops})
    simbolos = sorted(set(cfg.universo) | set(vig))
    series = descargar(simbolos, dias, cfg.minutos_vela)
    p = Parametros(cfg.capital_simulado, cfg.max_posiciones, cfg.pct_por_posicion, cfg.trailing_pct,
                   cfg.barras_ruptura, cfg.volumen_minimo, filtro_mercado=cfg.filtro_mercado)
    print(informe(ops, series, p, cfg.minutos_vela, vig, series.get("QQQ")))


if __name__ == "__main__":
    main()
