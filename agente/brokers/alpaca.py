"""Conexión con Alpaca (cuenta de práctica o real según ALPACA_PAPER).

Compra con órdenes limitadas y cantidades fraccionarias (pones tú el precio máximo,
así no pagas de más si el precio salta) y deja órdenes stop-loss puestas en Alpaca
para que venda durante la sesión aunque el agente no se esté ejecutando.
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

    def _cancelar_ordenes(self, simbolo: str) -> None:
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[simbolo])
        for orden in self.trading.get_orders(filter=req):
            self.trading.cancel_order_by_id(orden.id)

    def vender_todo(self, simbolo: str) -> str:
        self._cancelar_ordenes(simbolo)  # una orden stop pendiente bloquearía las acciones
        return str(self.trading.close_position(simbolo).id)

    def proteger(self, posiciones: list[Posicion], stop_pct: float) -> list[str]:
        """Pone (o renueva) una orden stop de venta por cada posición.

        Las fracciones de acción solo admiten órdenes válidas para el día (DAY), así que se
        renuevan en cada ejecución diaria; enviadas tras el cierre, valen para la sesión siguiente.
        """
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import StopOrderRequest

        mensajes = []
        for p in posiciones:
            stop = round(p.precio_medio * (1 - stop_pct / 100), 2)
            try:
                self._cancelar_ordenes(p.simbolo)
                self.trading.submit_order(StopOrderRequest(
                    symbol=p.simbolo, qty=p.cantidad, side=OrderSide.SELL,
                    stop_price=stop, time_in_force=TimeInForce.DAY,
                ))
                mensajes.append(f"Stop puesto en el broker: {p.simbolo} vende si baja de {stop}")
            except Exception as e:  # que un fallo aquí no pare el resto del ciclo
                mensajes.append(f"AVISO: no se pudo poner el stop de {p.simbolo}: {e}")
        return mensajes
