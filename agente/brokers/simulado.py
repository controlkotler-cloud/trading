"""Broker simulado: precios reales (Yahoo Finance), dinero ficticio.

Sirve para probar el agente completo sin cuenta en ningún broker.
El estado (efectivo y posiciones) se guarda en datos/simulado.json.
"""

import json
import uuid
from pathlib import Path

from agente.brokers.base import Broker, Posicion, Vela


class BrokerSimulado(Broker):
    nombre = "simulado"

    def __init__(self, carpeta: str, capital_inicial: float = 200.0, comision: float = 0.0):
        self.ruta = Path(carpeta) / "simulado.json"
        self.comision = comision
        self._cache_velas: dict[str, list[Vela]] = {}
        if self.ruta.exists():
            self.estado = json.loads(self.ruta.read_text())
        else:
            self.estado = {"efectivo": capital_inicial, "posiciones": {}}
            self._guardar()

    def _guardar(self) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.ruta.write_text(json.dumps(self.estado, indent=2))

    def historico(self, simbolo: str, dias: int = 60) -> list[Vela]:
        if simbolo not in self._cache_velas:
            import yfinance as yf

            df = yf.Ticker(simbolo).history(period="6mo", interval="1d", auto_adjust=True)
            self._cache_velas[simbolo] = [
                Vela(str(idx.date()), r.Open, r.High, r.Low, r.Close, r.Volume)
                for idx, r in df.iterrows()
            ]
        return self._cache_velas[simbolo][-dias:]

    def precio(self, simbolo: str) -> float:
        return self.historico(simbolo, 1)[-1].cierre

    def efectivo(self) -> float:
        return self.estado["efectivo"]

    def posiciones(self) -> list[Posicion]:
        return [
            Posicion(s, p["cantidad"], p["precio_medio"], self.precio(s))
            for s, p in self.estado["posiciones"].items()
        ]

    def comprar(self, simbolo: str, importe: float, precio_limite: float | None = None) -> str:
        precio = self.precio(simbolo)
        if precio_limite is not None and precio > precio_limite:
            raise RuntimeError(f"{simbolo}: precio {precio:.2f} por encima del límite {precio_limite:.2f}")
        coste = importe + self.comision
        if coste > self.efectivo():
            raise RuntimeError(f"Efectivo insuficiente: {self.efectivo():.2f} < {coste:.2f}")
        cantidad = importe / precio
        pos = self.estado["posiciones"].get(simbolo, {"cantidad": 0.0, "precio_medio": 0.0})
        total = pos["cantidad"] + cantidad
        pos["precio_medio"] = (pos["cantidad"] * pos["precio_medio"] + cantidad * precio) / total
        pos["cantidad"] = total
        self.estado["posiciones"][simbolo] = pos
        self.estado["efectivo"] -= coste
        self._guardar()
        return f"sim-{uuid.uuid4().hex[:8]}"

    def vender_todo(self, simbolo: str) -> str:
        pos = self.estado["posiciones"].pop(simbolo, None)
        if pos is None:
            raise RuntimeError(f"No hay posición en {simbolo}")
        self.estado["efectivo"] += pos["cantidad"] * self.precio(simbolo) - self.comision
        self._guardar()
        return f"sim-{uuid.uuid4().hex[:8]}"
