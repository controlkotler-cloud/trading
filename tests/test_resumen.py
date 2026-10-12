from dataclasses import replace
from types import SimpleNamespace

from agente import resumen
from agente.diario import Diario
from tests.conftest import BrokerFalso


def preparar(cfg, tmp_path):
    broker = BrokerFalso(str(tmp_path), {"SPY": [500.0] * 60, "NVDA": [100.0] * 60}, capital_inicial=2000)
    return replace(cfg, capital_simulado=2000), broker, Diario(str(tmp_path))


def test_diario_con_operaciones_y_comparacion(cfg, tmp_path):
    cfg, broker, diario = preparar(cfg, tmp_path)
    resumen._inicio(diario, broker)
    broker.comprar("NVDA", 600)
    diario.registrar_operacion("simulado", "comprar", "NVDA", 600, 100, "x", "rompe máximo")
    diario.guardar_maximo("NVDA", 110)
    broker.precios["NVDA"] = [100.0] * 59 + [110.0]
    broker.precios["SPY"] = [500.0] * 59 + [505.0]
    texto = resumen.diario_md(cfg, broker, diario)
    assert "Patrimonio: 2,060.00" in texto
    assert "+3.00%" in texto and "SPY: +1.00%" in texto
    assert "comprar **NVDA**" in texto and "stop 106.70" in texto


def test_semanal_sin_presupuesto_no_llama_a_claude(cfg, tmp_path):
    cfg, broker, diario = preparar(cfg, tmp_path)
    diario.sumar_gasto_ia(cfg.max_gasto_ia_mes)
    texto = resumen.semanal_md(cfg, broker, diario)
    assert "Revisión semanal" in texto and "tope de gasto" in texto


def test_semanal_con_claude(cfg, tmp_path, monkeypatch):
    cfg, broker, diario = preparar(cfg, tmp_path)
    import agente.analista as an

    class Falso:
        def __init__(self):
            self.cliente = SimpleNamespace(messages=SimpleNamespace(create=lambda **k: SimpleNamespace(
                content=[SimpleNamespace(type="text", text="Pocas operaciones: seguir igual.")],
                usage=SimpleNamespace(input_tokens=2000, output_tokens=500))))

    monkeypatch.setattr(an, "Analista", Falso)
    texto = resumen.semanal_md(cfg, broker, diario)
    assert "seguir igual" in texto and diario.gasto_ia_mes() > 0
