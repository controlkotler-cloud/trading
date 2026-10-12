"""Configuración leída del archivo .env. Los límites de riesgo viven aquí."""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    broker: str = "simulado"
    max_por_operacion: float = 50.0
    max_perdida_diaria: float = 10.0
    capital_minimo: float = 150.0
    max_operaciones_semana: int = 5
    stop_loss_pct: float = 8.0
    simbolos_permitidos: tuple[str, ...] = field(default=("SPY", "QQQ", "VTI"))
    confirmar_ordenes: bool = True
    max_gasto_ia_mes: float = 2.0
    min_rentabilidad_pct: float = 2.0
    min_confianza: int = 6
    regla_dos_meses: bool = True
    nucleo_simbolo: str = ""
    nucleo_pct: float = 0.6
    capital_simulado: float = 200.0
    # --- modo momentum (operar activamente durante la sesión) ---
    modo: str = "momentum"  # "momentum" (activo) o "conservador" (una decisión al día)
    universo: tuple[str, ...] = field(default=("NVDA", "TSLA", "AMD", "META", "AMZN", "AAPL", "MSFT", "GOOGL",
                                               "NFLX", "AVGO", "PLTR", "COIN", "QQQ", "SPY"))
    vigilar_max: int = 6
    max_posiciones: int = 3
    pct_por_posicion: float = 0.33
    trailing_pct: float = 3.0
    barras_ruptura: int = 20
    minutos_vela: int = 15
    volumen_minimo: float = 1.5
    max_perdida_diaria_pct: float = 8.0
    parada_drawdown_pct: float = 40.0
    espera_reentrada_min: int = 60
    alpaca_paper: bool = True
    carpeta_datos: str = "datos"


def cargar_config() -> Config:
    load_dotenv()
    env = os.environ

    def num(nombre: str, defecto: float) -> float:
        return float(env.get(nombre) or defecto)

    simbolos = env.get("SIMBOLOS_PERMITIDOS") or "SPY,QQQ,VTI"
    return Config(
        broker=env.get("BROKER", "simulado").strip().lower(),
        max_por_operacion=num("MAX_POR_OPERACION", 50),
        max_perdida_diaria=num("MAX_PERDIDA_DIARIA", 10),
        capital_minimo=num("CAPITAL_MINIMO", 150),
        max_operaciones_semana=int(num("MAX_OPERACIONES_SEMANA", 5)),
        stop_loss_pct=num("STOP_LOSS_PCT", 8),
        simbolos_permitidos=tuple(s.strip().upper() for s in simbolos.split(",") if s.strip()),
        confirmar_ordenes=env.get("CONFIRMAR_ORDENES", "true").lower() != "false",
        max_gasto_ia_mes=num("MAX_GASTO_IA_MES", 2),
        min_rentabilidad_pct=num("MIN_RENTABILIDAD_PCT", 2),
        min_confianza=int(num("MIN_CONFIANZA", 6)),
        regla_dos_meses=env.get("REGLA_DOS_MESES", "true").lower() != "false",
        nucleo_simbolo=env.get("NUCLEO_SIMBOLO", "").strip().upper(),
        nucleo_pct=num("NUCLEO_PCT", 0.6),
        capital_simulado=num("CAPITAL_SIMULADO", 2000),
        modo=env.get("MODO", "momentum").strip().lower(),
        universo=tuple(x.strip().upper() for x in (env.get("UNIVERSO") or ",".join(Config.universo)).split(",") if x.strip()),
        vigilar_max=int(num("VIGILAR_MAX", 6)),
        max_posiciones=int(num("MAX_POSICIONES", 3)),
        pct_por_posicion=num("PCT_POR_POSICION", 0.33),
        trailing_pct=num("TRAILING_PCT", 3),
        barras_ruptura=int(num("BARRAS_RUPTURA", 20)),
        minutos_vela=int(num("MINUTOS_VELA", 15)),
        volumen_minimo=num("VOLUMEN_MINIMO", 1.5),
        max_perdida_diaria_pct=num("MAX_PERDIDA_DIARIA_PCT", 8),
        parada_drawdown_pct=num("PARADA_DRAWDOWN_PCT", 40),
        espera_reentrada_min=int(num("ESPERA_REENTRADA_MIN", 60)),
        alpaca_paper=env.get("ALPACA_PAPER", "true").lower() != "false",
        carpeta_datos=env.get("CARPETA_DATOS", "datos"),
    )
