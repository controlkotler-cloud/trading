"""Laboratorio: estrategias de varios días o semanas, probadas con años de datos diarios.

    python -m agente.laboratorio                  # ~8 años, universo amplio, todas las estrategias
    python -m agente.laboratorio --anios 5 --coste 0.15

Reglas para no engañarse (las mismas que en los otros backtests):
- La decisión se toma con el cierre del día y se ejecuta en la APERTURA del día siguiente.
- Cada compra y cada venta paga un coste (diferencia de precio + deslizamiento), 0,1 % por defecto.
- Se mira cada estrategia en dos mitades del periodo: si solo funciona en una, es casualidad.
- Se compara con comprar el S&P 500 (SPY) y no tocarlo, y con comprar todo el universo a partes iguales.
- Solo se compran ACCIONES: en la UE no se pueden comprar ETF de EE. UU. (PRIIPs). SPY solo se usa
  como termómetro del mercado y como referencia.

Aviso importante: el universo son empresas grandes de HOY. Las que quebraron o se hundieron desde 2017
no están, y eso infla algo los resultados de todas las estrategias (sesgo de supervivencia).
Por eso se incluyen también valores que lo han hecho mal (INTC, BA, PFE, DIS, NKE...).
"""

import argparse
import math
from dataclasses import dataclass, field

from agente.brokers.base import Vela
from agente.indicadores import rsi

UNIVERSO = ("AAPL MSFT AMZN GOOGL META NVDA TSLA AVGO NFLX AMD ADBE CRM ORCL INTC CSCO QCOM TXN IBM "
            "JPM BAC WFC GS V MA JNJ UNH PFE MRK ABBV LLY PG KO PEP WMT COST HD MCD NKE DIS XOM CVX "
            "CAT BA GE T VZ").split()
MERCADO = "SPY"


# ---------------- estrategias ----------------
# Cada estrategia recibe el índice del día (con datos hasta el CIERRE de ese día) y devuelve los pesos
# objetivo de la cartera ({simbolo: peso}, suman <= 1; el resto queda en efectivo), o None si no cambia nada.

@dataclass
class Contexto:
    cierres: dict[str, list[float]]   # cierres alineados por fecha (None si el valor aún no cotizaba)
    fechas: list[str]
    pesos: dict[str, float] = field(default_factory=dict)  # pesos actuales (después de moverse el precio)
    entradas: dict[str, int] = field(default_factory=dict)  # día en que se compró cada valor

    def serie(self, s: str, i: int, n: int) -> list[float] | None:
        v = self.cierres[s][max(0, i - n + 1):i + 1]
        return None if len(v) < n or any(x is None for x in v) else v


def _media(v: list[float]) -> float:
    return sum(v) / len(v)


def mercado_alcista(ctx: Contexto, i: int) -> bool:
    v = ctx.serie(MERCADO, i, 200)
    return v is not None and v[-1] > _media(v)


def rotacion_impulso(top: int = 5, meses: int = 6, filtro: bool = True):
    """Cada mes, compra los `top` valores que más han subido en los últimos `meses` (sin el último mes,
    que suele girarse). Si el mercado está bajo su media de 200 días, todo a efectivo."""
    dias = 21 * meses

    primera = [True]

    def estrategia(ctx: Contexto, i: int):
        fin_de_mes = i + 1 >= len(ctx.fechas) or ctx.fechas[i + 1][:7] != ctx.fechas[i][:7]
        if not (fin_de_mes or primera[0]):
            return None  # solo se decide el último día de cada mes
        primera[0] = False
        if filtro and not mercado_alcista(ctx, i):
            return {}
        puntos = []
        for s in ctx.cierres:
            if s == MERCADO:
                continue
            v = ctx.serie(s, i, dias + 1)
            if v is not None:
                puntos.append((v[-22] / v[0] - 1, s))
        elegidos = [s for r, s in sorted(puntos, reverse=True)[:top] if r > 0]
        return {s: 1 / top for s in elegidos}

    return estrategia


