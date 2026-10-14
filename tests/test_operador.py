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


def test_vende_la_mitad_al_objetivo_y_sigue_con_el_resto(entorno):
    cfg, broker, diario = entorno
    cfg = replace(cfg, parcial_pct=3)
    broker.velas_intradia["NVDA"] = ruptura()
    operador.operar(cfg, broker, diario)
    cantidad = broker.posiciones()[0].cantidad
    entrada = broker.precio("NVDA")
    broker.velas_intradia["NVDA"] = broker.velas_intradia["NVDA"] + velas([entrada * 1.04])
    operador.operar(cfg, broker, diario)
    assert broker.posiciones()[0].cantidad == pytest.approx(cantidad / 2)
    operador.operar(cfg, broker, diario)  # no vuelve a vender la mitad
    assert broker.posiciones()[0].cantidad == pytest.approx(cantidad / 2)


def test_cierra_todo_al_final_de_la_sesion(entorno, monkeypatch):
    cfg, broker, diario = entorno
    broker.velas_intradia["NVDA"] = ruptura()
    operador.operar(cfg, broker, diario)
    monkeypatch.setattr(operador, "_sesion_ahora", lambda: (387, 3))
    operador.operar(replace(cfg, cerrar_al_cierre=True), broker, diario)
    assert broker.posiciones() == []


def test_horario_y_filtro_de_mercado_bloquean_compras(entorno, monkeypatch):
    cfg, broker, diario = entorno
    broker.velas_intradia["NVDA"] = ruptura()
    monkeypatch.setattr(operador, "_sesion_ahora", lambda: (5, 385))  # 9:35
    operador.operar(replace(cfg, evitar_apertura_min=15), broker, diario)
    assert broker.posiciones() == []
    broker.velas_intradia["QQQ"] = velas(list(range(160, 100, -1)))  # mercado cayendo
    operador.operar(replace(cfg, filtro_mercado=True), broker, diario)
    assert broker.posiciones() == []


def test_stop_adaptado_guarda_su_distancia(entorno):
    cfg, broker, diario = entorno
    broker.velas_intradia["NVDA"] = ruptura()
    operador.operar(replace(cfg, stop_atr=4), broker, diario)
    assert 1 <= diario.estado["distancias"]["NVDA"] <= 6


def test_bucle_para_por_tiempo_con_el_mercado_abierto(entorno):
    cfg, broker, diario = entorno
    assert operador.bucle(cfg, lambda c: broker, diario, segundos=0, hasta_cierre=True, max_minutos=1e-9) is True
    broker.abierto = False
    assert operador.bucle(cfg, lambda c: broker, diario, segundos=0, hasta_cierre=True) is False
