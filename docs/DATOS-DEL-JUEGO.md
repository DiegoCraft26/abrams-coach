# De dónde salen los datos: inventario verificado (2026-11-18)

Regla que manda sobre todo lo demás: **el panel solo enseña lo que se sabe con certeza en
ese instante**. Si un dato llega con 20 s de retraso, o se dice cuánto, o no se pinta. Este
documento dice qué fuente da qué, con cuánta latencia y con qué riesgo, para poder decidir
sin volver a investigarlo cada sesión.

## 1. En vivo, mientras juegas

| Fuente | Qué da | Latencia medida | Riesgo | Estado |
|---|---|---|---|---|
| **Broadcast** (`/v1/matches/{id}/live/url` + SSE) | 12 jugadores: almas, oro, KDA, héroe, ítems | **1.3 s** con URL explícita | Ninguno: es el cliente de espectador. Cuota 6/h por IP si la partida no está listada | en uso |
| **`console.log`** (`-condebug`) | Fase, match id, lobby, héroe, cuenta, cierre | ~1 s | Ninguno: es un archivo que el propio juego escribe | en uso |
| **Captura de pantalla** (KWin) | HUD: reloj, oro, inventario propio | 415–514 ms por cuadro; 2 Hz hoy | Ninguno: es tu pantalla | respaldo |
| **Memoria / inyección / hooks** | Todo | 0 | **Prohibido**: es lo que VAC castiga | no se usa |

**Lo que el `console.log` NO trae** (verificado sobre el archivo real y el binario):
almas, oro, ítems, compras. Solo fase y contexto. `grep -aic gamestate_integration` sobre
`game/bin/win64` → **0**: **Deadlock no tiene GSI** (la de CS2/Dota no existe aquí).

Consecuencia: **no hay forma legítima de tener tu inventario o tus almas al instante sin
capturar la pantalla o sin broadcast**. Cualquier overlay que prometa eso está leyendo
memoria. El nuestro no lo hace.

## 2. En masa, sin jugar (esto es lo nuevo)

La API comunitaria expone un **motor SQL sobre demos ya parseadas**:

```
POST /v1/matches/demo/query   {match_id, query, format: "ndjson"|"parquet"}
  → {job_id, status:"queued"}
GET  /v1/matches/demo/query/{job_id}
  → {status:"done", result_url:"https://demo-extracts.deadlock-api.com/<job>.ndjson.zst"}
```

Verificado hoy con dos partidas (una del 18 nov, otra del 7 nov):

| Partida | Consulta | Espera | Resultado |
|---|---|---|---|
| 139655632 (18 nov) | `SELECT tick, purchaser_player_slot, ability_id, change FROM AbilitiesChangedEvent ORDER BY tick LIMIT 15` | ~15 s | 15 filas |
| 132662221 (7 nov) | `SELECT count(*) FROM AbilitiesChangedEvent` | ~30 s | **277 eventos** |

### Qué hay dentro de una demo

`GET /v1/matches/demo/schema` devuelve **998 tablas**: entidades y eventos.

| Tabla | Qué es | Para qué sirve al motor |
|---|---|---|
| `AbilitiesChangedEvent` | `tick, purchaser_player_slot, ability_id, change` | **La compra exacta y su tick**: el orden real de build, no la lista del post-partida |
| `GoldHistoryEvent` | `tick, entindex_player, minute_records` | **Almas minuto a minuto**: permite saber si en ese momento *podía* pagar X (contrafactual de oro) |
| `DamageEvent` | 31 columnas: daño, tipo, atacante, víctima, habilidad, salud | Qué ítem hace daño de verdad y en qué momento |
| `PostMatchDetailsEvent` | Resumen final | Verdad terreno del resultado |
| `CCitadelPlayerPawn` | 326 columnas: salud, posición, habilidades | Posicionamiento y estado del héroe |

Esto es **órdenes de magnitud** más de lo que hay hoy: el corpus actual (313 324 compras de
Abrams) viene de una tabla agregada; aquí se puede reconstruir la partida compra por compra,
con oro disponible y daño.

### Límites

- **Retención**: la demo directa de la CDN (`replay*.valve.net/.../N_salt.dem.bz2`) caduca.
  La del 7 nov respondió, la de una partida más vieja devolvió **404** mientras su `.meta`
  seguía en 200. La consulta SQL va contra el archivo ya ingestado por la API, así que
  aguanta algo más; **no es infinito**.
- **Cola**: un job tarda 15–30 s; no hay documentación de paralelismo. Tratar como recurso
  escaso: 2–3 en vuelo, con reintento exponencial.
- **Cobertura**: partidas públicas. Los bots y las prácticas pueden no tener demo.

## 2.b La serie por parche (2026-11-18)