def tendencia(maximo: int = 10):
    """Cada semana: dentro de los valores con precio > media de 200 y media de 50 > media de 200
    (tendencia sana), hasta `maximo` a partes iguales, los de más impulso de 3 meses primero."""

    def estrategia(ctx: Contexto, i: int):
        if i % 5:
            return None
        candidatos = []
        for s in ctx.cierres:
            if s == MERCADO:
                continue
            v = ctx.serie(s, i, 200)
            if v is not None and v[-1] > _media(v) and _media(v[-50:]) > _media(v):
                candidatos.append((v[-1] / v[-63] - 1, s))
        elegidos = [s for _, s in sorted(candidatos, reverse=True)[:maximo]]
        return {s: 1 / maximo for s in elegidos}

    return estrategia


def rebote_rsi2(huecos: int = 5, umbral: float = 10, max_dias: int = 10):
    """Reversión a la media de corto plazo (Connors): compra un valor en tendencia alcista
    (sobre su media de 200) que ha caído con fuerza 1-3 días (RSI de 2 días < umbral). Vende cuando
    cierra sobre su media de 5 días o tras `max_dias`."""

    def estrategia(ctx: Contexto, i: int):
        nuevos = dict(ctx.pesos)
        cambio = False
        for s in list(nuevos):
            v = ctx.serie(s, i, 5)
            if v is None or v[-1] > _media(v) or i - ctx.entradas.get(s, i) >= max_dias:
                del nuevos[s]
                cambio = True
        libres = huecos - len(nuevos)
        if libres > 0 and mercado_alcista(ctx, i):
            candidatos = []
            for s in ctx.cierres:
                if s == MERCADO or s in nuevos:
                    continue
                v = ctx.serie(s, i, 200)
                if v is not None and v[-1] > _media(v):
                    r = rsi(v[-30:], 2)
                    if r < umbral:
                        candidatos.append((r, s))
            for _, s in sorted(candidatos)[:libres]:
                nuevos[s] = 1 / huecos
                cambio = True
        return nuevos if cambio else None

    return estrategia


def comprar_y_mantener(simbolos: list[str] | None = None):
    def estrategia(ctx: Contexto, i: int):
        if ctx.pesos:
            return None
        lista = simbolos or [s for s in ctx.cierres if s != MERCADO]
        vivos = [s for s in lista if ctx.cierres[s][i] is not None]
        return {s: 1 / len(vivos) for s in vivos} if vivos else None

    return estrategia


# ---------------- motor ----------------

@dataclass
class Resultado:
    nombre: str
    curva: list[float]
    fechas: list[str]
    operaciones: int
    exposicion: float  # % de días con dinero invertido

    def _rango(self, a: int, b: int) -> tuple[float, float]:
        c = self.curva[a:b]
        anios = max((b - a) / 252, 1e-9)
        cagr = (c[-1] / c[0]) ** (1 / anios) - 1
        pico, caida = c[0], 0.0
        for x in c:
            pico = max(pico, x)
            caida = max(caida, 1 - x / pico)
        return cagr * 100, caida * 100

    @property
    def cagr(self) -> float:
        return self._rango(0, len(self.curva))[0]

    @property
    def max_caida(self) -> float:
        return self._rango(0, len(self.curva))[1]

    @property
    def sharpe(self) -> float:
        r = [self.curva[k] / self.curva[k - 1] - 1 for k in range(1, len(self.curva))]
        media = _media(r)
        desv = math.sqrt(sum((x - media) ** 2 for x in r) / len(r)) or 1e-9
        return media / desv * math.sqrt(252)

    def mitades(self) -> tuple[float, float]:
        m = len(self.curva) // 2
        return self._rango(0, m + 1)[0], self._rango(m, len(self.curva))[0]

    def por_anio(self) -> dict[str, float]:
        out, inicio = {}, 0
        for k in range(1, len(self.fechas) + 1):
            if k == len(self.fechas) or self.fechas[k][:4] != self.fechas[k - 1][:4]:
                out[self.fechas[k - 1][:4]] = (self.curva[k - 1] / self.curva[max(inicio - 1, 0)] - 1) * 100
                inicio = k
        return out


