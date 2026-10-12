import pytest

from agente import fiscal


def op(fecha, accion, simbolo, cantidad, precio):
    return {"fecha": fecha, "accion": accion, "simbolo": simbolo, "cantidad": str(cantidad),
            "importe": str(cantidad * precio), "precio": str(precio)}


def test_fifo():
    ops = [op("2026-01-05T22:00:00", "comprar", "SPY", 1, 100),
           op("2026-02-05T22:00:00", "comprar", "SPY", 1, 120),
           op("2026-03-05T22:00:00", "vender", "SPY", 1, 130)]
    inf = fiscal.calcular(ops, 2026)
    assert inf.ventas[0].resultado == pytest.approx(30)  # empareja con la compra a 100


def test_tipo_de_cambio_por_fecha():
    ops = [op("2026-01-05T22:00:00", "comprar", "SPY", 1, 110),
           op("2026-06-05T22:00:00", "vender", "SPY", 1, 110)]
    tipos = {1: 1.10, 6: 1.00}
    inf = fiscal.calcular(ops, 2026, lambda d: tipos[d.month])
    # mismo precio en dólares, pero el dólar se ha revalorizado: ganancia en euros
    assert inf.ventas[0].resultado == pytest.approx(10)


def test_regla_dos_meses():
    ops = [op("2026-01-05T22:00:00", "comprar", "SPY", 1, 100),
           op("2026-02-05T22:00:00", "vender", "SPY", 1, 90),
           op("2026-03-01T22:00:00", "comprar", "SPY", 1, 92)]
    inf = fiscal.calcular(ops, 2026)
    assert inf.ventas[0].diferida
    assert inf.perdidas_computables == 0 and inf.perdidas_diferidas == pytest.approx(-10)


def test_perdida_sin_recompra_se_compensa():
    ops = [op("2026-01-05T22:00:00", "comprar", "SPY", 1, 100),
           op("2026-02-05T22:00:00", "vender", "SPY", 1, 90),
           op("2026-01-10T22:00:00", "comprar", "QQQ", 1, 50),
           op("2026-05-10T22:00:00", "vender", "QQQ", 1, 70)]
    inf = fiscal.calcular(ops, 2026)
    assert inf.neto == pytest.approx(10)
    assert fiscal.impuesto_ahorro(inf.neto) == pytest.approx(1.9)


def test_tramos():
    assert fiscal.impuesto_ahorro(10_000) == pytest.approx(6_000 * 0.19 + 4_000 * 0.21)
    assert fiscal.impuesto_ahorro(-50) == 0
