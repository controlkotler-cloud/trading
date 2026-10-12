import pytest

from agente.indicadores import resumir, rsi
from tests.conftest import velas_desde


def test_rsi_extremos():
    assert rsi([float(i) for i in range(1, 40)]) == 100
    assert rsi([float(i) for i in range(40, 1, -1)]) == pytest.approx(0)


def test_resumen_tendencia_alcista():
    r = resumir("SPY", velas_desde([100 + i for i in range(60)]))
    assert r.precio == 159
    assert r.cambio_20d_pct > 0
    assert r.media_20 > r.media_50


def test_resumen_pocos_datos():
    with pytest.raises(ValueError):
        resumir("SPY", velas_desde([100] * 10))


def test_ruptura_maximos_solo_el_primer_dia():
    base = [100.0] * 60
    assert resumir("SPY", velas_desde(base + [105])).ruptura_maximos
    assert not resumir("SPY", velas_desde(base + [105, 106])).ruptura_maximos
    assert not resumir("SPY", velas_desde(base + [99])).ruptura_maximos