def alinear(datos: dict[str, list[Vela]]) -> tuple[list[str], dict[str, list], dict[str, list]]:
    fechas = sorted({v.fecha for velas in datos.values() for v in velas})
    pos = {f: k for k, f in enumerate(fechas)}
    cierres = {s: [None] * len(fechas) for s in datos}
    aperturas = {s: [None] * len(fechas) for s in datos}
    for s, velas in datos.items():
        for v in velas:
            cierres[s][pos[v.fecha]] = v.cierre
            aperturas[s][pos[v.fecha]] = v.apertura
    return fechas, cierres, aperturas


def simular(datos: dict[str, list[Vela]], estrategia, nombre: str, coste_pct: float = 0.1,
            calentamiento: int = 260) -> Resultado:
    fechas, cierres, aperturas = alinear(datos)
    coste = coste_pct / 100
    ctx = Contexto(cierres, fechas)
    efectivo, acciones = 1.0, {}  # empieza con 1 (curva en "veces el capital inicial")
    curva, fechas_curva, ops, invertido = [], [], 0, 0
    pendiente = None
    ultimo: dict[str, float] = {}

    def precio_de(s: str, i: int) -> float:
        return aperturas[s][i] or ultimo.get(s) or cierres[s][i - 1]

    for i in range(calentamiento, len(fechas)):
        # 1. ejecutar en la apertura lo decidido ayer
        if pendiente is not None:
            valor = efectivo + sum(n * precio_de(s, i) for s, n in acciones.items())
            for s in list(acciones):
                if s not in pendiente:
                    efectivo += acciones.pop(s) * precio_de(s, i) * (1 - coste)
                    ctx.entradas.pop(s, None)
            # primero reducir (libera efectivo), luego aumentar
            for s, peso in sorted(pendiente.items(), key=lambda x: x[1] * valor - acciones.get(x[0], 0) * precio_de(x[0], i)):
                precio = aperturas[s][i]
                if precio is None:
                    continue
                diferencia = peso * valor - acciones.get(s, 0) * precio
                if s in acciones and abs(diferencia) < 0.02 * valor:
                    continue  # no mover pesos por diferencias pequeñas (ahorra costes)
                if s not in acciones:
                    ops += 1
                    ctx.entradas[s] = i
                if diferencia > 0:
                    diferencia = min(diferencia, efectivo / (1 + coste))
                    acciones[s] = acciones.get(s, 0) + diferencia / precio
                    efectivo -= diferencia * (1 + coste)
                else:
                    acciones[s] = acciones.get(s, 0) + diferencia / precio
                    efectivo += -diferencia * (1 - coste)
            pendiente = None
        # 2. valorar al cierre
        for s in acciones:
            if cierres[s][i] is not None:
                ultimo[s] = cierres[s][i]
        valores = {s: n * ultimo[s] for s, n in acciones.items()}
        total = efectivo + sum(valores.values())
        curva.append(total)
        fechas_curva.append(fechas[i])
        invertido += bool(acciones)
        ctx.pesos = {s: v / total for s, v in valores.items()} if total else {}
        # 3. decidir con el cierre de hoy
        pendiente = estrategia(ctx, i)
    return Resultado(nombre, curva, fechas_curva, ops, 100 * invertido / max(len(curva), 1))


# ---------------- datos e informe ----------------

