"""Titulares recientes de Alpaca (gratis con las claves de la cuenta) para que Claude elija mejor.

No es lo mismo un valor que sube por unos buenos resultados que uno que sube sin motivo, o que
tiene resultados mañana (riesgo de salto). Si no hay claves o falla la red, devuelve {} y el
agente sigue funcionando sin noticias.
"""

import os
from datetime import datetime, timedelta, timezone


def agrupar(noticias, simbolos: list[str], por_valor: int = 3) -> dict[str, list[str]]:
    """Reparte los titulares entre los valores que mencionan (los más recientes primero)."""
    resultado: dict[str, list[str]] = {s: [] for s in simbolos}
    for n in sorted(noticias, key=lambda n: n.created_at, reverse=True):
        texto = f"[{n.created_at:%d/%m %H:%M}] {n.headline}"
        for s in n.symbols or []:
            if s in resultado and len(resultado[s]) < por_valor:
                resultado[s].append(texto)
    return {s: t for s, t in resultado.items() if t}


def titulares(simbolos: list[str], horas: int = 36, por_valor: int = 3) -> dict[str, list[str]]:
    clave, secreto = os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_SECRET_KEY")
    if not clave or not secreto or not simbolos:
        return {}
    try:
        from alpaca.data.historical.news import NewsClient
        from alpaca.data.requests import NewsRequest

        cliente = NewsClient(clave, secreto)
        req = NewsRequest(symbols=",".join(simbolos), start=datetime.now(timezone.utc) - timedelta(hours=horas),
                          limit=50, exclude_contentless=False)
        datos = cliente.get_news(req).data
        noticias = datos.get("news", []) if isinstance(datos, dict) else list(datos)
        return agrupar(noticias, simbolos, por_valor)
    except Exception as e:
        print(f"Aviso: sin noticias de Alpaca ({e})")
        return {}
