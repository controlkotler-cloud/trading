import random

from agente import backtest_momentum as bm
from agente.brokers.base import Vela


def serie(tendencia, n=600, semilla=1):
    rnd = random.Random(semilla)
    precio, velas = 100.0, []
    for i in range(n):
        cambio = rnd.gauss(tendencia, 0.004)
        apertura, cierre = precio, precio * (1 + cambio)
        vol = 3000 if cambio > 0.006 else 1000
        velas.append(Vela(f"2026-01-01T{i:05d}", apertura, max(apertura, cierre) * 1.001,
                          min(apertura, cierre) * 0.999, cierre, vol))
        precio = cierre
    return velas


def test_gana_en_tendencia_alcista_y_respeta_capital():
    r = bm.simular({"A": serie(0.0015), "B": serie(0.0015, semilla=2)}, bm.Parametros(coste_pct=0))
    assert r.operaciones and r.rentabilidad_pct > 0
    assert min(r.curva) > 0


def test_stop_limita_perdidas_en_caida():
    r = bm.simular({"A": serie(-0.002)}, bm.Parametros(trailing_pct=3))
    assert r.max_caida_pct < abs(r.referencia_pct)


def test_costes_restan():
    datos = {"A": serie(0.0005, semilla=5)}
    sin = bm.simular(datos, bm.Parametros(coste_pct=0))
    con = bm.simular(datos, bm.Parametros(coste_pct=0.2))
    assert con.rentabilidad_pct < sin.rentabilidad_pct


def test_informe():
    texto = bm.informe({"A": serie(0.001)}, bm.Parametros())
    assert "Rentabilidad de la estrategia" in texto


def test_comparar_y_mejoras_no_rompen():
    datos = {"A": serie(0.001), "B": serie(0.001, semilla=3)}
    texto = bm.comparar(datos, bm.Parametros(), None)
    assert "Actual (sin mejoras)" in texto and "RESULTADO_JSON" in texto
    r = bm.simular(datos, bm.Parametros(parcial_pct=1, stop_atr=4))
    assert min(r.curva) > 0
