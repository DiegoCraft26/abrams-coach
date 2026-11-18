# La partida en vivo sin visión: qué se midió el 2026-11-09

Pregunta de Diego: *«¿hay un fix permanente para tener más información con solo código, sin
escanear y adivinar con visión?»*

Respuesta corta: **sí, para casi todo.** Existe un camino HTTP que devuelve, por jugador,
almas, oro, KDA, héroe, equipo e ítems en **1.3 s**, sin capturar un píxel. Lo único que
queda en duda es si ese camino cubre *tu propia* partida normal, y eso se comprueba en la
siguiente ranked con un comando.

## Lo que se creía y lo que hay

| Creencia | Dato medido (2026-11-09) |
|---|---|
| «Una ranked normal no tiene broadcast» | La lista `GET /v1/matches/live/urls` tenía **83 partidas en vivo y 65 fuera del top 200** del watch tab. El broadcast existe; lo limitado es el escaparate. |
| «El watch tab es un permiso» | `GET /v1/matches/active` es un **catálogo** (top 200). El permiso se pide por id: `GET /v1/matches/{match_id}/live/url`. |
| «Leer en vivo cuesta 6/h y es lento» | El espectáculo cuesta 1 de 6/h **por partida y hora** (queda cacheado). Con la URL en mano, las consultas son otro endpoint: **20 req/min**, sin tocar esa cuota. |
| «La latencia es 20-25 s» | Con `broadcast_url` explícita: **1.32-1.36 s** hasta las 12 filas de jugador. |

## La cadena completa

```
match id  ──►  URL del TV  ──►  SSE con SQL  ──►  estado del motor
```

1. **match id**: `console.log` del juego (gratis, sin red), o
   `GET /v1/matches/active?account_id=<cuenta>`, o `--match`.
2. **URL del TV**: `GET /v1/matches/{id}/live/url` → `http://dist*-*.steamcontent.com/tv/<match>_<salt>`.
   En caché responde en **0.34 s**.
3. **SQL en streaming**: `GET /v1/matches/demo/live/query?broadcast_url=...&query=...`.
   Las columnas de `CCitadelPlayerController` llegan con sus nombres crudos, así que el
   parser de siempre (`en_vivo.interpretar`) las entiende sin traducción.
4. **Reloj**: `tick / 64`. Verificado: tick 64236 → 1003.7 s.

### Ejemplo real (partida 134651996, 2026-11-09 20:29)

```
estado en 1.36 s · reloj 1025 s (tick 65580) · 12 jugadores

eq héroe            almas    oro     K/D/A ítems
 3 Seven            18675   1075     2/3/5     8
 2 Holliday         18356   2356     6/3/5     9
 3 Abrams           14035    435     7/2/2     8
...
```

Eso es exactamente lo que el camino de píxeles intentaba sacar: reloj, almas por jugador,
oro, ítems y enemigos. Aquí sale de un `SELECT`.

## Lo que queda por comprobar (una sola cosa)

El endpoint especta una partida **por su id**, sin mirar el watch tab (probado con ids
fuera del top 200: devolvió URL). Lo que no se ha podido probar sin jugar es que devuelva
URL para **tu** partida en el instante en que la juegas. Si la devuelve, la visión deja de
ser necesaria para el coach y queda solo como respaldo.

Comando para el próximo arranque de ranked:

```bash
python3 herramientas/probar_vivo.py
```

- Sale la tabla de 12 jugadores → el camino funciona para partidas propias.
- Sale `k_eNotInGame` con la partida en curso → ese id no es espectable; se sigue con el
  plan B (HUD) y se anota en `salida/telemetria.jsonl`.

No hace falta lanzarlo a mano: desde esta tanda, cada vez que el coach descubre una
partida deja una línea `api_url` en la telemetría (con `rechazo` y motivo si falla) y el
barrido queda registrado. El comando existe para verlo en el momento.

Y desde el 2026-11-09 la batería de pruebas escribe en un temporal, así que esas líneas
del registro son de partidas de verdad y de nadie más (antes se colaban «match 111» y
«k_eNotInGame» de los tests: 15 líneas borradas).


## Estabilidad medida (barrido de 190 s sobre una partida real)

20 fotos cada 10 s contra la partida 134651996, 2026-11-09 20:30-20:33:

| Métrica | Valor |
|---|---|
| Fotos con las 12 filas | **20/20** |
| Tiempo por foto | 0.83-1.13 s (mediana ~1.0 s) |
| Reloj al empezar / terminar | 1297.7 s / 1486.7 s |
| Tick al empezar / terminar | 83 052 / 95 148 |
| Diferencia de tick | 12 096 ticks en 190 s → **63.7 ticks/s** (nominal 64) |
| Ítems contados por foto | 112 → 117 mientras la partida avanzaba |

Que el tick avance a 63.7/s significa que el reloj de la API sigue el reloj del juego:
no es una estimación, es el mismo contador.

## Cómo quedó integrado en el coach

`run.py` (modo `--fuente vivo`): al descubrir la partida pide la URL con
`live_api.url_broadcast(match)` —una vez por partida, cacheada 1 h— y se la pasa a
`en_vivo.Escucha(..., url_tv=...)`. Con URL, `_url()` manda `broadcast_url` y **no**
manda `match_id`: no especta, no gasta los 6/h, y reconectar sale gratis.

Comprobado con el componente real (no con el prototipo): `Escucha(..., url_tv=...)`
publicó **18 estados en 3 s** con 12 jugadores y `error: None`.

