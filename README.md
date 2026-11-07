# Abrams Coach

Panel de decisiones para Deadlock, solo héroe **Abrams**, pensado para el monitor
secundario. Lee la partida por pantalla y por el broadcast de Valve, cruza con 1.9 millones
de partidas reales y dice qué comprar, qué vender y si toca farmear o pelear. Incluye un
**copiloto** que explica lo que el panel muestra y busca fuera de la base cuando hace falta.

No toca el juego: solo captura de pantalla del escritorio y APIs públicas. Cero lectura de
memoria, cero inyección, cero hooks. El anti-cheat está activo y la cuenta es de Diego.

## Estado (2026-11-07, sesión de 9 h)

| Pieza | Estado | Número que lo respalda |
|---|---|---|
| UI nativa GTK4 responsive | **funcionando** | 4 tamaños sin recortes (960×1080, 1280×720, 1920×1080, 800×600), 127.5 MB, 0.2 % CPU |
| Motor de decisión | funcionando | 4.5 ms medio, 8.6 ms máx (200 partidas, 2,156 estados) |
| Modo en vivo (broadcast) | funcionando | latencia 20–25 s, se muestra como *datos de hace N s* |
| Persistencia SQLite | **funcionando** | 1,936 muestras, 5,289 recomendaciones, 5 videos archivados |
| Copiloto DS 4.1 Flash | **funcionando** | 5 preguntas de muestra respondidas con estado real; 6 llamadas/min |
| Patrones de motor nuevos | **medidos** | diversidad 15 → 19 ítems distintos, residual +0.0552 pp |
| Tests | **en verde** | `pytest -q` → 25 tests, 0 fallos |
| Invariantes del motor | **en verde** | 6/6, 0 violaciones |

## Arranque

```bash
cd .

# panel con datos de demostración (sin juego)
./arrancar.sh simulado          # o: python3 run.py --fuente simulado
python3 panel_nativo.py         # ventana GTK4 contra http://127.0.0.1:8090

# partida real
./herramientas/partida.sh prep  # apaga lo que roba VRAM, abre coach y panel
./herramientas/partida.sh grabar
./herramientas/partida.sh cortar
./herramientas/partida.sh fin   # cierra y archiva en datos/coach.db
```

Atajos del panel: `1` recomendación · `2` enemigos · `3` compras · `c` copiloto · `?` ayuda
· `Esc` cerrar. La ventana recuerda tamaño y posición en `~/.config/abrams-coach/ui.json`.

## Arquitectura

