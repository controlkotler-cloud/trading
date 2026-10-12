"""Indicadores técnicos simples calculados sin librerías externas.

Se calculan en código (no los calcula la IA) para que sean exactos y gratuitos.
"""

from dataclasses import asdict, dataclass

from agente.brokers.base import Vela


@dataclass
class Resumen:
    simbolo: str
    precio: float
    cambio_5d_pct: float
    cambio_20d_pct: float
    media_20: float
    media_50: float | None
    rsi_14: float
    volatilidad_20d_pct: float
    maximo_60d: float
    minimo_60d: float
    ruptura_maximos: bool  # hoy cierra por encima del máximo de cierre de los 60 días anteriores (y ayer no)

    def como_dict(self) -> dict:
        return {k: round(v, 2) if isinstance(v, float) else v for k, v in asdict(self).items()}


def media(valores: list[float]) -> float:
    return sum(valores) / len(valores)


def rsi(cierres: list[float], periodo: int = 14) -> float:
    """RSI de Wilder. 0-100: <30 sobrevendido, >70 sobrecomprado."""
    if len(cierres) <= periodo:
        return 50.0
    cambios = [b - a for a, b in zip(cierres, cierres[1:])]
    ganancias = [max(c, 0) for c in cambios]
    perdidas = [max(-c, 0) for c in cambios]
    gan = media(ganancias[:periodo])
    per = media(perdidas[:periodo])
    for g, p in zip(ganancias[periodo:], perdidas[periodo:]):
        gan = (gan * (periodo - 1) + g) / periodo
        per = (per * (periodo - 1) + p) / periodo
    if per == 0:
        return 100.0
    return 100 - 100 / (1 + gan / per)


def volatilidad(cierres: list[float]) -> float:
    """Desviación típica de los rendimientos diarios, en %."""
    rend = [(b / a - 1) * 100 for a, b in zip(cierres, cierres[1:])]
    if len(rend) < 2:
        return 0.0
    m = media(rend)
    return (sum((r - m) ** 2 for r in rend) / (len(rend) - 1)) ** 0.5


def resumir(simbolo: str, velas: list[Vela]) -> Resumen:
    if len(velas) < 21:
        raise ValueError(f"{simbolo}: hacen falta al menos 21 velas, hay {len(velas)}")
    cierres = [v.cierre for v in velas]
    precio = cierres[-1]
    return Resumen(
        simbolo=simbolo,
        precio=precio,
        cambio_5d_pct=(precio / cierres[-6] - 1) * 100,
        cambio_20d_pct=(precio / cierres[-21] - 1) * 100,
        media_20=media(cierres[-20:]),
        media_50=media(cierres[-50:]) if len(cierres) >= 50 else None,
        rsi_14=rsi(cierres),
        volatilidad_20d_pct=volatilidad(cierres[-21:]),
        maximo_60d=max(v.maximo for v in velas[-60:]),
        minimo_60d=min(v.minimo for v in velas[-60:]),
        ruptura_maximos=precio > max(cierres[-61:-1]) and cierres[-2] <= max(cierres[-62:-2]),
    )
