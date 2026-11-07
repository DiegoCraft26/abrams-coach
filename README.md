# Abrams Coach

Panel de decisiones para Deadlock, solo héroe **Abrams**, en el monitor secundario.
Lee la partida por pantalla, cruza con 1.9 millones de partidas reales y dice qué comprar,
qué vender y si toca farmear o pelear.

## Estado

| Pieza | Estado |
|---|---|
| Minería de datos (deadlock-api) | funcionando, datos descargados |
| Base de conocimiento (120 ítems, 400 pares, 43 matchups) | funcionando |
| Motor de decisión | funcionando, **1–3 ms** por consulta |
| Panel web (SSE) | rediseñado: sistema de diseño, inventario abajo, tendencia de almas, estados claros |
| Puerta de calidad automatizada | `verificar_ui.py` + 3 suites de pruebas |
| Grafo de compras (fases + aristas) | funcionando: 558 nodos, 29,239 transiciones |
| Ítems de apertura | funcionando: solo abre con ítems de apertura reales |
| Filtro de estabilidad | funcionando: detecta reloj que retrocede, saltos imposibles, se congela |
| Detección de iconos | 100% en pruebas sintéticas con recorte exacto, 85% con icono al 70% |
| Lectura del marcador (12 almas + reloj) | **funcionando sobre captura real: 12/12 almas, reloj exacto** (2026-11-07) |
| Estado en vivo sin OCR (almas por jugador) | **funcionando y verificado** contra partidas reales (2026-11-07) |
| Registro de decisiones | funcionando |

## Estado en vivo (2026-11-07)

Hay tres fuentes de partida, y cada una está medida:

| Modo | Qué da | Coste |
|---|---|---|
| `--fuente vivo` | tiempo, almas por jugador, héroe, equipo y KDA **sin OCR** | 0 VRAM, ~KB de RAM, latencia ~20-25 s |
| `--fuente ocr` | tiempo y las 12 almas leídas de la pantalla | ~650 ms por lectura, 0 VRAM |
| `--fuente simulado` | demo sin juego, para ver el panel | despreciable |

```bash
python3 run.py --fuente vivo                 # busca tu partida por cuenta Steam
python3 run.py --fuente vivo --match 123456  # partida concreta (ver a cualquiera)
python3 run.py --fuente ocr --mi-columna 5   # columna aliada que eres tú
python3 run.py --fuente ocr --imagen salida/calibracion/marcador_real_juego.png  # probar sin juego
```

El modo `vivo` saca el estado del broadcast de espectador de Valve vía `deadlock-api`:
no lee memoria del juego, no inyecta y no hookea. Ver `coach/en_vivo.py`.

**Qué necesita Diego para cerrar lo que falta:**

1. Una captura del marcador de **otra partida** (para cumplir "≥2 capturas reales").
2. Una captura de **partida normal** sin Testing Tools (para ubicar el contador de almas
   propias del HUD; hoy se resuelve por la API en vivo o con `--mi-columna`).


## Arranque

```bash
cd .
./arrancar.sh simulado      # demo sin juego, para ver el panel
./arrancar.sh ocr           # lectura real de pantalla
./parar.sh
```

Panel: **http://127.0.0.1:8090**

Para el segundo monitor: abre esa URL en Brave y pon la ventana en la mitad derecha del
monitor secundario. El panel está pensado para ~960 px de ancho.

## Cómo se construyeron los datos

```bash
python3 mineria.py                 # descarga base: partidas, ítems, pares, builds
python3 -m coach.catalogo          # catálogo normalizado de 250 ítems
python3 -m coach.conocimiento      # base de conocimiento (usa caché)
python3 -m coach.iconos            # 245 iconos de ítems + 62 retratos
```

Fuente única: `api.deadlock-api.com`, sin clave. Datos del ciclo actual:
**1,945,004 partidas de Abrams**, winrate base 49.19%, 44 héroes enemigos con estadística
por ítem.

## El motor, en una frase

Ordena los ítems por **lift residual**: cuánto rinde un ítem por encima de lo que predice
su minuto típico de compra. Así se quita el sesgo de "los ítems caros los compra quien ya
va ganando", que es el error de todas las webs de estadísticas.

```
score = 1.00 · lift residual (pp)
      + 0.75 · delta del matchup contra la composición enemiga
      + 0.40 · encaje con el minuto actual
      + 0.20 · premio por no gastarte todas las almas
      + 0.50 · combo con un ítem que ya llevas
```

Filtros duros antes de puntuar: te alcanza, hay slot libre, no lo tienes, no es trampa
(lift residual por debajo de −1 pp), y tiene muestra suficiente.

### Apertura (primeros 10 minutos)

No recomienda cualquier ítem barato: solo los que en datos reales son apertura de Abrams
(Restorative Shot, Melee Lifesteal, Close Quarters, Extra Stamina, Rebuttal), con su
winrate ajustado y su muestra.

### Pathing

`item-flow-stats` da el grafo real de compras: **558 nodos y 29,239 transiciones** entre
ítems, con winrate ajustado por fase y almas medias al comprar. El motor lo usa de dos
formas: premia ítems que se compran en la fase actual, y muestra los 2 ítems que suelen
venir después del recomendado.

### Estabilidad y errores de lectura

`coach/estabilizador.py` detecta y frena:

- reloj que retrocede o que no avanza en 4 lecturas seguidas
- saltos de almas mayores a 12,000 entre lecturas
- almas negativas o tiempo fuera de rango

