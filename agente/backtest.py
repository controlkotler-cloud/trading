"""Backtester: prueba estrategias de reglas simples con datos históricos ANTES de arriesgar dinero.

    python -m agente.backtest SPY                 # todas las estrategias, 10 años
    python -m agente.backtest QQQ --anios 5 --coste 0.15

Para no engañarse:
- La señal se calcula con el cierre del día y se ejecuta en la APERTURA del día siguiente
  (no se usa información del futuro).
- Cada compra y cada venta paga un coste (comisión + diferencia de precio), por defecto 0,1 %.
- Los datos se parten en dos: "entrenamiento" (70 % más antiguo) y "prueba" (30 % más reciente).
  Una estrategia solo vale si funciona también en la parte de prueba.
- Todo se compara con "comprar y mantener": si no lo mejora, no merece la pena.
"""

import argparse
import random
from dataclasses import dataclass
from typing import Callable

from agente.brokers.base import Vela
from agente.indicadores import rsi

# Una estrategia recibe los cierres hasta hoy y dice si quiere estar dentro (True) o fuera (False)
Estrategia = Callable[[list[float]], bool]


def ema(valores: list[float], periodo: int) -> float:
    k = 2 / (periodo + 1)
    e = valores[0]
    for v in valores[1:]:
        e = v * k + e * (1 - k)
    return e


def comprar_y_mantener(cierres: list[float]) -> bool:
    return True


def precio_sobre_ema9(cierres: list[float]) -> bool:
    """Versión diaria de la idea "EMA9" de Instagram: dentro mientras el precio esté sobre su EMA de 9 días."""
    return cierres[-1] > ema(cierres[-60:], 9)


def cruce_medias_20_50(cierres: list[float]) -> bool:
    """Seguir la tendencia: dentro si la media de 20 días está por encima de la de 50."""
    if len(cierres) < 50:
        return False
    return sum(cierres[-20:]) / 20 > sum(cierres[-50:]) / 50


def tendencia_200(cierres: list[float]) -> bool:
    """Filtro clásico: dentro solo si el precio está sobre la media de 200 días."""
    if len(cierres) < 200:
        return False
    return cierres[-1] > sum(cierres[-200:]) / 200


ESTRATEGIAS: dict[str, Callable[[], Estrategia]] = {
    "comprar_y_mantener": lambda: comprar_y_mantener,
    "precio_sobre_ema9": lambda: precio_sobre_ema9,
    "cruce_medias_20_50": lambda: cruce_medias_20_50,
    "tendencia_200": lambda: tendencia_200,
    "rebote_rsi": lambda: _rebote_rsi_nueva(),  # compra RSI<30, vende RSI>55
}


def _rebote_rsi_nueva() -> Estrategia:
    estado = {"dentro": False}

    def f(cierres: list[float]) -> bool:
        r = rsi(cierres[-60:])
        if not estado["dentro"] and r < 30:
            estado["dentro"] = True
        elif estado["dentro"] and r > 55:
            estado["dentro"] = False
        return estado["dentro"]

    return f


@dataclass
class Resultado:
    nombre: str
    rentabilidad_pct: float
    rentabilidad_anual_pct: float
    max_caida_pct: float
    operaciones: int
    aciertos_pct: float
    tiempo_dentro_pct: float
    curva: list[float]
    rend_operaciones: list[float]


def simular(velas: list[Vela], estrategia: Estrategia, nombre: str = "", coste_pct: float = 0.1,
            calentamiento: int = 0) -> Resultado:
    """Simula invertir todo el capital cuando la estrategia dice 'dentro'.

    calentamiento: velas iniciales que solo sirven para calcular indicadores (no se opera).
    """
    coste = coste_pct / 100
    capital, unidades, dentro = 1.0, 0.0, False
    precio_entrada = 0.0
    curva, rend_ops = [], []
    dias_dentro = 0
    cierres = [v.cierre for v in velas]

    for i in range(max(calentamiento, 1), len(velas)):
        # La señal se decidió ayer al cierre; se ejecuta hoy a la apertura
        quiere = estrategia(cierres[:i])
        apertura = velas[i].apertura
        if quiere and not dentro:
            unidades = capital * (1 - coste) / apertura
            capital, dentro, precio_entrada = 0.0, True, apertura
        elif not quiere and dentro:
            capital = unidades * apertura * (1 - coste)
            rend_ops.append((apertura * (1 - coste) ** 2 / precio_entrada - 1) * 100)
            unidades, dentro = 0.0, False
        dias_dentro += dentro
        curva.append(capital + unidades * velas[i].cierre)

    if dentro:  # cerrar al final para contabilizar la última operación
        rend_ops.append((velas[-1].cierre * (1 - coste) ** 2 / precio_entrada - 1) * 100)

    final = curva[-1] if curva else 1.0
    anios = max(len(curva) / 252, 1 / 252)
    pico, max_caida = 0.0, 0.0
    for v in curva:
        pico = max(pico, v)
        max_caida = max(max_caida, (pico - v) / pico * 100)
    return Resultado(
        nombre=nombre,
        rentabilidad_pct=(final - 1) * 100,
        rentabilidad_anual_pct=(final ** (1 / anios) - 1) * 100 if final > 0 else -100.0,
        max_caida_pct=max_caida,
        operaciones=len(rend_ops),
        aciertos_pct=100 * sum(r > 0 for r in rend_ops) / len(rend_ops) if rend_ops else 0.0,
        tiempo_dentro_pct=100 * dias_dentro / max(len(curva), 1),
        curva=curva,
        rend_operaciones=rend_ops,
    )