Si la URL no se consigue, `url_tv` queda en `None` y todo sigue como antes (consulta por
id, gastando cuota). El camino de píxeles sigue ahí como respaldo, sin cambios.

## Corrección del 2026-11-18: sin URL no se abre nada

Lo de arriba («todo sigue como antes») resultó ser el agujero. Medido en producción:

- Un **504 de Cloudflare** tumbó `live/url` a las 01:17:46. `url_tv` quedó en `None` y
  `run.py` abrió `Escucha` **por `match_id`**.
- El openapi lo dice explícito: `Spectating a match_id without API key: 6req/h` por IP.
  O sea: **abrir por `match_id` especta**; abrir con `broadcast_url` no.
- La escalera de reconexión (5/15/45 s) se aplicó también a esos fallos: **cinco
  aperturas en ~65 s**. El 429 de las 02:06:26 lo confirma: `"type":"IP",
  "quota":{"limit":6,"period":3600},"requests":6,"remaining":0,"next_request_in":672`.
- Como la URL nunca se cacheó, cada expiración de la pausa volvía a intentar por id y
  volvía a comer cuota. Panel muerto más de una hora por un 504 de cinco minutos.

Reglas nuevas, todas con prueba en `tests/test_live_api.py`:

1. **El escaparate primero.** `url_broadcast` mira `/v1/matches/live/urls` (gratis, 100
   req/s, caché 120 s) antes de llamar a `live/url`. Lo listado no cuesta nada; medido
   el 2026-11-18: 39 partidas listadas, 23 con URL.
2. **Sin URL no hay stream.** `run.py` no crea `Escucha` con `url_tv=None`: publica el
   motivo, sigue con HUD y `console.log` (gratis) y reintenta la URL cada 60 s.
3. **Sin URL no hay escalera.** Aunque alguien cree `Escucha` sin URL, `_espera()`
   devuelve 300 s desde el primer reintento (`ESPERA_SIN_URL_S`).
4. **La caché de URL sí se escribe.** `_guardar_cache_url()` estaba definido y no se
   llamaba nunca: el archivo `~/.cache/abrams-coach/urls_broadcast.json` no existía, así
   que cada reinicio del coach volvía a espectar.
5. **El 429 deja rastro.** Se anota `api_429` con `type`, `limit`, `period`, `usadas` y
   `espera`, y cada apertura de stream anota `api_sse` con `especta` sí/no. Antes no
   había forma de saber si la cuota la gastamos nosotros o es la global de la API.
6. **Una partida, un intento.** Si `live/url` responde 429, esa partida queda marcada en
   `_sin_cuota` y no se vuelve a pedir mientras viva el id: cada intento suma otra
   petición a la ventana. Medido: reintentando cada minuto, `requests` fue 6 → 9 → 12 y
   `next_request_in` pasó de 672 a 2336 s. Insistir no acerca la recuperación, la aleja.
7. **La pausa sobrevive a un reinicio.** `~/.cache/abrams-coach/cuota_pausa.json` guarda
   `{"hasta": epoch}`; al arrancar se relee. Sin eso, cada reinicio del coach durante un
   429 gastaba otra petición en el arranque y la ventana nunca drenaba.

### Lo que dice la API de sí misma (openapi, 2026-11-18)

- `demo/live/query` con `match_id` **especta** (6/h por IP sin clave); con
  `broadcast_url` solo cuenta el límite de 20 consultas/min.
- Load shedding: si una consulta no cacheada excede el tiempo, responde **504** y «la
  misma petición falla al instante durante unos minutos» — por eso el 504 de las 01:19
  se repetía en 0.26 s y `matches/active?account_ids` seguía fallando en cada reintento.
- Con clave (`X-API-KEY`) el espectáculo deja de tener límite por IP.



## GSI y console.log, revisados hoy

| Fuente | Estado 2026-11-09 |
|---|---|
| GSI de Source 2 | **Sigue sin existir**: `grep -aic gamestate_integration` sobre todos los binarios de `game/bin/win64` → **0 coincidencias** |
| `console.log` del juego | Sirve para **fase, match id, lobby, héroe y cuenta** (`ChangeGameState`, `Lobby N for Match M`, `models/heroes/<héroe>/`). No trae almas, oro ni ítems: 0 coincidencias de `soul`, `gold`, `buy`, `purchase`; los `item` son resúmenes de `vprof` |
| Cvar que escriba archivo | El único es `-condebug` (lo que genera ese `console.log`). No hay cvar de estado por jugador escribiendo a disco |

Conclusión: el único camino que da almas y ítems sin píxeles es el broadcast. `console.log`
se queda para lo que ya hace bien (saber si hay partida y cuál, sin gastar red).

## Límites y riesgos

| Tema | Estado |
|---|---|
| Cuota sin API key | 6 espectáculos/h por IP (solo cuando la partida no está en `/live/urls`; una vez por partida y cacheada 1 h) + 20 consultas/min por stream |
| Dependencia | `deadlock-api.com`, servicio comunitario (MIT). Si cae, el coach vuelve a píxeles |
| Legalidad | Es la misma vía que el cliente de espectador; no lee memoria, ni archivos del juego, ni red |
| Datos que NO da | posiciones y daño en tiempo real (sí están en el esquema, pero no se usan), y nada de lo que pase fuera de la partida |

## Piezas

| Qué | Dónde |
|---|---|
| Fuente nueva | `coach/fuentes/live_api.py` |
| Pruebas (19 comprobaciones, sin red) | `tests/test_live_api.py` |
| Comando de comprobación | `herramientas/probar_vivo.py` |
