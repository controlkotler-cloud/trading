"""Resúmenes para el móvil: diario (gratis, generado en código) y semanal (lo escribe Claude).

    python -m agente.resumen --diario
    python -m agente.resumen --semanal

Imprimen Markdown. En GitHub Actions se publican como comentario en una incidencia del repositorio
mencionando al dueño, así llegan por email y como notificación de la app de GitHub.
"""

import argparse
import json
from datetime import date, datetime, timedelta

from agente.brokers.base import Broker
from agente.config import Config, cargar_config
from agente.diario import Diario

REFERENCIA = "SPY"  # contra qué se compara: el índice S&P 500


def _inicio(diario: Diario, broker: Broker) -> dict:
    """Patrimonio y precio de referencia al empezar (se fija la primera vez)."""
    if "inicio" not in diario.estado:
        diario.estado["inicio"] = {"fecha": date.today().isoformat(), "patrimonio": broker.patrimonio(),
                                   "referencia": broker.precio(REFERENCIA) if hasattr(broker, "precio") else None}
        diario._guardar_estado()
    return diario.estado["inicio"]


def _ops_desde(diario: Diario, desde: date) -> list[dict]:
    return [o for o in diario.operaciones() if datetime.fromisoformat(o["fecha"]).date() >= desde]


def _estadisticas(ops: list[dict]) -> dict:
    ventas = [o for o in ops if o["accion"] == "vender" and o.get("resultado")]
    resultados = [float(o["resultado"]) for o in ventas]
    ganan = [r for r in resultados if r > 0]
    pierden = [r for r in resultados if r <= 0]
    return {
        "compras": sum(1 for o in ops if o["accion"] == "comprar"),
        "ventas": len(ventas),
        "ganadoras": len(ganan),
        "resultado": round(sum(resultados), 2),
        "media_ganadora": round(sum(ganan) / len(ganan), 2) if ganan else 0,
        "media_perdedora": round(sum(pierden) / len(pierden), 2) if pierden else 0,
    }


def _comparacion(diario: Diario, broker: Broker) -> tuple[float, float | None]:
    ini = _inicio(diario, broker)
    agente = (broker.patrimonio() / ini["patrimonio"] - 1) * 100
    ref = None
    if ini.get("referencia"):
        try:
            ref = (broker.precio(REFERENCIA) / ini["referencia"] - 1) * 100
        except Exception:
            pass
    return agente, ref


def diario_md(cfg: Config, broker: Broker, diario: Diario, hoy: date | None = None) -> str:
    hoy = hoy or date.today()
    patrimonio = broker.patrimonio()
    inicio_dia = diario.estado.get("patrimonio_inicio_dia", patrimonio) if diario.estado.get("dia") == hoy.isoformat() \
        else patrimonio
    cambio = (patrimonio / inicio_dia - 1) * 100 if inicio_dia else 0
    agente, ref = _comparacion(diario, broker)
    ops = _ops_desde(diario, hoy)
    e = _estadisticas(ops)
    lineas = [
        f"## 📊 Resumen del {hoy:%d/%m/%Y} ({broker.nombre})",
        "",
        f"**Patrimonio: {patrimonio:,.2f}** ({cambio:+.2f}% hoy)",
        f"Desde el inicio ({diario.estado['inicio']['fecha']}): **{agente:+.2f}%**"
        + (f" · comprar y mantener {REFERENCIA}: {ref:+.2f}%" if ref is not None else ""),
        "",
        f"Operaciones de hoy: {e['compras']} compras, {e['ventas']} ventas "
        f"({e['ganadoras']} con ganancia), resultado cerrado {e['resultado']:+.2f}",
    ]
    for o in ops:
        res = f" → {float(o['resultado']):+.2f}" if o.get("resultado") else ""
        lineas.append(f"- {o['fecha'][11:16]} {o['accion']} **{o['simbolo']}** {float(o['importe']):.2f} "
                      f"a {float(o['precio']):.2f}{res} — {o['motivo'][:90]}")
    posiciones = broker.posiciones()
    lineas += ["", "Posiciones abiertas:" if posiciones else "Sin posiciones abiertas."]
    for p in posiciones:
        maximo = diario.estado.get("maximos", {}).get(p.simbolo)
        stop = f" · stop {maximo * (1 - cfg.trailing_pct / 100):.2f}" if maximo else ""
        lineas.append(f"- **{p.simbolo}** {p.valor:,.2f} ({p.pnl_pct:+.1f}%){stop}")
    lineas += ["", f"Vigilando: {', '.join(diario.vigilancia()) or '-'} · Gasto en Claude este mes: "
                   f"{diario.gasto_ia_mes():.2f} $"]
    if diario.parada_total():
        lineas.append(f"\n⚠️ **PARADA TOTAL**: {diario.parada_total()}")
    return "\n".join(lineas)


