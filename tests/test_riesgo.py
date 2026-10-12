from agente import riesgo
from agente.brokers.base import Posicion


def test_parada_total_bajo_capital_minimo(cfg):
    assert not riesgo.parada_general(149, 160, cfg).permitido


def test_parada_por_perdida_diaria(cfg):
    v = riesgo.parada_general(190, 200, cfg)
    assert not v.permitido and "hoy" in v.motivo


def test_sin_parada(cfg):
    assert riesgo.parada_general(195, 200, cfg).permitido


def test_compra_recortada_al_maximo(cfg):
    v = riesgo.validar_compra("spy", 500, 200, 0, [], cfg)
    assert v.permitido and v.importe == 50


def test_compra_recortada_por_lo_ya_invertido(cfg):
    pos = [Posicion("SPY", 1, 30, 30)]
    assert riesgo.validar_compra("SPY", 50, 200, 0, pos, cfg).importe == 20


def test_compra_bloqueada_si_ya_esta_al_maximo(cfg):
    pos = [Posicion("SPY", 1, 50, 50)]
    assert not riesgo.validar_compra("SPY", 50, 200, 0, pos, cfg).permitido


def test_compra_de_valor_no_permitido(cfg):
    assert not riesgo.validar_compra("GME", 10, 200, 0, [], cfg).permitido


def test_limite_semanal(cfg):
    assert not riesgo.validar_compra("SPY", 10, 200, 5, [], cfg).permitido
    assert not riesgo.validar_venta("SPY", [Posicion("SPY", 1, 10, 10)], 5, cfg).permitido


def test_compra_limitada_por_efectivo(cfg):
    assert riesgo.validar_compra("SPY", 50, 20, 0, [], cfg).importe == 20


def test_stop_loss(cfg):
    pos = [Posicion("SPY", 1, 100, 91), Posicion("QQQ", 1, 100, 93)]
    assert [p.simbolo for p in riesgo.posiciones_a_cerrar_por_stop(pos, cfg)] == ["SPY"]
