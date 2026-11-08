# deadlock-api: comportamiento medido y estrategia de descubrimiento

Medido el 2026-11-08 entre 10:52 y 10:58 (America/Monterrey, UTC-6). Base `https://api.deadlock-api.com`.
User-Agent propio `abrams-coach-investigacion/1.0` (sin UA: 403). Cuenta de prueba 32501218, IP doméstica sin API key.

## Tabla de endpoints (latencia medida hoy)

| Endpoint | Hora | Resultado | Latencia |
|---|---|---|---|
| `GET /v1/matches/active` (sin filtro) | 10:53-10:56 | 200, 150 partidas, 253 KB | 0.10-0.20 s con caché CDN (`age` 15-125), 0.32-0.36 s en MISS |
| `GET /v1/matches/active?account_ids=32501218` | 10:53 / 10:57 | 200, 1.4 KB con la partida; `[]` cuando no juega | 0.08-0.28 s HIT, 0.27-0.30 s MISS |
| `GET /v1/matches/demo/live/query` (SSE) | 10:53 | **429** cuota IP agotada | 0.27 s (rechazo) |
| `GET /v1/matches/{id}/live/url` | 10:54 | **429**, misma cuota que el SSE | 0.28 s (rechazo) |
| `GET /v1/matches/live/urls` | 10:54 | 200, 39 partidas, 23 con `lobby_id`, 5.5 KB | 0.24 s, caché 120 s |
| `GET /v1/matches/{id}/metadata` partida terminada | 10:56 | 200, 222-412 KB | 0.14-0.54 s |
| `GET /v1/matches/{id}/metadata` partida en vivo | 10:55 | **404** "Failed to fetch match salts" | 1.35 s sin `disable_steam`, 0.39 s con él |
| `GET /v1/matches/{id}/metadata` recién terminada | 10:57 | 404 → **504** → **429** (cuota Steam 3/h) | 1.07 s / 2.43 s / 0.37 s |
| `GET /v1/players/{id}/match-history?limit=1` | 10:53 | 200, 816 KB | 1.12-1.71 s |
| `GET /v1/players/{id}/ingest-status` | 10:55 | 200, 77 B, `active:false` | 0.62 s |
| `GET /v1/matches/demo/schema` | 10:55 | 200, 5.3 MB (122 rutas totales en openapi) | 0.46 s |
| `GET /v1/matches/recently-fetched` | 10:55 | 200, 1.7 MB | 0.34 s |

## Fallos observados hoy

- **Cuota de espectador por IP: 6 por 3600 s**, compartida entre `demo/live/query` y `live/url`.
  A las 10:53 respondía `{"type":"IP","quota":{"limit":6,"period":3600},"requests":10,"remaining":0,"next_request_in":2449}`
  con cabeceras `ratelimit-limit/period/remaining/reset` y `retry-after`. La cuota estaba gastada antes de mi primera llamada:
  la gasta el propio coach (un stream por partida más los reintentos). El SSE no se pudo medir hoy: **sin medir**.
- **Cuota de Steam en metadata: 3 por 3600 s** (el error 429 lo dice explícito). La ruta que toca Steam devuelve 404 (sin salts),
  504 (timeout de Steam) o 503 "Steam is busy" (visto antes; hoy no lo cacé: 504 en su lugar).
- **`disable_steam=true`** en `metadata` evita Steam: responde 404 en 0.39 s sin gastar cuota. Para partida terminada que ya está
  en ClickHouse, 200 igual.
- **Caché CDN de 120 s con `stale-while-revalidate=120`** en `matches/active` (y también con `account_ids`). Medido a las 10:57:
  la lista cacheada (`age` 117) todavía incluía 133740065; la lista fresca ya no, y el filtro por cuenta devolvía `[]`.
  Peor caso de mentira: ~240 s. Un `[]` cacheado se sirve igual de rancio: **una partida recién empezada puede tardar minutos en aparecer**.
- **Cadencia de la lista global**: refresco real cada ~120 s (ciclo de `age` 15→125, un `UPDATING` y vuelta a `age` 15).
  En un refresco cambiaron 14 partidas de 150. Sondeando cada 15 s, una partida nueva apareció entre **170 y 289 s**
  después de su `start_time` (n=17; mezcla caché de 120 s y tiempo previo en partida: sin separar).
- **Cabecera `Cache-Control: no-cache` no salta la caché** (sigue `HIT`). Param único (`&t=<epoch_ns>`) sí: MISS real, 0.27-0.32 s.
- Caps de paginación suaves: `match-history?limit=1` devuelve lo mismo que `limit=3` (816 KB) — el `limit` no recorta el cuerpo.
- `start_time` de las partidas activas es epoch de segundos y sirve para estimar retraso de descubrimiento.

## Estrategia en 3 capas

1. **HUD (match id en pantalla)**: `coach/hud.py:leer_match_id()` ya lee "MATCH: …" de la esquina inferior derecha
   (caja 4050,1330-4480,1440). Un `spectacle -f` cuesta 0.41 s y 449 KB (medido por el proyecto). Cadencia 10 s como máximo,
   y sólo mientras no haya match id por API. Es la única capa que no depende de la nube ni de la cuota.