```
abrams-coach/
  run.py                  CLI y cableado: arma el motor, el servidor y el copiloto
  panel_nativo.py         punto de entrada del panel (delega todo en coach/ui/)
  coach/
    dominio.py            dataclasses tipadas: Jugador, Item, Recomendacion, Partida…
    bus.py                bus de estado con suscriptores (la UI no conoce las fuentes)
    config.py             carga y valida config/coach.yaml; valores por defecto seguros
    estado.py             estado de partida (compatibilidad con el motor histórico)
    motor.py              decisión: compra, venta, farm/pelear + scoring
    motor_api.py          puente: dict -> Estado -> recomendación
    decision/
      patrones.py         hitos de almas del build, economía por evento, objetivos
      situacionales.py    ítems situacionales con fuente y fecha
      explicador.py       las razones que ve el jugador (nunca vacías)
    fuentes/
      base.py             interfaz FuenteDatos
      api_vivo.py         broadcast de Valve vía deadlock-api (SSE)
      hud_ocr.py          reloj y oro del HUD por captura + OCR, con validación
      simulador.py        demo sin juego
      compuesto.py        regla de precedencia y estado honesto
    agente/
      proveedor.py        OpenAI-compatible (Command Code → Hugging Face)
      presupuesto.py      límites por minuto/sesión + caché
      herramientas.py     estado_actual, explicar, historial, api_query, buscar_web
      copiloto.py         bucle de herramientas, log en SQLite
    persistencia/
      db.py               SQLite con WAL y migraciones idempotentes
      repos.py            guardar/consultar partidas, muestras, compras, videos, agente
    ui/
      app.py              ventana, breakpoints, sondeo a /api/estado, atajos
      tema.css            sistema de diseño (colores, tipografía, tarjetas)
      preferencias.py     memoria de tamaño y posición
      iconos.py           caché de iconos (antes se releían del disco cada segundo)
      componentes/        cabecera, recomendación, enemigos, compras, plan, inventario,
                          tendencia, ventas, equipo, contra-composición, copiloto, pie
    servidor.py           HTTP + SSE en 127.0.0.1:8090, /api/copiloto
  herramientas/
    partida.sh            prep/grabar/cortar/estado/resumen/archivar/seguir/fin
    archivar.py           importa salida/*.jsonl y videos a SQLite (idempotente)
    capturar_ui.py        capturas a tamaños exactos, sin depender del compositor
    evaluar_motor.py      A/B del motor sobre 626 partidas reales
    escenarios_motor.py   escenarios que el replay no puede medir (comeback)
    monitor.py            muestreo periódico a salida/monitor-<match>.jsonl
  config/coach.yaml       pesos del motor, UI, fuentes, agente y banderas
  datos/coach.db          base de datos local (no se versiona)
  capturas/               capturas de la UI (4 tamaños + antes/después)
  informes/               investigación, evaluaciones y este informe de sesión
```

### Reglas de diseño que se respetan

- **Interfaces explícitas**: `FuenteDatos`, repositorios y `ProveedorLLM`. Los dicts crudos
  no cruzan capas nuevas (`coach/dominio.py` para lo tipado).
- **Un bus de estado**: `coach/bus.py`; el servidor publica y la UI solo consume HTTP, así
  que no sabe si detrás hay broadcast, OCR o demo.
- **Configuración con defaults y validación**: `config/coach.yaml`. Un YAML roto no impide
  arrancar: se usan los valores por defecto y se anota el aviso.
- **Banderas para lo nuevo** (`flags` en `config/coach.yaml`): `patrones_nuevos`,
  `copiloto`, `hud_ocr`, `archivado_auto`, `interfaz_responsive`. Todo se puede apagar sin
  tocar código.

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
      + 1.20 · probabilidad de ser la compra siguiente
      + 0.45 · balance de slots (rellenar el más flojo)
      + contexto de composición (0–4 puntos, con fuente)
      − 0.30 · gastarte lo que te faltaba para el hito de build
      − 0.90 · ítem caro cuando vas atrás
