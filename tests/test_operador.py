from dataclasses import replace

import pytest

from agente import operador
from agente.diario import Diario
from tests.conftest import BrokerFalso
from tests.test_momentum import velas


@pytest.fixture
def entorno(cfg, tmp_path):
    cfg = replace(cfg, universo=("NVDA", "AMD"), max_posiciones=2, pct_por_posicion=0.5, trailing_pct=3)
    broker = BrokerFalso(str(tmp_path), {"NVDA": [100.0] * 70, "AMD": [50.0] * 70})
    diario = Diario(str(tmp_path))
    diario.guardar_vigilancia(["NVDA", "AMD"], "prueba")
    return cfg, broker, diario


def ruptura(precio=100.0):
    return velas([precio + (i % 3) * 0.1 for i in range(40)] + [precio * 1.015], [1000] * 40 + [3000])


def test_compra_en_ruptura_con_la_mitad_del_patrimonio(entorno):
    cfg, broker, diario = entorno
    broker.velas_intradia["NVDA"] = ruptura()
    operador.operar(cfg, broker, diario)
    assert [p.simbolo for p in broker.posiciones()] == ["NVDA"]
    assert float(diario.operaciones()[0]["importe"]) == 100  # 50 % de 200


def test_stop_dinamico_sube_y_vende(entorno):
    cfg, broker, diario = entorno
    broker.velas_intradia["NVDA"] = ruptura()
    operador.operar(cfg, broker, diario)
    entrada = broker.precio("NVDA")
    # sube un 10 %: el stop sube con él
    broker.velas_intradia["NVDA"] = broker.velas_intradia["NVDA"] + velas([entrada * 1.10])
    operador.operar(cfg, broker, diario)
    assert broker.posiciones() and diario.estado["maximos"]["NVDA"] == pytest.approx(entrada * 1.10)
    # se gira un 4 % desde el máximo: vende con ganancia
    broker.velas_intradia["NVDA"] = broker.velas_intradia["NVDA"] + velas([entrada * 1.10 * 0.96])
    broker.abierto = False  # que no vuelva a entrar en la misma pasada
    operador.operar(cfg, broker, diario)
    assert broker.posiciones() == []
    venta = diario.operaciones()[-1]
    assert venta["accion"] == "vender" and float(venta["resultado"]) > 0


def test_no_reentra_justo_despues_de_salir(entorno):
    cfg, broker, diario = entorno
    diario.registrar_salida("NVDA")
    broker.velas_intradia["NVDA"] = ruptura()
    operador.operar(cfg, broker, diario)
    assert broker.posiciones() == []


def test_mercado_cerrado_no_compra(entorno):
    cfg, broker, diario = entorno
    broker.abierto = False
    broker.velas_intradia["NVDA"] = ruptura()
    operador.operar(cfg, broker, diario)
    assert broker.posiciones() == []


def test_parada_total_por_caida_desde_maximo(entorno):
    cfg, broker, diario = entorno
    broker.velas_intradia["NVDA"] = ruptura()
    operador.operar(cfg, broker, diario)
    diario.estado["pico_patrimonio"] = 400  # simula que llegó a 400 y ahora vale ~200 (-50 %)
    operador.operar(cfg, broker, diario)
    assert broker.posiciones() == [] and diario.parada_total()
    broker.velas_intradia["AMD"] = ruptura(50)
    operador.operar(cfg, broker, diario)  # con la parada activa no hace nada
    assert broker.posiciones() == []


def test_perdida_diaria_bloquea_entradas(entorno):
    cfg, broker, diario = entorno
    diario.patrimonio_inicio_dia(250)  # empezó el día con 250, ahora 200: -20 %
    broker.velas_intradia["NVDA"] = ruptura()
    operador.operar(cfg, broker, diario)
    assert broker.posiciones() == []
