"""Ciclo completo con broker y Claude falsos: comprueba que la IA no se salta los límites."""

from dataclasses import replace

import pytest

from agente import main as m
from agente.analista import Decision
from agente.diario import Diario
from tests.conftest import BrokerFalso

# SPY cae con fuerza al final (dispara el aviso "sobrevendido / movimiento fuerte"); QQQ plano
PRECIOS_CON_AVISO = {"SPY": [100.0] * 50 + [100 - 1.2 * i for i in range(1, 11)], "QQQ": [50.0] * 60}
PRECIOS_SIN_AVISO = {"SPY": [100.0 + (i % 2) * 0.1 for i in range(60)], "QQQ": [50.0] * 60}


class AnalistaFalso:
    llamadas = 0

    def __init__(self, decision):
        self.decision = decision
        self.gasto_usd = 0.05

    def decidir(self, *a):
        AnalistaFalso.llamadas += 1
        return self.decision


def decision(accion="comprar", importe=999.0, rent=5.0, confianza=7):
    return Decision(accion=accion, simbolo="SPY", importe=importe, argumentos_a_favor=["a"],
                    argumentos_en_contra=["b"], ventaja="v", riesgo_principal="r",
                    rentabilidad_esperada_pct=rent, horizonte_dias=20, confianza=confianza, razonamiento="x")


@pytest.fixture(autouse=True)
def reset():
    AnalistaFalso.llamadas = 0


def preparar(tmp_path, monkeypatch, dec, precios=None):
    import agente.analista

    monkeypatch.setattr(agente.analista, "Analista", lambda: AnalistaFalso(dec))
    precios = {k: list(v) for k, v in (precios or PRECIOS_CON_AVISO).items()}
    return BrokerFalso(str(tmp_path), precios), Diario(str(tmp_path))


def test_compra_recortada_a_50(cfg, tmp_path, monkeypatch):
    broker, diario = preparar(tmp_path, monkeypatch, decision(importe=999))
    m.ciclo(cfg, broker, diario)
    ops = diario.operaciones()
    assert len(ops) == 1 and float(ops[0]["importe"]) == 50
    assert broker.efectivo() == 150
    assert diario.gasto_ia_mes() == 0.05


def test_sin_avisos_no_llama_a_claude(cfg, tmp_path, monkeypatch):
    broker, diario = preparar(tmp_path, monkeypatch, decision(), PRECIOS_SIN_AVISO)
    m.ciclo(cfg, broker, diario)
    assert AnalistaFalso.llamadas == 0 and diario.gasto_ia_mes() == 0


def test_mantener_no_opera(cfg, tmp_path, monkeypatch):
    broker, diario = preparar(tmp_path, monkeypatch, decision(accion="mantener", importe=0))
    m.ciclo(cfg, broker, diario)
    assert AnalistaFalso.llamadas == 1 and diario.operaciones() == []


def test_poca_rentabilidad_esperada_no_compra(cfg, tmp_path, monkeypatch):
    broker, diario = preparar(tmp_path, monkeypatch, decision(rent=0.8))
    m.ciclo(cfg, broker, diario)
    assert diario.operaciones() == []


def test_poca_confianza_no_compra(cfg, tmp_path, monkeypatch):
    broker, diario = preparar(tmp_path, monkeypatch, decision(confianza=4))
    m.ciclo(cfg, broker, diario)
    assert diario.operaciones() == []


def test_tope_gasto_ia_no_llama(cfg, tmp_path, monkeypatch):
    broker, diario = preparar(tmp_path, monkeypatch, decision())
    diario.sumar_gasto_ia(cfg.max_gasto_ia_mes)
    m.ciclo(cfg, broker, diario)
    assert AnalistaFalso.llamadas == 0 and diario.operaciones() == []


def test_regla_dos_meses_bloquea_recompra(cfg, tmp_path, monkeypatch):
    broker, diario = preparar(tmp_path, monkeypatch, decision())
    diario.registrar_operacion("simulado", "vender", "SPY", 40, 90, "x", "stop", resultado=-10)
    m.ciclo(cfg, broker, diario)
    assert [o["accion"] for o in diario.operaciones()] == ["vender"]


def test_stop_loss_vende_sin_ia_y_anota_resultado(cfg, tmp_path, monkeypatch):
    broker, diario = preparar(tmp_path, monkeypatch, decision(accion="mantener", importe=0))
    broker.comprar("SPY", 50)
    broker.precios["SPY"] = broker.precios["SPY"][:-1] + [80.0]
    m.ciclo(cfg, broker, diario, usar_ia=False)
    assert broker.posiciones() == []
    op = diario.operaciones()[0]
    assert "stop-loss" in op["motivo"] and float(op["resultado"]) < 0


def test_sin_teclado_y_con_confirmacion_no_opera(cfg, tmp_path, monkeypatch):
    """En GitHub Actions no hay nadie para confirmar: la orden se propone pero no se ejecuta."""
    broker, diario = preparar(tmp_path, monkeypatch, decision(importe=30))
    m.ciclo(replace(cfg, confirmar_ordenes=True), broker, diario)
    assert diario.operaciones() == []
    assert broker.efectivo() == 200


def test_ciclo_completo_pide_stops_al_broker_y_vigilancia_no(cfg, tmp_path, monkeypatch):
    broker, diario = preparar(tmp_path, monkeypatch, decision(accion="mantener", importe=0))
    llamadas = []
    broker.proteger = lambda posiciones, pct: llamadas.append(pct) or []
    m.ciclo(cfg, broker, diario, usar_ia=False)
    assert llamadas == []
    m.ciclo(cfg, broker, diario)
    assert llamadas == [cfg.stop_loss_pct]


def test_nucleo_se_compra_y_no_tiene_stop(cfg, tmp_path, monkeypatch):
    cfg = replace(cfg, nucleo_simbolo="QQQ", nucleo_pct=0.6)
    broker, diario = preparar(tmp_path, monkeypatch, decision(accion="mantener", importe=0))
    m.ciclo(cfg, broker, diario)
    nucleo = [p for p in broker.posiciones() if p.simbolo == "QQQ"]
    assert nucleo and nucleo[0].valor == pytest.approx(120)
    # cae un 30 %: no se vende (el núcleo no tiene stop) y no cuenta en el límite semanal
    broker.precios["QQQ"] = broker.precios["QQQ"][:-1] + [35.0]
    m.ciclo(cfg, broker, diario, usar_ia=False)
    assert any(p.simbolo == "QQQ" for p in broker.posiciones())
    assert diario.operaciones_ultimos_dias(excluir_simbolo="QQQ") == 0