def montecarlo(rend_operaciones: list[float], n: int = 2000, semilla: int = 1) -> tuple[float, float]:
    """Reordena las operaciones al azar: ¿cuánto podría haber caído con otra secuencia de suerte?

    Devuelve (caída máxima típica, caída máxima en el 5 % de peores casos).
    """
    if len(rend_operaciones) < 2:
        return 0.0, 0.0
    rnd = random.Random(semilla)
    caidas = []
    for _ in range(n):
        ops = rend_operaciones[:]
        rnd.shuffle(ops)
        valor, pico, peor = 1.0, 1.0, 0.0
        for r in ops:
            valor *= 1 + r / 100
            pico = max(pico, valor)
            peor = max(peor, (pico - valor) / pico * 100)
        caidas.append(peor)
    caidas.sort()
    return caidas[n // 2], caidas[int(n * 0.95)]


def descargar(simbolo: str, anios: int) -> list[Vela]:
    import yfinance as yf

    df = yf.Ticker(simbolo).history(period=f"{anios}y", interval="1d", auto_adjust=True)
    return [Vela(str(i.date()), r.Open, r.High, r.Low, r.Close, r.Volume) for i, r in df.iterrows()]


def informe(simbolo: str, velas: list[Vela], coste_pct: float) -> str:
    corte = int(len(velas) * 0.7)
    calentamiento = 200
    lineas = [
        f"\n{simbolo}: {velas[0].fecha} → {velas[-1].fecha} | coste por operación {coste_pct}%",
        f"Entrenamiento hasta {velas[corte].fecha}; prueba desde {velas[corte].fecha}\n",
        f"{'Estrategia':<20} {'Tramo':<14} {'Rent.%':>8} {'Anual%':>7} {'Caída%':>7} {'Ops':>5} {'Acierto%':>9} {'Dentro%':>8}",
    ]
    for nombre, fabrica in ESTRATEGIAS.items():
        tramos = [
            ("entrenamiento", velas[:corte], calentamiento),
            ("prueba", velas[corte - calentamiento:], calentamiento),
        ]
        for etiqueta, datos, cal in tramos:
            r = simular(datos, fabrica(), nombre, coste_pct, cal)
            lineas.append(f"{nombre:<20} {etiqueta:<14} {r.rentabilidad_pct:>8.1f} {r.rentabilidad_anual_pct:>7.1f} "
                          f"{r.max_caida_pct:>7.1f} {r.operaciones:>5} {r.aciertos_pct:>9.0f} {r.tiempo_dentro_pct:>8.0f}")
        completo = simular(velas, fabrica(), nombre, coste_pct, calentamiento)
        tipica, peor = montecarlo(completo.rend_operaciones)
        if completo.operaciones >= 2:
            lineas.append(f"{'':<20} montecarlo: caída típica {tipica:.1f}% | 5% peores casos {peor:.1f}%")
    lineas.append("\nCómo leerlo: una estrategia solo interesa si en el tramo de PRUEBA gana a comprar_y_mantener "
                  "o consigue algo parecido con bastante menos caída.")
    return "\n".join(lineas)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Prueba estrategias con datos históricos")
    ap.add_argument("simbolos", nargs="+")
    ap.add_argument("--anios", type=int, default=10)
    ap.add_argument("--coste", type=float, default=0.1, help="coste por compra o venta, en %%")
    args = ap.parse_args(argv)
    for s in args.simbolos:
        velas = descargar(s.upper(), args.anios)
        if len(velas) < 400:
            print(f"{s}: pocos datos ({len(velas)} días)")
            continue
        print(informe(s.upper(), velas, args.coste))


if __name__ == "__main__":
    main()
