"""Conexión con Alpaca (cuenta de práctica o real según ALPACA_PAPER).

Usa órdenes limitadas con cantidades fraccionarias: pones tú el precio máximo
de compra, así no pagas de más si el precio salta.
"""

import os
from datetime import datetime, timedelta, timezone

from agente.brokers.base import Broker, Posicion, Vela


class BrokerAlpaca(Broker):
    nombre = "alpaca"

    def __init__(self, paper: bool = True):
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.trading.client import TradingClient

        clave = os.environ.get("ALPACA_API_KEY")
        secreto = os.environ.get("ALPACA_SECRET_KEY")
        if not clave or not secreto:
            raise RuntimeError("Faltan ALPACA_API_KEY / ALPACA_SECRET_KEY en el archivo .env")
        self.paper = paper
        self.trading = TradingClient(clave, secreto, paper=paper)
        self.datos = StockHistoricalDataClient(clave, secreto)

    def efectivo(self) -> float:
        return float(self.trading.get_account().cash)

    def patrimonio(self) -> float:
        return float(self.trading.get_account().equity)

    def posiciones(self) -> list[Posicion]:
        return [
            Posicion(p.symbol, float(p.qty), float(p.avg_entry_price), float(p.current_price))
            for p in self.trading.get_all_positions()
        ]

    def historico(self, simbolo: str, dias: int = 60) -> list[Vela]:
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        inicio = datetime.now(timezone.utc) - timedelta(days=int(dias * 1.6) + 10)
        req = StockBarsRequest(symbol_or_symbols=simbolo, timeframe=TimeFrame.Day, start=inicio)
        barras = self.datos.get_stock_bars(req).data.get(simbolo, [])
        velas = [
            Vela(str(b.timestamp.date()), b.open, b.high, b.low, b.close, b.volume) for b in barras
        ]
        return velas[-dias:]

    def comprar(self, simbolo: str, importe: float, precio_limite: float | None = None) -> str:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest

        if precio_limite is None:
            orden = MarketOrderRequest(
                symbol=simbolo, notional=round(importe, 2), side=OrderSide.BUY, time_in_force=TimeInForce.DAY
            )
        else:
            orden = LimitOrderRequest(
                symbol=simbolo,
                qty=round(importe / precio_limite, 6),
                limit_price=round(precio_limite, 2),
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
            )
        return str(self.trading.submit_order(orden).id)

    def vender_todo(self, simbolo: str) -> str:
        return str(self.trading.close_position(simbolo).id)
