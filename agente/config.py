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
    max_gasto_ia_mes: float = 5.0
    capital_simulado: float = 200.0
    alpaca_paper: bool = True
    carpeta_datos: str = "datos"


def cargar_config() -> Config:
    load_dotenv()
    env = os.environ

    def num(nombre: str, defecto: float) -> float:
        return float(env.get(nombre) or defecto)

    simbolos = env.get("SIMBOLOS_PERMITIDOS", "SPY,QQQ,VTI")
    return Config(
        broker=env.get("BROKER", "simulado").strip().lower(),
        max_por_operacion=num("MAX_POR_OPERACION", 50),
        max_perdida_diaria=num("MAX_PERDIDA_DIARIA", 10),
        capital_minimo=num("CAPITAL_MINIMO", 150),
        max_operaciones_semana=int(num("MAX_OPERACIONES_SEMANA", 5)),
        stop_loss_pct=num("STOP_LOSS_PCT", 8),
        simbolos_permitidos=tuple(s.strip().upper() for s in simbolos.split(",") if s.strip()),
        confirmar_ordenes=env.get("CONFIRMAR_ORDENES", "true").lower() != "false",
        max_gasto_ia_mes=num("MAX_GASTO_IA_MES", 5),
        capital_simulado=num("CAPITAL_SIMULADO", 200),
        alpaca_paper=env.get("ALPACA_PAPER", "true").lower() != "false",
        carpeta_datos=env.get("CARPETA_DATOS", "datos"),
    )