Cuando pasa, la lectura se marca como dudosa, la confianza baja a 35% y **se mantiene la
última recomendación buena** en vez de saltar a una decisión con datos rotos. Además hay
histéresis: la recomendación no cambia hasta repetirse 2 lecturas o superar a la anterior
por 0.8 puntos.

### Estados

Solo tres, y solo a partir del minuto 10:

- **FARM** — vas ≥10% atrás en almas: farmea hasta un objetivo que el panel calcula.
- **PELEAR** — vas ≥10% arriba: busca pelea y objetivos.
- **EQUILIBRIO** — diferencia menor al 10%: sigue el ritmo, no fuerces.

No compara líneas ni rivales concretos: usa la media de almas enemiga. Así no falla cuando
el equipo enemigo rota y el marcador ya no coincide con la línea.

### Venta

En Deadlock todo ítem se vende por su valor completo, así que la regla no es "¿puedo?"
sino "¿mejoro?". Solo propone vender si:

1. el ítem que entra supera al que sale por **≥2 pp**,
2. el que sale se vende de verdad en partidas reales (≥40% de las veces),
3. ya pasó su minuto típico de venta (dato real de `avg_sell_time_relative`).

Ejemplo real del motor:
`Slowing Bullets supera a Rapid Rounds por +13.0pp y Rapid Rounds se vende en 75% de las partidas`

## Calibrar con el juego abierto

```bash
python3 calibrar.py
```

Regiones en `config/regiones.json` (fracciones de pantalla, 0–1): `tiempo`, `almas`,
`retrato`, `mis_items` (barra del HUD con tus 12 slots), `scoreboard`.

Guarda `salida/captura.png`, intenta leer tiempo y almas, y genera
`salida/rejilla-scoreboard.png` con la rejilla encima del marcador. Si la rejilla no cae
donde debe, ajusta `config/regiones.json` (fracciones 0–1 de la pantalla, no píxeles).
Después vuelve a correr `calibrar.py` hasta que las celdas coincidan con los iconos.

## Pruebas

```bash
python3 tests/test_motor.py        # decisiones, filtros, estado táctico, latencia
python3 tests/test_robustez.py     # basura de entrada: nunca se cae
python3 tests/test_deteccion.py    # precisión de reconocimiento de iconos
```

## Registro

Cada recomendación se anota en `salida/decisiones.jsonl` con tiempo, almas, estado y
los ítems sugeridos. Es la base para comparar después qué recomendó la app contra lo que
compraste y contra el resultado.

## Fuente de imagen

`--captura auto|bufer|spectacle`:

- `bufer`: reutiliza `~/.dsh/state/ultima.png` (servicio `dsh-buffer-pantalla`) si está
  fresco. **Su intervalo es de 12 s**, así que sirve como respaldo barato, no como fuente
  principal para un coach en vivo.
- `spectacle`: captura propia, la fuente real del coach.
- `auto`: usa lo más fresco de los dos.

## Composición enemiga

Se lee la columna de retratos del marcador (10 filas), las 5 primeras son enemigos y las
5 siguientes aliados. Los nombres entran al scoring por matchup: el motor cambia la
recomendación según contra quién juegas.

## Competencia (revisado 2026-11-06)

Hay al menos tres apps que hacen algo parecido, así que no es tierra virgen:

| App | Qué hace | En qué nos diferenciamos |
|---|---|---|
| [Deadlock Signal](https://overwolf.com/app/deadlock_signal-deadlock_signal) | builds en orden de compra y skill order, overlay Overwolf | ellos son overlay dentro del juego; nosotros monitor 2, sin inyección |
| [Soulbound](https://www.overwolf.com/app/jackalope_digital-soulbound) | overlay discreto, scout de lobby, counter pick, top ítems por winrate | su ranking es winrate crudo, que demostramos sesgado por el minuto de compra |
| [Item Assistant](https://deadlocktrade.gg/mods/item-assistant) | overlay en la tienda: qué comprar, cuándo y contra el equipo enemigo | no pudimos abrir su página para verificar su lógica; no afirmamos ventaja aquí |

Nuestra ventaja verificable: lift residual, grafo de compras por fase, plan de 2 compras
siguientes, filtro de estabilidad con detección de lecturas rotas, y registro de decisiones
para medir después.

## Validación

Ver [VALIDACION.md](VALIDACION.md). Resumen: el lift residual predice ganar
(+0.48 pp de diferencia entre ganadores y perdedores, p = 0.0015, n = 113 partidas) y la
app elige un ítem de mayor residual que el jugador en 88% de las compras (+2.29 pp).
Imitar la compra exacta del jugador da 0%: esa métrica mide popularidad, no calidad.

## Limitaciones conocidas

- La lectura de ítems del marcador necesita calibración: depende del HUD y la resolución.
- El scoreboard solo se ve con Tab abierto; si está cerrado el panel lo dice y sigue
  recomendando con el resto de la información.
- Los ítems de aliados todavía no entran en el cálculo (solo enemigos).
- El tiempo de partida se lee del reloj del HUD; si el HUD lo oculta, la app avisa.
- Los combos de 3 ítems no se pudieron bajar (el endpoint devolvía 504).

## Riesgos que se respetan por diseño

- Solo captura de pantalla del escritorio, igual que OBS.
- Cero lectura de memoria, cero inyección, cero hooks al proceso del juego.
- Nada se dibuja encima del juego: el panel vive en el otro monitor.
