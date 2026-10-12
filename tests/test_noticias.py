from datetime import datetime, timezone
from types import SimpleNamespace

from agente import noticias


def n(h, simbolos, titular):
    return SimpleNamespace(created_at=datetime(2026, 10, 12, h, tzinfo=timezone.utc), symbols=simbolos, headline=titular)


def test_agrupa_por_valor_mas_recientes_primero_y_limita():
    datos = [n(9, ["NVDA"], "viejo"), n(12, ["NVDA", "AMD"], "chips"), n(11, ["NVDA"], "medio"),
             n(10, ["NVDA"], "otro"), n(8, ["TSLA"], "fuera del universo")]
    r = noticias.agrupar(datos, ["NVDA", "AMD"], por_valor=3)
    assert [t.split("] ")[1] for t in r["NVDA"]] == ["chips", "medio", "otro"]
    assert r["AMD"] == ["[12/10 12:00] chips"]
    assert "TSLA" not in r


def test_sin_claves_devuelve_vacio(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    assert noticias.titulares(["NVDA"]) == {}
