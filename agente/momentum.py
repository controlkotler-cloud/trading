"""Estrategia de impulso (momentum) con stop dinámico: lo que haría un trader pegado a la pantalla.

- ENTRADA: el precio rompe el máximo de las últimas N velas, va por encima de su media (tendencia)
  y con más volumen de lo normal (hay interés real, no ruido).
- SALIDA: stop dinámico (trailing stop). Se guarda el precio máximo alcanzado desde la compra y
  se vende si cae un TRAILING_PCT desde ese máximo. El stop solo sube, nunca baja:
  si el valor sube, se deja correr la ganancia; si se gira, se sale.
- TAMAÑO: cada posición es un % del patrimonio ACTUAL, así las ganancias se reinvierten solas
  (interés compuesto), y las pérdidas también reducen el tamaño (protege de rachas malas).

Todo son funciones puras (sin red ni disco) para poder probarlas y usarlas en el backtest.
"""

from dataclasses import dataclass

from agente.brokers.base import Vela


@dataclass
class Senal:
    entrar: bool
    motivo: str


def ema(valores: list[float], periodo: int) -> float:
    k = 2 / (periodo + 1)
    e = valores[0]
    for v in valores[1:]:
        e = v * k + e * (1 - k)
    return e


def senal_entrada(velas: list[Vela], barras_ruptura: int = 20, volumen_minimo: float = 1.5) -> Senal:
    """¿Rompe al alza con tendencia y volumen en la última vela cerrada?"""
    if len(velas) < barras_ruptura + 2:
        return Senal(False, "pocos datos")
    ultima = velas[-1]
    previas = velas[-barras_ruptura - 1:-1]
    maximo_previo = max(v.maximo for v in previas)
    if ultima.cierre <= maximo_previo:
        return Senal(False, "sin ruptura")
    media = ema([v.cierre for v in velas[-60:]], 20)
    if ultima.cierre <= media:
        return Senal(False, "por debajo de su media")
    vol_medio = sum(v.volumen for v in previas) / len(previas)
    if vol_medio > 0 and ultima.volumen < volumen_minimo * vol_medio:
        return Senal(False, "sin volumen")
    subida = (ultima.cierre / maximo_previo - 1) * 100
    return Senal(True, f"rompe máximo de {barras_ruptura} velas (+{subida:.2f}%) con volumen "
                       f"x{ultima.volumen / vol_medio:.1f}" if vol_medio else "rompe máximo")


def actualizar_trailing(maximo: float, precio: float, trailing_pct: float) -> tuple[float, float, bool]:
    """Devuelve (nuevo máximo, precio de stop, ¿vender?). El stop solo sube."""
    maximo = max(maximo, precio)
    stop = maximo * (1 - trailing_pct / 100)
    return maximo, stop, precio <= stop


def tamano_posicion(patrimonio: float, efectivo: float, pct_por_posicion: float) -> float:
    """Importe a invertir: % del patrimonio actual (reinversión automática), limitado al efectivo."""
    return round(max(0.0, min(patrimonio * pct_por_posicion, efectivo)), 2)


def ranking_impulso(resumenes: dict[str, dict]) -> list[str]:
    """Ordena los valores por fuerza de la tendencia reciente (para elegir qué vigilar hoy).

    Puntuación: subida de 20 días + subida de 5 días, solo valores por encima de su media de 50.
    """
    candidatos = []
    for s, r in resumenes.items():
        if r.get("media_50") and r["precio"] < r["media_50"]:
            continue
        candidatos.append((r["cambio_20d_pct"] + r["cambio_5d_pct"], s))
    return [s for _, s in sorted(candidatos, reverse=True)]
