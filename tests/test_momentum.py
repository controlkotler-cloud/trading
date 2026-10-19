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


def test_distancia_stop_se_adapta_al_valor():
    from agente.brokers.base import Vela
    tranquilo = [Vela("t", 100, 100.1, 99.9, 100, 1) for _ in range(20)]
    nervioso = [Vela("t", 100, 101, 99, 100, 1) for _ in range(20)]
    assert momentum.distancia_stop(tranquilo, 2, 0) == 2  # desactivado: trailing fijo
    assert momentum.distancia_stop(tranquilo, 2, 4) == 1.0  # mínimo 1 %
    assert momentum.distancia_stop(nervioso, 2, 4) == 6.0   # máximo 6 %


def test_minutos_sesion_y_horario():
    desde, hasta = momentum.minutos_sesion("2026-10-14 13:40:00+00:00")  # 9:40 en Nueva York
    assert (desde, hasta) == (10, 380)
    assert not momentum.en_horario(desde, hasta, 15, 30)
    assert momentum.en_horario(desde, hasta, 0, 0)
    assert momentum.minutos_sesion("d1") is None


def test_mercado_favorable():
    from agente.brokers.base import Vela
    sube = [Vela("t", c, c, c, c, 1) for c in range(100, 160)]
    baja = [Vela("t", c, c, c, c, 1) for c in range(160, 100, -1)]
    assert momentum.mercado_favorable(sube) and not momentum.mercado_favorable(baja)


def test_velas_cerradas_quita_la_vela_en_curso():
    from datetime import datetime, timezone
    ahora = datetime(2026, 10, 14, 13, 47, tzinfo=timezone.utc)
    v = [Vela("2026-10-14T13:40:00+00:00", 1, 1, 1, 1, 1), Vela("2026-10-14T13:45:00+00:00", 1, 1, 1, 1, 1)]
    assert len(momentum.velas_cerradas(v, 5, ahora)) == 1          # la de 13:45 acaba a las 13:50
    assert len(momentum.velas_cerradas(v, 5, ahora.replace(minute=50))) == 2
    assert len(momentum.velas_cerradas(velas([1, 2]), 5, ahora)) == 2  # fechas sin hora: no toca nada
