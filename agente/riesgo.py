"""Reglas de riesgo. Las aplica el código, nunca la IA: Claude propone, esto decide.

Todas las funciones son puras (sin red ni disco) para poder probarlas a fondo.
"""

from dataclasses import dataclass

from agente.brokers.base import Posicion
from agente.config import Config


@dataclass
class Veredicto:
    permitido: bool
    motivo: str
    importe: float = 0.0


def parada_general(patrimonio: float, patrimonio_inicio_dia: float, cfg: Config) -> Veredicto:
    """¿Hay que dejar de operar del todo (hoy o para siempre)?"""
    if patrimonio < cfg.capital_minimo:
        return Veredicto(False, f"PARADA TOTAL: patrimonio {patrimonio:.2f} por debajo del mínimo {cfg.capital_minimo:.2f}. "
                                 "Revisa la estrategia antes de volver a activar el agente.")
    perdida_hoy = patrimonio_inicio_dia - patrimonio
    if perdida_hoy >= cfg.max_perdida_diaria:
        return Veredicto(False, f"Parada por hoy: pérdida diaria {perdida_hoy:.2f} >= límite {cfg.max_perdida_diaria:.2f}")
    return Veredicto(True, "ok")


def posiciones_a_cerrar_por_stop(posiciones: list[Posicion], cfg: Config) -> list[Posicion]:
    """Posiciones que han caído más que el stop-loss: se venden sin consultar a la IA."""
    return [p for p in posiciones if p.pnl_pct <= -cfg.stop_loss_pct]


def validar_compra(simbolo: str, importe: float, efectivo: float, operaciones_semana: int,
                   posiciones: list[Posicion], cfg: Config) -> Veredicto:
    simbolo = simbolo.upper()
    if simbolo not in cfg.simbolos_permitidos:
        return Veredicto(False, f"{simbolo} no está en la lista de valores permitidos")
    if operaciones_semana >= cfg.max_operaciones_semana:
        return Veredicto(False, f"Límite semanal alcanzado ({operaciones_semana}/{cfg.max_operaciones_semana} operaciones)")
    ya_invertido = sum(p.valor for p in posiciones if p.simbolo == simbolo)
    hueco = cfg.max_por_operacion - ya_invertido
    importe = min(importe, cfg.max_por_operacion, hueco, efectivo)
    if importe < 1:
        return Veredicto(False, f"Importe resultante demasiado pequeño ({importe:.2f}): "
                                f"efectivo {efectivo:.2f}, ya invertido en {simbolo} {ya_invertido:.2f}")
    return Veredicto(True, "ok", round(importe, 2))


def validar_venta(simbolo: str, posiciones: list[Posicion], operaciones_semana: int, cfg: Config) -> Veredicto:
    if not any(p.simbolo == simbolo.upper() for p in posiciones):
        return Veredicto(False, f"No hay posición abierta en {simbolo}")
    if operaciones_semana >= cfg.max_operaciones_semana:
        return Veredicto(False, f"Límite semanal alcanzado ({operaciones_semana}/{cfg.max_operaciones_semana} operaciones)")
    return Veredicto(True, "ok")
