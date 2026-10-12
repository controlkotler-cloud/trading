"""Interfaz común: cualquier broker (simulado, Alpaca, Kraken, IBKR...) implementa esto."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Posicion:
    simbolo: str
    cantidad: float
    precio_medio: float
    precio_actual: float

    @property
    def valor(self) -> float:
        return self.cantidad * self.precio_actual

    @property
    def pnl_pct(self) -> float:
        return (self.precio_actual / self.precio_medio - 1) * 100


@dataclass
class Vela:
    fecha: str
    apertura: float
    maximo: float
    minimo: float
    cierre: float
    volumen: float


class Broker(ABC):
    nombre: str = "base"

    @abstractmethod
    def efectivo(self) -> float: ...

    @abstractmethod
    def posiciones(self) -> list[Posicion]: ...

    @abstractmethod
    def historico(self, simbolo: str, dias: int = 60) -> list[Vela]:
        """Velas diarias, de la más antigua a la más reciente."""

    @abstractmethod
    def comprar(self, simbolo: str, importe: float, precio_limite: float | None = None) -> str:
        """Compra por importe (permite fracciones), sin pagar más de precio_limite.

        Devuelve el id de la orden."""

    @abstractmethod
    def vender_todo(self, simbolo: str) -> str:
        """Cierra la posición entera. Devuelve el id de la orden."""

    def intradia(self, simbolo: str, minutos: int = 15, dias: int = 5) -> list[Vela]:
        """Velas intradía (por defecto de 15 minutos) de los últimos `dias`."""
        raise NotImplementedError

    def mercado_abierto(self) -> bool:
        """Horario regular de la bolsa de EE. UU. (9:30-16:00 Nueva York, lunes a viernes).

        No tiene en cuenta festivos; los brokers reales lo sobrescriben con su reloj oficial.
        """
        from datetime import datetime, time
        from zoneinfo import ZoneInfo

        ahora = datetime.now(ZoneInfo("America/New_York"))
        return ahora.weekday() < 5 and time(9, 30) <= ahora.time() < time(16, 0)

    def poner_stop(self, simbolo: str, cantidad: float, precio_stop: float) -> str:
        """Deja (o mueve) una orden stop de venta en el broker. Por defecto no hace nada."""
        return ""

    def proteger(self, posiciones: list[Posicion], stop_pct: float) -> list[str]:
        """Deja órdenes stop-loss puestas en el propio broker para la próxima sesión.

        Así, si el precio cae durante el día, el broker vende aunque nuestro programa no esté
        ejecutándose. Por defecto no hace nada (el broker simulado no tiene órdenes pendientes).
        Devuelve mensajes para el registro.
        """
        return []

    def patrimonio(self) -> float:
        return self.efectivo() + sum(p.valor for p in self.posiciones())
