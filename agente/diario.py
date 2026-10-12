"""Diario del agente: qué hizo, por qué y cuánto costó.

- datos/operaciones.csv  -> una fila por orden (sirve también para la renta)
- datos/decisiones.jsonl -> cada análisis completo de Claude, con su coste
- datos/estado.json      -> patrimonio al inicio del día y gasto en IA por mes
"""

import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path

COLUMNAS = ["fecha", "broker", "accion", "simbolo", "importe", "precio", "orden_id", "motivo"]


class Diario:
    def __init__(self, carpeta: str):
        self.carpeta = Path(carpeta)
        self.carpeta.mkdir(parents=True, exist_ok=True)
        self.ruta_ops = self.carpeta / "operaciones.csv"
        self.ruta_dec = self.carpeta / "decisiones.jsonl"
        self.ruta_estado = self.carpeta / "estado.json"
        self.estado = json.loads(self.ruta_estado.read_text()) if self.ruta_estado.exists() else {}

    def _guardar_estado(self) -> None:
        self.ruta_estado.write_text(json.dumps(self.estado, indent=2))

    # --- patrimonio diario ---
    def patrimonio_inicio_dia(self, patrimonio_actual: float, hoy: date | None = None) -> float:
        """Devuelve el patrimonio con el que empezó hoy (lo fija en la primera ejecución del día)."""
        hoy_txt = (hoy or date.today()).isoformat()
        if self.estado.get("dia") != hoy_txt:
            self.estado["dia"] = hoy_txt
            self.estado["patrimonio_inicio_dia"] = patrimonio_actual
            self._guardar_estado()
        return self.estado["patrimonio_inicio_dia"]

    # --- gasto en IA ---
    def gasto_ia_mes(self, hoy: date | None = None) -> float:
        mes = (hoy or date.today()).strftime("%Y-%m")
        return self.estado.get("gasto_ia", {}).get(mes, 0.0)

    def sumar_gasto_ia(self, usd: float, hoy: date | None = None) -> None:
        mes = (hoy or date.today()).strftime("%Y-%m")
        gastos = self.estado.setdefault("gasto_ia", {})
        gastos[mes] = round(gastos.get(mes, 0.0) + usd, 6)
        self._guardar_estado()

    # --- operaciones ---
    def registrar_operacion(self, broker: str, accion: str, simbolo: str, importe: float,
                            precio: float, orden_id: str, motivo: str) -> None:
        nuevo = not self.ruta_ops.exists()
        with self.ruta_ops.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNAS)
            if nuevo:
                w.writeheader()
            w.writerow({
                "fecha": datetime.now().isoformat(timespec="seconds"), "broker": broker,
                "accion": accion, "simbolo": simbolo, "importe": round(importe, 2),
                "precio": round(precio, 4), "orden_id": orden_id, "motivo": motivo,
            })

    def operaciones(self) -> list[dict]:
        if not self.ruta_ops.exists():
            return []
        with self.ruta_ops.open() as f:
            return list(csv.DictReader(f))

    def operaciones_ultimos_dias(self, dias: int = 7) -> int:
        limite = datetime.now() - timedelta(days=dias)
        return sum(1 for o in self.operaciones() if datetime.fromisoformat(o["fecha"]) >= limite)

    # --- decisiones ---
    def registrar_decision(self, datos: dict) -> None:
        datos = {"fecha": datetime.now().isoformat(timespec="seconds"), **datos}
        with self.ruta_dec.open("a") as f:
            f.write(json.dumps(datos, ensure_ascii=False) + "\n")
