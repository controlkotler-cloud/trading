import math

import pytest

from agente import backtest as bt
from tests.conftest import velas_desde


def test_comprar_y_mantener_sin_costes_sigue_al_precio():
    velas = velas_desde([100 + i for i in range(300)])
    r = bt.simular(velas, bt.comprar_y_mantener, coste_pct=0)
    # entra en la apertura de la vela 1 (101) y termina en el cierre de la última (399)
    assert r.rentabilidad_pct == pytest.approx((399 / 101 - 1) * 100)
    assert r.operaciones == 1 and r.aciertos_pct == 100


def test_costes_reducen_rentabilidad():
    velas = velas_desde([100 + i for i in range(300)])
    assert bt.simular(velas, bt.comprar_y_mantener, coste_pct=0.5).rentabilidad_pct < \
        bt.simular(velas, bt.comprar_y_mantener, coste_pct=0).rentabilidad_pct


def test_sin_mirar_al_futuro():
    """La estrategia solo ve cierres anteriores al día en que opera."""
    vistos = []

    def espia(cierres):
        vistos.append(len(cierres))
        return False

    bt.simular(velas_desde([100.0] * 50), espia)
    assert vistos == list(range(1, 50))


def test_tendencia_200_sale_en_caida():
    precios = [100 + i for i in range(300)] + [400 - 3 * i for i in range(100)]
    r = bt.simular(velas_desde(precios), bt.tendencia_200, coste_pct=0, calentamiento=200)
    assert r.max_caida_pct < bt.simular(velas_desde(precios), bt.comprar_y_mantener, coste_pct=0,
                                        calentamiento=200).max_caida_pct


def test_rebote_rsi_opera_en_serie_oscilante():
    precios = [100 + 15 * math.sin(i / 6) for i in range(400)]
    r = bt.simular(velas_desde(precios), bt.ESTRATEGIAS["rebote_rsi"](), coste_pct=0, calentamiento=60)
    assert r.operaciones > 0


def test_montecarlo():
    tipica, peor = bt.montecarlo([5, -3, 4, -6, 2, -1, 3] * 5)
    assert 0 < tipica <= peor


def test_informe_completo():
    precios = [100 + 10 * math.sin(i / 20) + i * 0.05 for i in range(800)]
    texto = bt.informe("TEST", velas_desde(precios), 0.1)
    for nombre in bt.ESTRATEGIAS:
        assert nombre in texto
