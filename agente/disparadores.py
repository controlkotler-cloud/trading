"""Disparadores: reglas gratuitas que deciden SI merece la pena consultar a Claude.

Con 200 de capital, la IA es el mayor coste: 3 $/mes son ~18 % al año del capital.
Por eso Claude solo se consulta los días en que pasa algo; el resto de días el coste es 0.
"""

from dataclasses import dataclass


@dataclass
class Disparo:
    simbolo: str
    motivo: str
    prioridad: int  # mayor = más urgente


def detectar(resumenes: dict[str, dict], posiciones: list[dict], excluir: tuple[str, ...] = ()) -> list[Disparo]:
    """Devuelve los disparos ordenados por prioridad (el primero es el que se analiza)."""
    disparos: list[Disparo] = []
    pos = {p["simbolo"]: p for p in posiciones}

    for s, r in resumenes.items():
        if s in excluir:
            continue
        motivos, prioridad = [], 0
        if s in pos:
            pnl = pos[s]["pnl_pct"]
            if pnl >= 15:
                motivos.append(f"posición con +{pnl:.1f}%: ¿recoger beneficios?")
                prioridad = max(prioridad, 3)
            elif pnl <= -5:
                motivos.append(f"posición con {pnl:.1f}%, acercándose al stop")
                prioridad = max(prioridad, 4)
        if r["rsi_14"] < 30:
            motivos.append(f"RSI {r['rsi_14']:.0f}: sobrevendido")
            prioridad = max(prioridad, 2)
        elif r["rsi_14"] > 75 and s in pos:
            motivos.append(f"RSI {r['rsi_14']:.0f}: sobrecomprado")
            prioridad = max(prioridad, 2)
        if abs(r["cambio_5d_pct"]) >= max(5.0, 2.5 * r["volatilidad_20d_pct"]):
            motivos.append(f"movimiento fuerte en 5 días ({r['cambio_5d_pct']:+.1f}%)")
            prioridad = max(prioridad, 2)
        if r.get("ruptura_maximos") and r.get("media_50") and r["precio"] > r["media_50"] and s not in pos:
            # solo el día de la ruptura: si no, en mercados alcistas avisaría a diario y gastaría en IA
            motivos.append("rompe máximos de 60 días con tendencia alcista")
            prioridad = max(prioridad, 1)
        if motivos:
            disparos.append(Disparo(s, "; ".join(motivos), prioridad))

    return sorted(disparos, key=lambda d: -d.prioridad)
