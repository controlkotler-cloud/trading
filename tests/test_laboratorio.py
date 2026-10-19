import random
from datetime import date, timedelta

import pytest

from agente import laboratorio as lab
from agente.brokers.base import Vela


def serie(tendencia, n=700, semilla=1):
    rnd, precio, out = random.Random(semilla), 100.0, []
    d = date(2018, 1, 1)
    for i in range(n):
        d += timedelta(days=1)
        abre = precio * (1 + rnd.gauss(0, 0.002))
        precio = abre * (1 + rnd.gauss(tendencia, 0.012))
        out.append(Vela(d.isoformat(), abre, max(abre, precio), min(abre, precio), precio, 1e6))
    return out


@pytest.fixture
def datos():
    return {"SPY": serie(0.0004), "A": serie(0.0015, semilla=2), "B": serie(-0.001, semilla=3),
            "C": serie(0.0005, semilla=4)}


def test_comprar_y_mantener_sigue_al_precio(datos):
    r = lab.simular(datos, lab.comprar_y_mantener(["SPY"]), "spy", coste_pct=0)
    v = datos["SPY"]
    esperado = v[-1].cierre / v[261].apertura  # decide al cierre del día 260, compra en la apertura del 261
    assert r.curva[-1] == pytest.approx(esperado, rel=1e-6)


def test_rotacion_elige_al_ganador_y_paga_costes(datos):
    r = lab.simular(datos, lab.rotacion_impulso(1, 6, filtro=False), "rot", coste_pct=0)
    assert r.curva[-1] > 1 and r.operaciones >= 1
    caro = lab.simular(datos, lab.rotacion_impulso(1, 6, filtro=False), "rot", coste_pct=1)
    assert caro.curva[-1] < r.curva[-1]


def test_estrategias_no_rompen_e_informe(datos):
    for crear in lab.ESTRATEGIAS.values():
        r = lab.simular(datos, crear(), "x")
        assert min(r.curva) > 0
    assert "Rentabilidad por año" in lab.informe(datos, 0.1)
