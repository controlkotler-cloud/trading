from datetime import datetime, timedelta, timezone

from agente import auditoria
from agente.backtest_momentum import Parametros
from agente.brokers.base import Vela


def velas_5m(n=200, inicio=datetime(2026, 10, 14, 13, 30, tzinfo=timezone.utc)):
    out, precio = [], 100.0
    for i in range(n):
        precio *= 1.001 if i % 5 else 0.998
        out.append(Vela((inicio + timedelta(minutes=5 * i)).isoformat(), precio, precio * 1.002,
                        precio * 0.998, precio, 1000))
    return out


def test_empareja_y_analiza():
    ops = [
        {"fecha": "2026-10-14T14:01:10", "accion": "comprar", "simbolo": "A", "precio": "103"},
        {"fecha": "2026-10-15T13:31:00", "accion": "vender", "simbolo": "A", "precio": "101"},
        {"fecha": "2026-10-15T14:00:00", "accion": "comprar", "simbolo": "A", "precio": "105"},
    ]
    pares = auditoria.emparejar(ops)
    assert len(pares) == 2 and pares[0]["salida"] == 101 and pares[1]["salida"] is None
    f = auditoria.analizar(pares[0], velas_5m(), 5, 2, 12, 1.2)
    assert f["noche"] and f["resultado_pct"] < 0 and f["habia_vela_en_curso"]
    assert f["deslizamiento_pct"] is not None


def test_informe_completo():
    ops = auditoria.emparejar([
        {"fecha": "2026-10-14T14:01:10", "accion": "comprar", "simbolo": "A", "precio": "103"},
        {"fecha": "2026-10-14T15:00:00", "accion": "vender", "simbolo": "A", "precio": "101"},
    ])
    texto = auditoria.informe(ops, {"A": velas_5m()}, Parametros(), 5, ["A"], None)
    assert "AUDITORÍA" in texto and "Backtest mismos días" in texto and "Real: 1" in texto
