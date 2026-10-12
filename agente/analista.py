"""El cerebro: Claude actúa de comité de inversión sobre UN valor, solo cuando hay un disparo.

Inspirado en TradingAgents (debate a favor / en contra + gestor de riesgo), pero en una sola llamada.
Los disparadores gratuitos (disparadores.py) deciden cuándo merece la pena llamar.

Claude solo PROPONE. Los límites de riesgo, costes e impuestos los aplica riesgo.py después.
"""

import json
import os
from typing import Literal

import anthropic
from pydantic import BaseModel

MODELO = "claude-opus-5-5"
# Precio de Claude Opus 5.5 en dólares por token (4 $ / 20 $ por millón)
PRECIO_ENTRADA = 4 / 1_000_000
PRECIO_SALIDA = 20 / 1_000_000

SISTEMA = """Eres el analista de un agente de trading personal con un capital muy pequeño (unos 200).
Objetivo: máxima rentabilidad NETA (después de costes e impuestos), preservando capital.

Reglas de criterio:
- "Mantener" (no hacer nada) es la respuesta correcta la mayoría de las veces.
- Toda propuesta debe explicar cuál es la ventaja concreta y por qué no está ya en el precio.
- Estima la rentabilidad esperada en % para el horizonte que propones, siendo conservador.
  Solo compensa si supera con holgura los costes (diferencia de precio, comisiones) y el 19 % de impuestos sobre la ganancia.
- Vender con ganancia genera impuestos; mantener una posición ganadora los aplaza. Véndela solo si hay un motivo claro.
- Horizonte de días a semanas, no minutos.
- No inventes datos: usa solo los indicadores y posiciones que se te dan.
- Escribe en español, claro y breve."""


class Decision(BaseModel):
    accion: Literal["comprar", "vender", "mantener"]
    simbolo: str
    importe: float  # en la moneda de la cuenta; 0 si mantener o vender
    argumentos_a_favor: list[str]
    argumentos_en_contra: list[str]
    ventaja: str  # por qué esta operación tiene ventaja
    riesgo_principal: str
    rentabilidad_esperada_pct: float  # estimación conservadora para el horizonte
    horizonte_dias: int
    confianza: int  # 1 a 10
    razonamiento: str


class Seleccion(BaseModel):
    vigilar: list[str]  # valores a vigilar hoy, del más al menos prometedor
    evitar: list[str]   # valores del universo que hoy conviene no tocar
    motivo: str


SISTEMA_SELECCION = """Eres el analista matinal de un agente de trading de impulso (momentum) intradía de alto riesgo.
El agente compra rupturas al alza con volumen y sale con un stop dinámico. Tu trabajo: elegir qué valores
del universo vigilar hoy. Prioriza los que tienen tendencia fuerte, volatilidad suficiente para moverse
durante el día y liquidez. Evita los que están en caída o sin dirección. Usa los titulares recientes:
un catalizador claro (resultados, contratos, mejoras de recomendación) refuerza el impulso; resultados
inminentes o noticias negativas son riesgo de salto en contra. No inventes datos ni noticias.
Escribe en español y breve."""


class Analista:
    def __init__(self):
        # Si la clave de API no pertenece a un "workspace", hay que indicar cuál usar
        workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
        cabeceras = {"anthropic-workspace-id": workspace} if workspace else None
        self.cliente = anthropic.Anthropic(default_headers=cabeceras)
        self.gasto_usd = 0.0

    def _llamar(self, prompt: str, formato: type[BaseModel], esfuerzo: str, sistema: str = SISTEMA):
        respuesta = self.cliente.messages.parse(
            model=MODELO,
            max_tokens=16000,
            system=sistema,
            output_config={"effort": esfuerzo},
            output_format=formato,
            messages=[{"role": "user", "content": prompt}],
            # Si un filtro de seguridad rechaza la petición, la API la reintenta con otro modelo
            extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
            extra_body={"fallbacks": "default"},
        )
        uso = respuesta.usage
        self.gasto_usd += uso.input_tokens * PRECIO_ENTRADA + uso.output_tokens * PRECIO_SALIDA
        if respuesta.stop_reason == "refusal":
            return None
        return respuesta.parsed_output

    def decidir(self, simbolo: str, motivo: str, resumen: dict, posiciones: list[dict],
                efectivo: float, max_importe: float, avisos_fiscales: list[str]) -> Decision | None:
        prompt = (
            f"Se ha activado un aviso en {simbolo}: {motivo}\n\n"
            f"Indicadores diarios de {simbolo}:\n{json.dumps(resumen, ensure_ascii=False, indent=1)}\n\n"
            f"Posiciones abiertas: {json.dumps(posiciones, ensure_ascii=False)}\n"
            f"Efectivo disponible: {efectivo:.2f}. Importe máximo por operación: {max_importe:.2f}\n"
            + (f"Avisos fiscales: {'; '.join(avisos_fiscales)}\n" if avisos_fiscales else "")
            + "\nHaz de comité de inversión:\n"
            "1. Analista optimista: los mejores argumentos A FAVOR de actuar.\n"
            "2. Analista pesimista: los mejores argumentos EN CONTRA.\n"
            "3. Gestor de riesgo: qué puede salir mal, cuánto arriesgar, y si la rentabilidad esperada "
            "compensa costes e impuestos.\n"
            "4. Decisión final: comprar, vender o mantener. Si los argumentos en contra pesan igual o más, mantener."
        )
        return self._llamar(prompt, Decision, esfuerzo="high")

    def seleccionar(self, resumenes: dict[str, dict], ranking: list[str], maximo: int,
                    noticias: dict[str, list[str]] | None = None) -> Seleccion | None:
        prompt = (
            f"Indicadores diarios del universo:\n{json.dumps(resumenes, ensure_ascii=False, indent=1)}\n\n"
            f"Ranking por impulso calculado en código: {ranking}\n\n"
            + (f"Titulares recientes:\n{json.dumps(noticias, ensure_ascii=False, indent=1)}\n\n" if noticias
               else "No hay titulares disponibles.\n\n")
            + f"Elige como mucho {maximo} valores para vigilar hoy y cuáles evitar."
        )
        return self._llamar(prompt, Seleccion, esfuerzo="medium", sistema=SISTEMA_SELECCION)


def probar_conexion() -> str:
    """Llamada mínima para comprobar que la clave de Claude funciona y hay saldo."""
    analista = Analista()
    r = analista.cliente.messages.create(
        model=MODELO, max_tokens=200, output_config={"effort": "low"},
        messages=[{"role": "user", "content": "Responde solo: OK"}],
    )
    texto = "".join(b.text for b in r.content if b.type == "text").strip()
    coste = r.usage.input_tokens * PRECIO_ENTRADA + r.usage.output_tokens * PRECIO_SALIDA
    return f"Claude responde: {texto!r} | modelo {r.model} | coste {coste:.4f} $"
