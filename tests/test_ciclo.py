"""Ciclo completo con broker y Claude falsos: comprueba que la IA no se salta los límites."""

from agente import main as m
from agente.analista import Cribado, Decision
from agente.diario import Diario
from tests.conftest import BrokerFalso


class AnalistaFalso:
    def __init__(self, decision):
        self.decision = decision
        self.gasto_usd = 0.05

    def cribar(self, *a):
        return Cribado(valores=[], candidato="SPY", accion_candidata="comprar", motivo="prueba")

    def decidir(self, *a):
        return self.decision


def decision(accion="comprar", importe=999.0):
    return Decision(accion=accion, simbolo="SPY", importe=importe, argumentos_a_favor=["a"],
                    argumentos_en_contra=["b"], ventaja="v", riesgo_principal="r", confianza=7, razonamiento="x")


def preparar(tmp_path, monkeypatch, dec, precios=None):
    import agente.analista

    monkeypatch.setattr(agente.analista, "Analista", lambda: AnalistaFalso(dec))
    precios = precios or {"SPY": [100.0] * 60, "QQQ": [50.0] * 60}
    return BrokerFalso(str(tmp_path), precios), Diario(str(tmp_path))


def test_compra_recortada_a_50(cfg, tmp_path, monkeypatch):
    broker, diario = preparar(tmp_path, monkeypatch, decision(importe=999))
    m.ciclo(cfg, broker, diario)
    ops = diario.operaciones()
    assert len(ops) == 1 and float(ops[0]["importe"]) == 50
    assert broker.efectivo() == 150
    assert diario.gasto_ia_mes() == 0.05


def test_mantener_no_opera(cfg, tmp_path, monkeypatch):
    broker, diario = preparar(tmp_path, monkeypatch, decision(accion="mantener", importe=0))
    m.ciclo(cfg, broker, diario)
    assert diario.operaciones() == []


def test_tope_gasto_ia_no_llama(cfg, tmp_path, monkeypatch):
    broker, diario = preparar(tmp_path, monkeypatch, decision())
    diario.sumar_gasto_ia(cfg.max_gasto_ia_mes)
    m.ciclo(cfg, broker, diario)
    assert diario.operaciones() == []


def test_stop_loss_vende_sin_ia(cfg, tmp_path, monkeypatch):
    broker, diario = preparar(tmp_path, monkeypatch, decision(accion="mantener", importe=0))
    broker.comprar("SPY", 50)
    broker.precios["SPY"] = [100.0] * 59 + [80.0]
    m.ciclo(cfg, broker, diario, usar_ia=False)
    assert broker.posiciones() == []
    assert "stop-loss" in diario.operaciones()[0]["motivo"]


def test_sin_teclado_y_con_confirmacion_no_opera(cfg, tmp_path, monkeypatch):
    """En GitHub Actions no hay nadie para confirmar: la orden se propone pero no se ejecuta."""
    from dataclasses import replace

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