2. **API por cuenta**: `matches/active?account_ids=<cuenta>`, barata (0.27-0.30 s, 1.4 KB). Sondeo cada 30 s, no más rápido:
   la caché es de 120 s y pedir más seguido no adelanta nada. Cada 3 sondas vacías (90 s) repetir con param único de cache-bust
   (una sola vez, 0.30 s) para distinguir "no juega" de "caché rancia".
3. **API por listado global**: `matches/active` completo (253 KB, 0.10-0.36 s) cada 30 s sólo si las capas 1 y 2 fallaron, y
   filtrando en local por las cuentas conocidas del HUD o por composición de héroes (el listado trae `hero_id` por jugador).
   `matches/live/urls` (5.5 KB, 0.24 s) como atajo: dice qué partidas tienen broadcast disponible de verdad, útil para descartar
   un match_id que nunca va a streamear.

Reglas de espera y backoff, todas sobre el reloj de pared:
- Ante 429 en `demo/live/query` o `live/url`: leer `retry-after`/`next_request_in` y **no reintentar antes de ese instante**
  (hoy: 2449 s). Nada de reintentos rápidos: cada intento cuenta contra el 6/h.
- Ante 404/503/504 en `metadata`: no cuentan como fallo de red, cuentan contra la cuota de Steam (3/h). Usar `disable_steam=true`
  para el sondeo y llamar sin él una sola vez, cuando la partida ya terminó.
- Presupuesto de streams: 6/h → un stream por partida, abierto una vez, reconectado como máximo 3 veces (5 s, 15 s, 45 s) y
  cerrado sin reabrir si el match_id cambia. Con dos partidas por hora sobra margen.

## Fin de partida, alt-tab y stream muerto

- **Detectar el final**: tick congelado 60 s (o 3 publicaciones seguidas sin tick nuevo), o que el match_id desaparezca de la lista
  fresca. Medido: tras terminar, la lista lo mantuvo hasta ~76 s extra (caché). Secuencia: cerrar el stream de inmediato (devuelve
  cuota), soltar `match_id`, volver a capa 1+2 en 15 s, y publicar estado "partida terminada" sin recomendaciones nuevas.
- **Nunca quedarse clavado al match viejo**: el id resuelto lleva marca de tiempo; si en 90 s no hubo un solo estado del stream,
  se descarta y se vuelve a descubrir. Es la regla que ya insinúa `coach/fuentes/api_vivo.py` (`ultima_senal > 90.0`) pero hoy
  convive con `_resolver_match()` llamado en cada `estado()`, que vuelve a pegar el id viejo si la caché CDN lo sigue sirviendo.
- **Alt-tab**: no rompe nada. `spectacle` captura el escritorio completo y el HUD de espectador no depende del foco, así que la capa 1
  sigue leyendo. Lo que sí cambia es que sin HUD visible (menú, escritorio) no hay MATCH que leer: ahí manda la capa 2 y, si la caché
  va rancia, la 3.
- **Stream muerto a mitad**: reconectar con 5/15/45 s; si los 3 fallan, seguir con la última tabla conocida marcada como vieja
  (no vaciar la UI) y reintentar el descubrimiento completo, no la misma URL. Si el 429 aparece, se acabó el presupuesto: pasar el
  resto de la hora a HUD, que no gasta cuota.

## Endpoints que dan más de lo que la app usa

- `CCitadelGameRulesProxy` (en `demo/schema`): `m_pGameRules__m_bGamePaused`, `m_nPauseStartTick`, `m_nTotalPausedTicks`,
  `m_pGameRules__m_iWinningTeam`, `m_flGameStartTime`, `m_pGameRules__m_nAmberGold`/`m_nSapphireGold`,
  `m_pGameRules__m_iMidbossKillCount`, `m_pGameRules__m_tNextMidBossSpawnTime`. Hoy nada de esto se consulta: la app no sabe
  si la partida está en pausa ni cuándo sale el mid boss.
- `CCitadelTeam`: `m_nBossesAlive`, `m_nBossesMax`, `m_flBaseObjectiveHealth`, `m_nFlexSlotsUnlocked` → objetivos sin OCR.
- `CCitadelPlayerController`: `m_PlayerDataGlobal__m_iObjectiveDamage`, `m_bAlive`, `m_flRespawnTime`, `m_iCreepGold*`,
  `m_vecAbilityUpgradeState__m_ItemID`. Además el broadcast ya trae `m_vecUpgrades` de los 12 jugadores, pero
  `api_vivo._traducir()` sólo conserva los ítems de `yo` y descarta los de aliados y enemigos: **el inventario enemigo ya viene, se tira**.
- Sin usar en absoluto: `matches/live/urls`, `matches/{id}/live/url`, `matches/recently-fetched`, `players/{id}/ingest-status`,
  `matches/demo/schema`, `v1/sql`, `matches/active/raw`.
- Sobra en el código actual: la escalera `[0.5, 1, 2]` de `api_vivo._backoffs()` duplicada en `_resolver_match()` y en `estado()`,
  y el sondeo de cuenta en cada vuelta. Con un descubrimiento único cada 30 s y un `retry-after` respetado se borra casi todo eso.
