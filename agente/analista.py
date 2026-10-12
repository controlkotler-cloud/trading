"""El cerebro: Claude analiza en dos pasos, inspirado en TradingAgents pero con 2 llamadas al día.

1. Cribado (esfuerzo bajo, barato): repasa todos los valores y elige como mucho un candidato.
2. Decisión (esfuerzo alto): debate a favor / en contra sobre ese candidato y propone qué hacer.

Claude solo PROPONE. Los límites de riesgo los aplica riesgo.py después.
"""

import json
from typing import Literal

import anthropic
from pydantic import BaseModel

MODELO = "claude-opus-5-5"
# Precio de Claude Opus 5.5 en dólares por token (4 $ / 20 $ por millón)
PRECIO_ENTRADA = 4 / 1_000_000
PRECIO_SALIDA = 20 / 1_000_000

SISTEMA = """Eres el analista de un agente de trading personal con un capital muy pequeño (unos 200).
Objetivo: aprender y preservar capital. Operar poco y solo con ventaja clara.

Reglas de criterio:
- "Mantener" (no hacer nada) es la respuesta correcta la mayoría de los días.
- Toda propuesta debe explicar cuál es la ventaja concreta y por qué no está ya en el precio.
- Ten en cuenta que cada operación tiene costes y que el horizonte es de días a semanas, no minutos.
- No inventes datos: usa solo los indicadores y posiciones que se te dan.
- Escribe en español, claro y breve."""


class AnalisisValor(BaseModel):
    simbolo: str
    tendencia: Literal["alcista", "bajista", "lateral"]
    puntuacion: int  # de -5 (vender) a +5 (comprar)
    resumen: str


class Cribado(BaseModel):
    valores: list[AnalisisValor]
    candidato: str | None  # símbolo a estudiar a fondo, o null si no hay nada interesante
    accion_candidata: Literal["comprar", "vender", "ninguna"]
    motivo: str


class Decision(BaseModel):
    accion: Literal["comprar", "vender", "mantener"]
    simbolo: str
    importe: float  # en la moneda de la cuenta; 0 si mantener o vender
    argumentos_a_favor: list[str]
    argumentos_en_contra: list[str]
    ventaja: str  # por qué esta operación tiene ventaja
    riesgo_principal: str
    confianza: int  # 1 a 10
    razonamiento: str


class Analista:
    def __init__(self):
        self.cliente = anthropic.Anthropic()
        self.gasto_usd = 0.0

    def _llamar(self, prompt: str, formato: type[BaseModel], esfuerzo: str):
        respuesta = self.cliente.messages.parse(
            model=MODELO,
            max_tokens=16000,
            system=SISTEMA,
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

    def cribar(self, resumenes: list[dict], posiciones: list[dict], efectivo: float) -> Cribado | None:
        prompt = (
            "Indicadores diarios de los valores permitidos:\n"
            f"{json.dumps(resumenes, ensure_ascii=False, indent=1)}\n\n"
            f"Posiciones abiertas: {json.dumps(posiciones, ensure_ascii=False)}\n"
            f"Efectivo disponible: {efectivo:.2f}\n\n"
            "Analiza cada valor y elige como mucho UN candidato para comprar o vender. "
            "Si nada destaca claramente, candidato = null y accion_candidata = 'ninguna'."
        )
        return self._llamar(prompt, Cribado, esfuerzo="low")

    def decidir(self, cribado: Cribado, resumen: dict, posiciones: list[dict],
                efectivo: float, max_importe: float) -> Decision | None:
        prompt = (
            f"El cribado propone: {cribado.accion_candidata} {cribado.candidato}. Motivo: {cribado.motivo}\n\n"
            f"Indicadores de {cribado.candidato}:\n{json.dumps(resumen, ensure_ascii=False, indent=1)}\n\n"
            f"Posiciones abiertas: {json.dumps(posiciones, ensure_ascii=False)}\n"
            f"Efectivo disponible: {efectivo:.2f}. Importe máximo por operación: {max_importe:.2f}\n\n"
            "Haz de comité de inversión:\n"
            "1. Analista optimista: los mejores argumentos A FAVOR.\n"
            "2. Analista pesimista: los mejores argumentos EN CONTRA.\n"
            "3. Gestor de riesgo: ¿qué puede salir mal y cuánto arriesgar?\n"
            "4. Decisión final: comprar, vender o mantener. Si los argumentos en contra pesan igual o más, mantener."
        )
        return self._llamar(prompt, Decision, esfuerzo="high")