def semanal_md(cfg: Config, broker: Broker, diario: Diario, hoy: date | None = None) -> str:
    hoy = hoy or date.today()
    desde = hoy - timedelta(days=7)
    ops = _ops_desde(diario, desde)
    e = _estadisticas(ops)
    agente, ref = _comparacion(diario, broker)
    datos = {
        "patrimonio": round(broker.patrimonio(), 2), "rentabilidad_desde_inicio_pct": round(agente, 2),
        "referencia_desde_inicio_pct": None if ref is None else round(ref, 2), "semana": e,
        "operaciones": ops[-60:], "parametros": {"trailing_pct": cfg.trailing_pct, "max_posiciones": cfg.max_posiciones,
                                                 "pct_por_posicion": cfg.pct_por_posicion,
                                                 "barras_ruptura": cfg.barras_ruptura, "universo": cfg.universo},
        "parada_total": diario.parada_total(),
    }
    cabecera = (f"## 🗓️ Revisión semanal ({desde:%d/%m} - {hoy:%d/%m})\n\n"
                f"Patrimonio {datos['patrimonio']:,.2f} · desde el inicio {agente:+.2f}%"
                + (f" · {REFERENCIA} {ref:+.2f}%" if ref is not None else "")
                + f"\nSemana: {e['compras']} compras, {e['ventas']} ventas, {e['ganadoras']} ganadoras, "
                  f"resultado {e['resultado']:+.2f}\n\n")
    if diario.gasto_ia_mes() >= cfg.max_gasto_ia_mes:
        return cabecera + "_Sin análisis de Claude: tope de gasto mensual alcanzado._"

    from agente.analista import MODELO, PRECIO_ENTRADA, PRECIO_SALIDA, Analista

    analista = Analista()
    prompt = (
        "Eres el revisor de un agente de trading de impulso con stop dinámico (cuenta "
        f"{broker.nombre}). Datos de la semana:\n{json.dumps(datos, ensure_ascii=False, default=str)}\n\n"
        "Escribe una revisión breve en español, en Markdown, para leer en el móvil:\n"
        "1. Qué ha funcionado y qué no (con cifras).\n"
        "2. Comparación honesta con comprar y mantener.\n"
        "3. Como mucho 3 ajustes concretos de parámetros que propondrías, y por qué; o ninguno si es pronto.\n"
        "4. Una línea final: ¿seguir igual, ajustar o parar?\n"
        "No inventes datos. Si hay pocas operaciones, dilo: no se pueden sacar conclusiones."
    )
    try:
        r = analista.cliente.messages.create(model=MODELO, max_tokens=4000, output_config={"effort": "medium"},
                                             messages=[{"role": "user", "content": prompt}])
        coste = r.usage.input_tokens * PRECIO_ENTRADA + r.usage.output_tokens * PRECIO_SALIDA
        diario.sumar_gasto_ia(coste)
        texto = "".join(b.text for b in r.content if b.type == "text").strip()
        return cabecera + texto + f"\n\n_Coste de esta revisión: {coste:.3f} $_"
    except Exception as ex:
        return cabecera + f"_No se pudo generar el análisis de Claude: {ex}_"


def main(argv: list[str] | None = None) -> None:
    from agente.main import crear_broker

    ap = argparse.ArgumentParser(description="Resúmenes del agente")
    ap.add_argument("--diario", action="store_true")
    ap.add_argument("--semanal", action="store_true")
    args = ap.parse_args(argv)
    cfg = cargar_config()
    broker = crear_broker(cfg)
    diario = Diario(cfg.carpeta_datos)
    if args.semanal:
        print(semanal_md(cfg, broker, diario))
    else:
        print(diario_md(cfg, broker, diario))


if __name__ == "__main__":
    main()
