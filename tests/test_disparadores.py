from agente.disparadores import detectar


def resumen(**kw):
    base = dict(precio=100, rsi_14=50, cambio_5d_pct=0.5, volatilidad_20d_pct=1.0,
                maximo_60d=110, minimo_60d=90, media_50=100, ruptura_maximos=False)
    return {**base, **kw}


def test_dia_tranquilo_sin_avisos():
    assert detectar({"SPY": resumen()}, []) == []


def test_sobrevendido():
    d = detectar({"SPY": resumen(rsi_14=25)}, [])
    assert d[0].simbolo == "SPY" and "sobrevendido" in d[0].motivo


def test_posicion_cerca_del_stop_tiene_prioridad():
    d = detectar({"SPY": resumen(rsi_14=25), "QQQ": resumen()},
                 [{"simbolo": "QQQ", "valor": 50, "pnl_pct": -6}])
    assert d[0].simbolo == "QQQ"


def test_excluye_nucleo():
    assert detectar({"SPY": resumen(rsi_14=20)}, [], excluir=("SPY",)) == []


def test_ruptura_de_maximos_avisa_solo_sin_posicion():
    r = {"SPY": resumen(precio=111, ruptura_maximos=True)}
    assert detectar(r, [])[0].simbolo == "SPY"
    assert detectar(r, [{"simbolo": "SPY", "valor": 50, "pnl_pct": 3}]) == []