def descargar(simbolos: list[str], anios: int) -> dict[str, list[Vela]]:
    """Velas diarias AJUSTADAS por splits y dividendos (Alpaca si hay claves, si no Yahoo)."""
    import os
    from datetime import datetime, timedelta, timezone

    datos = {}
    if os.environ.get("ALPACA_API_KEY"):
        from alpaca.data.enums import Adjustment
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        cliente = StockHistoricalDataClient(os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"])
        inicio = datetime.now(timezone.utc) - timedelta(days=365 * anios + 400)
        req = StockBarsRequest(symbol_or_symbols=simbolos, timeframe=TimeFrame.Day, start=inicio,
                               adjustment=Adjustment.ALL)
        for s, barras in cliente.get_stock_bars(req).data.items():
            datos[s] = [Vela(str(b.timestamp.date()), b.open, b.high, b.low, b.close, b.volume) for b in barras]
    else:
        import yfinance as yf

        for s in simbolos:
            df = yf.Ticker(s).history(period=f"{anios + 2}y", interval="1d", auto_adjust=True)
            datos[s] = [Vela(str(i.date()), r.Open, r.High, r.Low, r.Close, r.Volume) for i, r in df.iterrows()]
    return {s: v for s, v in datos.items() if len(v) > 300}


ESTRATEGIAS = {
    "SPY comprar y mantener (referencia)": lambda: comprar_y_mantener([MERCADO]),
    "Universo a partes iguales (referencia)": lambda: comprar_y_mantener(),
    "Rotación impulso 6m, top 5, filtro": lambda: rotacion_impulso(5, 6, True),
    "Rotación impulso 12m, top 5, filtro": lambda: rotacion_impulso(5, 12, True),
    "Rotación impulso 6m, top 5, sin filtro": lambda: rotacion_impulso(5, 6, False),
    "Rotación impulso 6m, top 3, filtro": lambda: rotacion_impulso(3, 6, True),
    "Rotación impulso 6m, top 10, filtro": lambda: rotacion_impulso(10, 6, True),
    "Tendencia semanal, 10 valores": lambda: tendencia(10),
    "Rebote RSI2, 5 huecos": lambda: rebote_rsi2(5),
}


def informe(datos: dict[str, list[Vela]], coste_pct: float) -> str:
    resultados = [simular(datos, crear(), nombre, coste_pct) for nombre, crear in ESTRATEGIAS.items()]
    r0 = resultados[0]
    lineas = [
        f"\nLaboratorio de estrategias | {len(datos) - 1} acciones + SPY | {r0.fechas[0]} -> {r0.fechas[-1]} "
        f"| coste {coste_pct}% por operación\n",
        f"{'Estrategia':<42}{'Anual':>8}{'1ª mitad':>10}{'2ª mitad':>10}{'Caída máx':>11}{'Sharpe':>8}"
        f"{'Compras/año':>12}{'Invertido':>11}",
    ]
    anios = len(r0.curva) / 252
    for r in resultados:
        m1, m2 = r.mitades()
        lineas.append(f"{r.nombre:<42}{r.cagr:>+7.1f}%{m1:>+9.1f}%{m2:>+9.1f}%{r.max_caida:>10.1f}%"
                      f"{r.sharpe:>8.2f}{r.operaciones / anios:>12.0f}{r.exposicion:>10.0f}%")
    lineas += ["", "Rentabilidad por año:"]
    anios_lista = list(r0.por_anio())
    lineas.append(f"{'':<42}" + "".join(f"{a:>8}" for a in anios_lista))
    for r in resultados:
        pa = r.por_anio()
        lineas.append(f"{r.nombre:<42}" + "".join(f"{pa.get(a, 0):>+7.1f}%" for a in anios_lista))
    lineas += [
        "",
        "Cómo leerlo: 'Anual' es la rentabilidad compuesta por año. Una estrategia interesa si gana a SPY en",
        "LAS DOS mitades, o gana parecido con bastante menos caída. Ojo: el universo son empresas grandes de hoy",
        "(sesgo de supervivencia), así que todas las cifras están algo infladas; lo que importa es la comparación.",
    ]
    return "\n".join(lineas)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Laboratorio de estrategias de varios días")
    ap.add_argument("--anios", type=int, default=8)
    ap.add_argument("--coste", type=float, default=0.1)
    args = ap.parse_args(argv)
    datos = descargar(UNIVERSO + [MERCADO], args.anios)
    if MERCADO not in datos:
        raise SystemExit("Sin datos del mercado (SPY).")
    print(informe(datos, args.coste))


if __name__ == "__main__":
    main()