`datos/historico.db` (167 MB, se regenera con `herramientas/lab/ingesta_parches.py`):
**9 731 partidas en 20 parches** (ago-2025 → nov-2026), 114 452 jugadores y **1 841 828
compras** con `net_worth` al comprar. Sale de muestrear `match_id` de los 540 historiales
de jugadores y pedir su metadata: **el metadata trae `items[]` con `game_time_s`,
`sold_time_s` y `net_worth_at_buy`**, no solo el resumen.

Tres cosas que esto habilita y antes no:

- **Filtrar el modo sin adivinar**: `game_mode` trae `Normal` (9 151) y `StreetBrawl`
  (580, los de 8 jugadores que contaminaron `lab.db`).
- **Serie temporal**: efecto por ítem por parche y réplica entre parches.
- **Banda**: `badge` no nulo en 8 192 partidas (84 %, contra el 10 % de `lab.db`).

**Trampa que hay que conocer**: para agrupar por parche hay que usar la **fecha del
título** de `/v1/patches`, no `pub_date`: este último llega 0–35 días tarde y tres
parches de ago–oct 2026 comparten `pub_date` con 33 s de diferencia. Agrupando por
`pub_date` los cubos quedan corridos hasta 35 días.

## 3. Qué se puede afirmar y qué no

| Afirmación | ¿Se puede? |
|---|---|
| «Tu siguiente compra» | Sí: es una decisión del motor, no un dato del juego |
| «Te alcanza / faltan 680» | **No** sin almas frescas. Por eso se quitó del overlay y de la tarjeta (2026-11-18) |
| «Vas 12 % de almas abajo» | Solo con broadcast (1.3 s) o con el marcador leído; con retraso se dice la edad |
| «Este ítem vale +1.4 pp» | Sí, con su intervalo y su E-value (ver `MOTOR-V2.md`) |
| «Este build gana 54 %» | Solo declarando banda y ventana; sin MMR no se compara entre trackers |

## 4. Plan de ingesta masiva (siguiente paso)

1. **Semilla**: partidas por héroe y por parche desde `deadlock-api` (`/v1/matches/recently-fetched`,
   `/v1/players/{id}/match-history`). Objetivo inicial: 5 000 partidas, 3 héroes.
2. **Extracción**: por partida, un job con `AbilitiesChangedEvent` + `GoldHistoryEvent`
   (una sola consulta con `UNION` o dos jobs). Guardar el `ndjson.zst` crudo.
3. **Almacén**: DuckDB en la PC (`/srv/abrams/datos/demos.duckdb`). Una tabla por evento,
   con `match_id`, `parche` y `hero_id` como dimensiones.
4. **Puerta de calidad**: reconstruir una partida conocida y comparar con
   `data/replay_cache.json` (626 partidas ya parseadas). Si no coincide, no entra.
5. **Costo**: 15–30 s por partida ⇒ 5 000 partidas ≈ 21–42 h de cola. Se corre en la PC,
   por lotes, con reanudación.

Esto no mejora el panel de hoy; mejora **lo que el motor puede aprender mañana**: el
contrafactual de oro es justo lo que falta para pasar de «este ítem se asocia a ganar» a
«este ítem, con este oro y este minuto, era la compra correcta».

## 2.c El metadata trae los ítems: la nota ya no depende de la demo

`GET /v1/matches/{id}/metadata` devuelve `players[].items[]` con `game_time_s`,
`item_id`, `upgrade_id` y `sold_time_s`. Eso permite calcular el **minuto del primer
3 200** sin demo.

Validado el 2026-11-18 en cuatro partidas con demo: el minuto calculado desde el
metadata y desde la demo coincide a **0,01 min (menos de un segundo)**.

Consecuencia práctica: la nota de después de la partida sale completa aunque la demo
tarde horas o nunca llegue — que era el caso más común. La demo sigue haciendo falta
para el oro exacto y el detalle de compras, no para la regla del 3 200.

## 2.d La clave de la API: el camino para salir de la cuota

Desde el 2026-11-18 el endpoint `POST /v1/matches/demo/query` responde **429 en cadena**
cuando no hay clave: la cuota es por IP y está agotada de facto (≈1 partida por hora). El
crawler respeta `Retry-After` y reintenta, pero no puede avanzar.

La API acepta **`X-API-KEY`** (o `?api_key=`). Con clave, el límite deja de ser por IP.
El código ya la soporta sin cambiar nada más:

```bash
mkdir -p ~/.config/abrams-coach
printf '%s\n' 'TU_CLAVE' > ~/.config/abrams-coach/api_key
# o: export DEADLOCK_API_KEY=TU_CLAVE
```

`herramientas/demos/consulta.py` y `herramientas/demos/crawler.py` la leen de ahí; no está
en el repo y no debe estarlo. `abrams-coach listo` avisa si no la hay (no es un fallo, es
una mejora disponible).

**Lo que no se puede afirmar:** que con clave el ritmo suba, porque **no tenemos clave y no
se ha probado**. La documentación de la API dice que el límite por IP se levanta; el efecto
real en `demo/query` no está medido. Si alguien la consigue, el crawler la usará sin tocar
código y la primera hora de datos dirá si era eso.
