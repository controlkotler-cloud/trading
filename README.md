# Agente de trading con Claude

Dos modos (variable `MODO`):

- **`momentum`** (por defecto): opera activamente durante la sesión de EE. UU. como lo haría un trader
  pendiente de la pantalla. Compra rupturas al alza con volumen, sube el stop conforme sube el precio
  (stop dinámico), vende cuando se gira y reinvierte las ganancias. Alto riesgo.
- **`conservador`**: una decisión al día con Claude, límites estrictos (descrito más abajo).

## Modo momentum

```
13:15 UTC    Selección: ranking de impulso del UNIVERSO + titulares de Alpaca; Claude elige hasta 6 valores (1 consulta/día)
Cada 10 min  Operador (sin IA, coste 0):
             1. Seguridad: si cae PARADA_DRAWDOWN_PCT desde el máximo -> vende todo y se para
                           si hoy pierde MAX_PERDIDA_DIARIA_PCT -> no abre más hoy
             2. Stop dinámico: guarda el máximo de cada posición y vende si cae TRAILING_PCT desde él;
                el stop se deja también puesto en el broker para que actúe entre pasadas
             3. Entradas: rompe el máximo de 20 velas de 15 min, sobre su media y con volumen x1,5
                -> compra PCT_POR_POSICION del patrimonio actual (interés compuesto)
```

### Resúmenes

- **Diario** (tras el cierre, gratis): patrimonio, operaciones del día, posiciones con su stop y
  comparación con comprar y mantener SPY.
- **Semanal** (viernes, lo escribe Claude, ~0,05 $): qué ha funcionado, qué no y ajustes propuestos.

Se publican como comentario en la incidencia "📊 Resúmenes del agente" (pestaña Issues) mencionando al
dueño del repositorio, así llegan **por email y a la app de GitHub**. Para lanzarlos a mano:
Run workflow → `resumen-diario` o `resumen-semanal`.

Pruébalo antes con datos reales de los últimos 60 días:

```bash
python -m agente.backtest_momentum                  # universo por defecto
python -m agente.backtest_momentum NVDA TSLA AMD --trailing 4
```

(o en GitHub: Actions → Agente diario → Run workflow → `backtest-momentum`).

Para operar de verdad de forma continua (cada minuto) en un Mac encendido o un servidor:
`python -m agente.main --bucle`. GitHub Actions lo hace cada 10 minutos, gratis pero con algún retraso.

Notas: la normativa de EE. UU. que exigía 25.000 $ para hacer day trading se eliminó en 2026.
En este modo la regla fiscal de los 2 meses no bloquea recompras: las pérdidas no se pierden, se
difieren (el informe fiscal las marca). Antes de fin de año conviene revisarlo.

---

## Modo conservador

Agente que analiza el mercado una vez al día con Claude, propone operaciones
y **solo las ejecuta si pasan unos límites de riesgo fijos en el código**.

## Cómo funciona

```
1. Stop-loss     → si una posición cae más de STOP_LOSS_PCT, se vende (sin IA)
2. Paradas       → si el patrimonio < CAPITAL_MINIMO o se pierde MAX_PERDIDA_DIARIA hoy, no opera
3. Núcleo        → mantiene NUCLEO_PCT del patrimonio en un índice amplio (solo compra, nunca vende)
4. Indicadores   → precio, medias, RSI, volatilidad… (calculados en código, gratis)
5. Disparadores  → reglas gratuitas: ¿pasa algo hoy? Si no, NO se llama a Claude (coste 0)
6. Claude        → "comité" sobre el valor con aviso: a favor, en contra, riesgo, rentabilidad esperada
7. Filtros       → riesgo + costes (rentabilidad y confianza mínimas) + impuestos (regla de los 2 meses)
8. Orden         → orden limitada (no paga más de un 0,3 % sobre el último cierre)
9. Diario        → operaciones con resultado, razonamientos y coste de la IA en datos/
```

