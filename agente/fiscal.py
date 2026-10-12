"""Informe fiscal estimado para la renta española (ganancias y pérdidas patrimoniales).

    python -m agente.fiscal 2026               # convierte a euros con el tipo de cambio de cada día
    python -m agente.fiscal 2026 --sin-divisa  # en la moneda de la cuenta, sin convertir

Cómo calcula (criterios de Hacienda):
- FIFO: cada venta se empareja con las compras más antiguas del mismo valor.
- En euros: compra y venta se convierten con el tipo de cambio de su propia fecha
  (así se incluye también la ganancia o pérdida por divisa).
- Regla de los 2 meses: una venta con pérdidas no se puede compensar ese año si se compró el mismo
  valor en los 2 meses anteriores o posteriores y se sigue teniendo. Se marca como "diferida".
- Impuesto estimado con los tramos de la base del ahorro.

Es una ESTIMACIÓN a partir del diario del agente. Para la declaración usa los datos oficiales del broker
y, si tienes dudas, consulta con un asesor.
"""

import argparse
import csv
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

TRAMOS_AHORRO = [(6_000, 0.19), (50_000, 0.21), (200_000, 0.23), (300_000, 0.27), (float("inf"), 0.30)]


@dataclass
class Lote:
    fecha: date
    cantidad: float
    precio: float
    tipo: float  # unidades de la moneda de la cuenta por 1 euro


@dataclass
class Venta:
    fecha: date
    simbolo: str
    cantidad: float
    transmision: float  # valor de venta en euros
    adquisicion: float  # coste en euros
    diferida: bool = False

    @property
    def resultado(self) -> float:
        return self.transmision - self.adquisicion


@dataclass
class Informe:
    anio: int
    ventas: list[Venta] = field(default_factory=list)

    @property
    def ganancias(self) -> float:
        return sum(v.resultado for v in self.ventas if v.resultado > 0)

    @property
    def perdidas_computables(self) -> float:
        return sum(v.resultado for v in self.ventas if v.resultado < 0 and not v.diferida)

    @property
    def perdidas_diferidas(self) -> float:
        return sum(v.resultado for v in self.ventas if v.resultado < 0 and v.diferida)

    @property
    def neto(self) -> float:
        return self.ganancias + self.perdidas_computables


def impuesto_ahorro(base: float) -> float:
    if base <= 0:
        return 0.0
    total, anterior = 0.0, 0.0
    for limite, tipo in TRAMOS_AHORRO:
        tramo = min(base, limite) - anterior
        if tramo <= 0:
            break
        total += tramo * tipo
        anterior = limite
    return total


def calcular(operaciones: list[dict], anio: int, tipo_cambio=lambda d: 1.0) -> Informe:
    """operaciones: filas de datos/operaciones.csv en orden cronológico."""
    lotes: dict[str, list[Lote]] = {}
    compras: dict[str, list[tuple[date, Lote]]] = {}
    informe = Informe(anio)

    for o in sorted(operaciones, key=lambda o: o["fecha"]):
        fecha = datetime.fromisoformat(o["fecha"]).date()
        s, precio = o["simbolo"], float(o["precio"])
        cantidad = float(o["cantidad"]) if o.get("cantidad") else float(o["importe"]) / precio
        tipo = tipo_cambio(fecha)
        if o["accion"] == "comprar":
            lote = Lote(fecha, cantidad, precio, tipo)
            lotes.setdefault(s, []).append(lote)
            compras.setdefault(s, []).append((fecha, lote))
            continue
        # venta: FIFO
        pendiente, coste_eur, usados = cantidad, 0.0, []
        cola = lotes.get(s, [])
        while pendiente > 1e-9 and cola:
            lote = cola[0]
            q = min(pendiente, lote.cantidad)
            coste_eur += q * lote.precio / lote.tipo
            lote.cantidad -= q
            pendiente -= q
            usados.append(lote)
            if lote.cantidad <= 1e-9:
                cola.pop(0)
        venta = Venta(fecha, s, cantidad, cantidad * precio / tipo, coste_eur)
        if fecha.year == anio:
            informe.ventas.append(venta)

    # Regla de los 2 meses (se evalúa al final: necesita las compras posteriores a cada venta)
    for v in informe.ventas:
        if v.resultado >= 0:
            continue
        ventana = timedelta(days=61)
        for fecha_c, lote in compras.get(v.simbolo, []):
            if abs(fecha_c - v.fecha) <= ventana and fecha_c != v.fecha and lote.cantidad > 1e-9:
                v.diferida = True
                break
    return informe


def tipos_eur(moneda_por_eur: str = "EURUSD=X"):
    """Devuelve una función fecha -> unidades de dólar por euro (último cierre disponible)."""
    import yfinance as yf

    df = yf.Ticker(moneda_por_eur).history(period="10y", interval="1d")
    serie = {i.date(): float(r.Close) for i, r in df.iterrows()}
    fechas = sorted(serie)

    def tipo(d: date) -> float:
        anteriores = [f for f in fechas if f <= d]
        return serie[anteriores[-1] if anteriores else fechas[0]]

    return tipo


def texto(inf: Informe, moneda: str) -> str:
    lineas = [f"\nInforme fiscal estimado {inf.anio} (importes en {moneda})\n",
              f"{'Fecha':<11} {'Valor':<6} {'Transmisión':>12} {'Adquisición':>12} {'Resultado':>10}"]
    for v in inf.ventas:
        marca = "  (diferida: regla 2 meses)" if v.diferida else ""
        lineas.append(f"{v.fecha!s:<11} {v.simbolo:<6} {v.transmision:>12.2f} {v.adquisicion:>12.2f} "
                      f"{v.resultado:>+10.2f}{marca}")
    lineas += [
        "",
        f"Ganancias:                 {inf.ganancias:>10.2f}",
        f"Pérdidas compensables:     {inf.perdidas_computables:>10.2f}",
        f"Pérdidas diferidas:        {inf.perdidas_diferidas:>10.2f}  (se podrán computar cuando vendas lo recomprado)",
        f"Resultado neto:            {inf.neto:>10.2f}",
        f"Impuesto estimado:         {impuesto_ahorro(inf.neto):>10.2f}",
    ]
    if inf.neto < 0:
        lineas.append("Pérdida neta: se puede compensar con ganancias de los 4 años siguientes "
                      "(y hasta un 25 % con intereses o dividendos del mismo año).")
    lineas.append("\nEn la renta va en 'Ganancias y pérdidas patrimoniales derivadas de la transmisión de "
                  "acciones'. Estimación orientativa: usa los datos oficiales del broker.")
    return "\n".join(lineas)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Informe fiscal estimado")
    ap.add_argument("anio", type=int, nargs="?", default=date.today().year)
    ap.add_argument("--sin-divisa", action="store_true", help="no convertir a euros")
    ap.add_argument("--datos", default="datos")
    args = ap.parse_args(argv)

    ruta = Path(args.datos) / "operaciones.csv"
    if not ruta.exists():
        raise SystemExit(f"No hay operaciones en {ruta}")
    with ruta.open() as f:
        ops = list(csv.DictReader(f))
    if args.sin_divisa:
        print(texto(calcular(ops, args.anio), "moneda de la cuenta"))
    else:
        print(texto(calcular(ops, args.anio, tipos_eur()), "euros"))


if __name__ == "__main__":
    main()
