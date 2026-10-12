import pytest

from agente.brokers.base import Vela
from agente.brokers.simulado import BrokerSimulado
from agente.config import Config


def velas_desde(cierres):
    return [Vela(f"d{i}", c, c * 1.01, c * 0.99, c, 1000) for i, c in enumerate(cierres)]


class BrokerFalso(BrokerSimulado):
    """Simulado con precios inventados (sin red)."""

    def __init__(self, carpeta, precios: dict[str, list[float]], **kw):
        super().__init__(carpeta, **kw)
        self.precios = precios
        self.velas_intradia: dict[str, list] = {}
        self.abierto = True

    def historico(self, simbolo, dias=60):
        return velas_desde(self.precios[simbolo])[-dias:]

    def intradia(self, simbolo, minutos=15, dias=5):
        return self.velas_intradia.get(simbolo, [])

    def mercado_abierto(self):
        return self.abierto


@pytest.fixture
def cfg(tmp_path):
    return Config(simbolos_permitidos=("SPY", "QQQ"), confirmar_ordenes=False, carpeta_datos=str(tmp_path))
