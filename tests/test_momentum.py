import pytest

from agente import momentum
from agente.brokers.base import Vela


def velas(cierres, volumenes=None):
    volumenes = volumenes or [1000] * len(cierres)
    return [Vela(f"t{i}", c, c * 1.001, c * 0.999, c, v) for i, (c, v) in enumerate(zip(cierres, volumenes))]


def test_ruptura_con_volumen_entra():
    cierres = [100 + (i % 3) * 0.1 for i in range(40)] + [101.5]
    s = momentum.senal_entrada(velas(cierres, [1000] * 40 + [3000]))
    assert s.entrar and "rompe" in s.motivo


def test_ruptura_sin_volumen_no_entra():
    cierres = [100 + (i % 3) * 0.1 for i in range(40)] + [101.5]
    assert not momentum.senal_entrada(velas(cierres)).entrar


def test_sin_ruptura_no_entra():
    cierres = [100 + (i % 3) * 0.1 for i in range(40)] + [100.1]
    assert not momentum.senal_entrada(velas(cierres, [1000] * 40 + [5000])).entrar


def test_trailing_solo_sube_y_vende_al_girarse():
    maximo, stop, vender = momentum.actualizar_trailing(100, 110, 3)
    assert maximo == 110 and stop == pytest.approx(106.7) and not vender
    maximo, stop, vender = momentum.actualizar_trailing(maximo, 108, 3)
    assert maximo == 110 and stop == pytest.approx(106.7) and not vender  # el stop no baja
    assert momentum.actualizar_trailing(maximo, 106.5, 3)[2]


def test_tamano_reinvierte_ganancias():
    assert momentum.tamano_posicion(300, 300, 0.33) == 99
    assert momentum.tamano_posicion(300, 50, 0.33) == 50


def test_ranking_excluye_bajistas():
    r = {"A": {"precio": 10, "media_50": 9, "cambio_20d_pct": 15, "cambio_5d_pct": 3},
         "B": {"precio": 10, "media_50": 9, "cambio_20d_pct": 5, "cambio_5d_pct": 1},
         "C": {"precio": 8, "media_50": 9, "cambio_20d_pct": 30, "cambio_5d_pct": 9}}
    assert momentum.ranking_impulso(r) == ["A", "B"]