```

### Fase económica y power spikes (nuevo, 2026-11-07)

El motor compara tus almas con el build de referencia de Abrams (7.6k a los 10 min y 25.5k
a los 25, Blitz.gg 2026-10-31) y con los hitos por coste total (Early 8,000 · Mid 13,600 ·
Late 22,400, deadlocked.gg 2026-10-30). Eso alimenta tres cosas: la etiqueta de fase, el
castigo por gastar de más justo antes de un hito y el texto que dice cuántas almas faltan.

### Situacionales y contra-composición (nuevo)

Los ítems situacionales (anti-curación, anti-spirit, anti-control, anti-movilidad) se
listan en **CONTRA SU COMPOSICIÓN**, fuera del ranking, con su fuente y con el aviso de que
sus datos de residual son negativos (los compra quien va perdiendo). No se cuelan en la
recomendación principal salvo que los datos de matchup del proyecto también los apoyen.

### Venta

En Deadlock todo ítem se vende por su valor completo, así que la regla no es "¿puedo?"
sino "¿mejoro?". Solo propone vender si el ítem que entra supera al que sale por ≥2 pp, el
que sale se vende de verdad (≥40 % de las partidas) y ya pasó su minuto típico de venta.

## Copiloto

`POST /api/copiloto {"pregunta": "..."}` con el estado vivo. Cadena de proveedores:
`commandcode` (DeepSeek V4.1 Flash) → `huggingface` → **Qwen 3.5-9B local** (gratis, solo
si `llama-server` está arriba; responde sin herramientas y con el razonamiento apagado,
medido en 1.5 s). Las claves se leen de
`~/.dsh/.credentials.yaml` y **nunca** se imprimen ni se escriben en el repo.

- Herramientas: `estado_actual`, `explicar_recomendacion`, `historial`, `api_query` (lista
  blanca de endpoints), `buscar_web` (Tavily, devuelve URL y extracto).
- Guardrails: 6 llamadas/minuto, 120 por sesión, caché de 300 s, timeout de 45 s por
  llamada y 75 s por pregunta, log en `agente_log`. En partida es **solo lectura**.
- Verificado con 5 preguntas reales; ver `informes/copiloto-muestras.md`.

## Datos

**1,945,004 partidas de Abrams**, winrate base 49.19 %, 153 ítems con datos, 400 pares,
43 matchups, 558 nodos y 29,239 transiciones en el grafo de compras.

Base local (`datos/coach.db`, SQLite con WAL):

```bash
sqlite3 datos/coach.db ".tables"
sqlite3 datos/coach.db "select match_id, duracion_s, resultado from partidas order by inicio desc limit 5;"
sqlite3 datos/coach.db "select item, count(*) n from recomendaciones group by item order by n desc limit 10;"
sqlite3 datos/coach.db "select * from videos;"
./herramientas/partida.sh archivar        # reimporta salida/*.jsonl (idempotente)
```

## Rutas de modelo verificadas (2026-11-07)

| Ruta | Estado | Nota |
|---|---|---|
| `commandcode` (DS 4.1 Flash) | **funciona** | exige cabecera `User-Agent` o devuelve 403 |
| `huggingface` | funciona | respaldo de texto |
| `opencode-go` (beam/iceman/crouton free) | **funciona** | se usó para subagentes gratis |
| `local-llama` (Qwen 3.5-9B) | funciona por HTTP | **no** admite `tools` ni dos mensajes de sistema; hay que apagarle el razonamiento |
| `groq`, `gemini`, `openrouter` | fallaron como subagente | reintentar antes de confiar en ellos |

## Pruebas y puertas de calidad

```bash
python3 -m py_compile run.py panel_nativo.py coach/*.py coach/*/*.py
PYTHONPATH=$HOME/.dsh/bin/pylib python3 -m pytest -q       # 25 tests
python3 tests/test_invariantes.py                          # 6/6 invariantes
python3 herramientas/evaluar_motor.py --partidas 200        # A/B del motor
python3 herramientas/escenarios_motor.py                   # escenarios sintéticos
python3 herramientas/capturar_ui.py                        # 4 capturas + gate de pintado
```

## Limitaciones conocidas (sin adornos)

- La latencia del broadcast (20–25 s, más con pausas) **se muestra**, no se disimula.
- El OCR del HUD sigue siendo frágil: el reloj funciona, el oro se valida contra el
  broadcast y se descarta si difiere >30 %. El fallback de solo-HUD sigue apagado.
- Los ítems del enemigo solo se ven cuando el broadcast los manda; no hay build completo.
- El copiloto no lee el build rival: lo dice cuando se lo preguntan.
- La prueba de escalado 125 %/150 % no se pudo hacer con capturas offscreen (GDK_SCALE no
  aplica al render); queda pendiente probarla con el escalado del monitor.
- Los FPS del juego no se midieron en esta sesión: no había partida abierta.

## Riesgos que se respetan por diseño

- Solo captura de pantalla del escritorio, igual que OBS.
- Cero lectura de memoria, cero inyección, cero hooks al proceso del juego.
- Nada se dibuja encima del juego: el panel vive en el otro monitor.
