# Agente de trading con Claude

Agente personal que analiza el mercado una vez al día con Claude, propone operaciones
y **solo las ejecuta si pasan unos límites de riesgo fijos en el código**.

Objetivo de esta fase: **aprender con poco dinero (≈200)**, no hacerse rico.

## Cómo funciona

```
1. Stop-loss    → si una posición cae más de STOP_LOSS_PCT, se vende (sin IA)
2. Paradas      → si el patrimonio < CAPITAL_MINIMO o se pierde MAX_PERDIDA_DIARIA hoy, no opera
3. Indicadores  → precio, medias 20/50, RSI, volatilidad… (calculados en código, gratis y exactos)
4. Claude #1    → cribado rápido de todos los valores: elige como mucho 1 candidato
5. Claude #2    → "comité": argumentos a favor, en contra, riesgo y decisión final
6. Límites      → el código recorta o bloquea lo que se pase de tus límites
7. Orden        → orden limitada (no paga más de un 0,3 % sobre el último cierre); te pregunta antes
8. Diario       → todo queda en datos/ (operaciones, razonamientos, coste de la IA)
```

Claude **propone**; el código **decide si se puede**. La IA nunca puede saltarse un límite.

## Límites por defecto (editables en `.env`)

| Límite | Valor |
|---|---|
| Máximo por operación (y por valor) | 50 |
| Pérdida máxima en un día | 10 |
| Parada total si el patrimonio baja de | 150 |
| Operaciones máximas en 7 días | 5 |
| Stop-loss por posición | -8 % |
| Gasto máximo en Claude al mes | 5 $ |
| Valores permitidos | SPY, QQQ, VTI, AAPL, MSFT |
| Confirmar cada orden | sí |

## Brokers

- `simulado`: precios reales (Yahoo Finance), dinero ficticio. **Empieza aquí.**
- `alpaca`: cuenta de práctica (`ALPACA_PAPER=true`) o real (`ALPACA_PAPER=false`).

## Puesta en marcha en tu Mac

1. Instala Python 3.11 o superior (https://www.python.org/downloads/).
2. Abre la app **Terminal** y ejecuta:

   ```bash
   git clone https://github.com/controlkotler-cloud/trading.git
   cd trading
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env
   open -e .env
   ```

3. En `.env` pega tu clave de Claude (`ANTHROPIC_API_KEY`, se crea en https://console.anthropic.com).
   El archivo `.env` **no se sube nunca a GitHub** (está en `.gitignore`).
4. Prueba:

   ```bash
   python -m agente.main --estado   # ver situación
   python -m agente.main --sin-ia   # comprobar límites sin gastar en IA
   python -m agente.main            # ciclo completo
   ```

Cada vez que abras una Terminal nueva: `cd trading && source .venv/bin/activate`.

## Probar estrategias con datos históricos (backtest)

Antes de creerte una estrategia (de Instagram o de quien sea), pruébala:

```bash
python -m agente.backtest SPY QQQ           # 10 años, coste 0,1 % por operación
python -m agente.backtest AAPL --anios 5 --coste 0.2
```

Compara varias estrategias de reglas simples (comprar y mantener, precio sobre EMA9, cruce de medias 20/50,
tendencia sobre la media de 200 y rebote por RSI) en dos tramos: **entrenamiento** (70 % más antiguo) y
**prueba** (30 % más reciente). Incluye costes, no mira al futuro (ejecuta al día siguiente) y una
simulación Monte Carlo de cuánto podría caer con otra secuencia de suerte.

Regla de oro: si en el tramo de **prueba** no gana a "comprar y mantener" (o no consigue algo parecido
con mucha menos caída), no merece la pena.

## Ejecutarlo gratis en la nube (GitHub Actions)

El archivo `.github/workflows/agente.yml` ejecuta, gratis en los servidores de GitHub:

- **Ciclo completo con Claude** de lunes a viernes a las 21:40 UTC (después del cierre de EE. UU.).
- **Vigilancia sin Claude** (no cuesta nada) cada 30 minutos durante la sesión: stop-loss y límites.

### Protección durante el día

1. **Stop en el broker (Alpaca):** cada noche el agente deja una orden stop-loss puesta en Alpaca por cada
   posición. Si el precio cae durante la sesión, **Alpaca vende al instante**, aunque el agente no esté
   funcionando. Es la protección principal.
2. **Vigilancia cada 30 min:** segunda red de seguridad (y la única en modo simulado). GitHub puede
   retrasar o saltarse alguna ejecución, por eso no es la protección principal.

Ningún stop protege de un **salto en la apertura**: si una acción cierra a 100 y abre a 85 por una
noticia nocturna, se vende a 85 aunque el stop esté en 92. El diario se guarda
en la rama `datos` del repositorio, así que se conserva entre ejecuciones.

Configuración (una sola vez), en GitHub → repositorio → **Settings → Secrets and variables → Actions**:

**Secrets** (cifrados, nadie los puede leer):

| Nombre | Valor |
|---|---|
| `ANTHROPIC_API_KEY` | tu clave de Claude |
| `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` | claves de Alpaca (opcional en modo simulado: se usan solo para leer precios, más fiable que Yahoo) |

**Variables** (opcionales; si no existen se usan los valores por defecto):

| Nombre | Por defecto | Para qué |
|---|---|---|
| `BROKER` | `simulado` | `alpaca` para operar en Alpaca |
| `ALPACA_PAPER` | `true` | `false` = dinero real |
| `CONFIRMAR_ORDENES` | `false` | `true` = solo propone, no ejecuta (no hay nadie para confirmar) |
| `MAX_GASTO_IA_MES` | `5` | tope de gasto en Claude, en dólares |
| `SIMBOLOS_PERMITIDOS` | `SPY,QQQ,VTI,AAPL,MSFT` | valores que puede operar |

Para lanzarlo a mano: pestaña **Actions → Agente diario → Run workflow** (también desde la app de GitHub
en el móvil). El resultado de cada ejecución aparece en el resumen de la ejecución, y GitHub te avisa
por email si falla.

## Plan por fases

1. **Simulado** (2–4 semanas): `BROKER=simulado`. Ejecutarlo cada día y leer los razonamientos en `datos/decisiones.jsonl`.
2. **Alpaca práctica**: `BROKER=alpaca`, `ALPACA_PAPER=true`, con las claves de la cuenta de práctica.
3. **Dinero real (200)**: `ALPACA_PAPER=false` con claves de la cuenta real. Mantener `CONFIRMAR_ORDENES=true` al principio.

## Archivos

| Archivo | Qué hace |
|---|---|
| `agente/main.py` | El ciclo diario |
| `agente/analista.py` | Las dos llamadas a Claude |
| `agente/riesgo.py` | Los límites (lo más importante) |
| `agente/indicadores.py` | Indicadores técnicos |
| `agente/backtest.py` | Probador de estrategias con datos históricos |
| `agente/diario.py` | Registro de operaciones, decisiones y gasto |
| `agente/brokers/` | Simulado y Alpaca (se pueden añadir Kraken, IBKR…) |
| `tests/` | Pruebas: `python -m pytest` |

## Impuestos

`datos/operaciones.csv` guarda cada compra y venta con fecha, importe y precio: es la base para
declarar las ganancias y pérdidas patrimoniales en la renta. Consulta con un asesor.

## Aviso

Esto es un proyecto de aprendizaje. Operar en bolsa conlleva riesgo de pérdida. Nada aquí es asesoramiento financiero.