Claude **propone**; el código **decide si se puede**. La IA nunca puede saltarse un límite.

## Optimización de costes e impuestos

Con poco capital, lo que más pesa no son las comisiones del broker sino **el coste de la IA y el número
de operaciones**. El agente está diseñado para minimizar ambos:

| Palanca | Cómo se aplica |
|---|---|
| **Coste de la IA** | Claude solo se consulta los días con avisos (disparadores gratuitos), una sola llamada. Tope mensual `MAX_GASTO_IA_MES` (2 $ por defecto). |
| **Operar solo si compensa** | Claude debe estimar una rentabilidad ≥ `MIN_RENTABILIDAD_PCT` (2 %) y confianza ≥ `MIN_CONFIANZA` (6/10); si no, no se opera. |
| **Diferencia de precio** | Órdenes limitadas y valores muy líquidos. |
| **Núcleo-satélite** | `NUCLEO_PCT` (60 %) en un índice amplio que **nunca se vende**: casi sin costes y sin impuestos hasta que vendas (aplazar impuestos es rentabilidad). El 40 % restante es el que mueve el agente. |
| **Regla de los 2 meses** | No recompra un valor vendido con pérdidas en 61 días, para que la pérdida se pueda compensar en la renta. |
| **Vender ganadoras** | Claude sabe que vender con ganancia genera el 19 % de impuesto y solo lo propone con motivo claro. |

### Informe fiscal

```bash
python -m agente.fiscal 2026
```

Calcula ganancias y pérdidas **en euros** (con el tipo de cambio de cada fecha), emparejando compras y
ventas por **FIFO** como exige Hacienda, marca las pérdidas **diferidas** por la regla de los 2 meses y
estima el impuesto con los tramos del ahorro (19 % hasta 6.000 €). Es una estimación: para la
declaración usa los datos oficiales del broker.

**Ojo con los ETF de EE. UU. (SPY, QQQ, VTI):** la normativa europea (PRIIPs) suele impedir que los
particulares de la UE los compren. Si tu cuenta real no lo permite, usa para el núcleo un ETF europeo
equivalente que ofrezca el broker, o acciones (las acciones no están afectadas).

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
| `MODO` | `momentum` | `momentum` o `conservador` |
| `UNIVERSO` | 14 valores tecnológicos y ETFs | valores entre los que elige |
| `TRAILING_PCT` / `MAX_POSICIONES` / `PCT_POR_POSICION` | `3` / `3` / `0.33` | stop dinámico y tamaño |
| `CAPITAL_SIMULADO` | `2000` | dinero ficticio inicial |
| `MAX_GASTO_IA_MES` | `2` | tope de gasto en Claude, en dólares |
| `SIMBOLOS_PERMITIDOS` | `QQQ,VTI,AAPL,MSFT` | valores que puede operar |
| `NUCLEO_SIMBOLO` / `NUCLEO_PCT` | (vacío) / `0.6` | modo conservador: núcleo que no se vende |
| `ANTHROPIC_WORKSPACE_ID` | (vacío) | solo si tu clave de Claude no pertenece a un workspace |

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
| `agente/main.py` | Punto de entrada y ciclo del modo conservador |
| `agente/operador.py` | Modo momentum: selección, stops dinámicos y entradas |
| `agente/momentum.py` | Reglas de la estrategia de impulso |
| `agente/resumen.py` | Resumen diario y revisión semanal |
| `agente/noticias.py` | Titulares de Alpaca para la selección |
| `agente/backtest_momentum.py` | Backtest intradía de la estrategia de impulso |
| `agente/analista.py` | La llamada a Claude (comité de inversión) |
| `agente/disparadores.py` | Reglas gratuitas que deciden si consultar a Claude |
| `agente/fiscal.py` | Informe fiscal estimado (FIFO, euros, regla de 2 meses) |
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
