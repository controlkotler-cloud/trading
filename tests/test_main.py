from agente import main as programa
from agente import operador


def test_bucle_por_tiempo_deja_aviso_para_continuar(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MODO", "momentum")
    monkeypatch.setenv("BROKER", "simulado")
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.setattr(operador, "bucle", lambda *a, **k: True)
    programa.main(["--bucle", "--hasta-cierre", "--max-minutos", "1"])
    assert (tmp_path / "continuar").exists()
