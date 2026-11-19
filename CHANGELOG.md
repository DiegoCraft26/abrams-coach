# Cambios

## v1.0.5 — 2026-11-18 (noche)

**Lo que motivó esto:** una auditoría del coste del coach con la máquina en reposo, después
de notar el juego «ligeramente más laggy».

### Fuera el hilo de captura que nadie leía

`arrancar_hud` llamaba a `captura.global_()` con intervalo 0.4 s. Ese singleton capturaba
los **dos monitores** (4480×1440) 2,3 veces por segundo y el cuadro no lo consumía nadie: el
HUD usa `MarcoPerezoso` y `leer_actual()` no tiene ni una llamada. Medido: 39 ms por captura
→ **~92 ms de CPU/s (9 % de un núcleo)** más 2,3 readbacks del compositor por segundo. Con
broadcast el coach entero costaba ~13 ms/s; esto solo costaba siete veces más.

### `--intervalo` / `ABRAMS_INTERVALO` ahora manda de verdad

El OCR tenía un piso duro de 2 s (`max(2.0, 1/hz)`), así que `ABRAMS_INTERVALO=2` no cambiaba
nada aunque el comentario de `partida.sh` lo prometía. Ahora la cadencia es
`max(2 s, --intervalo)`: en un equipo justo de CPU se puede llevar a 4 s y el coste sin
broadcast baja a la mitad (312 ms de CPU por ciclo: 2 tesseract de 103 ms + PIL).

Medido en reposo: tesseract 103 ms de CPU por proceso, `hud_rapido.leer()` 144 ms de reloj /
312 ms de CPU, captura 39 ms, motor + estabilizador 7,4 ms, registro 4,5 ms, panel 0,15 ms
de firma. El panel ya estaba óptimo (repintado por firma, un timer cada 700 ms).

## v1.0.4 — 2026-11-18 (noche, tras la primera partida real)

**Lo que motivó esto:** primera partida jugada con el panel. El panel se queda como está
(Diego está acostumbrado a mirarlo en el segundo monitor), el overlay no aportó nada y el
camino se contradecía con el consejo de composición.

### El overlay es opt-in

`abrams-coach esperar` ya **no** abre la tarjeta encima del HUD: se enciende con
`esperar --overlay`. En la primera partida real el overlay no aportó nada frente al panel
del segundo monitor y encima es una superficie más que el compositor tiene que sostener
sobre el juego. `--sin-overlay` se sigue aceptando (sin efecto) para no romper guiones.

### El counter de composición entra en el camino, no en una caja aparte

La caja «CONTRA SU COMPOSICIÓN» recomendaba Spellbreaker (6 400) al minuto 0 mientras el
camino no lo pedía hasta el 25: dos consejos que se contradecían en la misma pantalla.
Ahora el counter se inserta **como un paso** del camino (uno solo, marcado `counter` en la
tira), justo después de la apertura, y la caja desaparece. Un 6 400 de composición no entra
salvo que su rival vaya ganando la partida (`amenaza`), que es el caso en el que frenar no
es composición sino la partida. `contra_composicion` se sigue publicando en el motor para
el visor.

### La tira no promete pasos que el motor no va a pedir

`construir()` filtra lo que devuelve para pintar: un 800 de apertura sin comprar sale de la
tira cuando ya pasó su ventana. Era el «Restorative Shot de cuarto ítem» reportado. La
apertura se cierra **por piezas** y no por reloj: el corte temporal a los 15 min era el que
dejaba ese hueco y además metía un escalón que cambiaba el ítem entre dos lecturas
seguidas (invariante 3 del banco).

### `ABRAMS_INTERVALO`

La lectura de pantalla cuando no hay broadcast se puede espaciar sin tocar el código:
`ABRAMS_INTERVALO=2 abrams-coach jugar`. Medido: captura 39 ms, ciclo de HUD 118 ms.

## v1.0.3 — 2026-11-18 (noche)

**Lo que motivó esto:** el laboratorio dependía de cupos que ya no hacen falta. El corpus
se llenaba partida a partida por API y el motor estaba en modo CIEGO porque el artefacto
no coincidía con la base.

### El corpus se reconstruye desde el data lake

`herramientas/lab/desde_lago.py` se attacha al catálogo DuckLake público
(`https://data.deadlock-api.com/v1/catalog.ducklake`) y lee los parquet **por HTTP con
DuckDB**: ni descargas, ni 200/h de `demo/query`, ni una petición por partida. Cero cupo.

- 15 horas de datos → **28 016 partidas, 322 846 jugadores, 5 389 319 compras** en 4 min 25 s.
- Antes: 20 500 / 235 011 / 3 868 185. Compras de Abrams: **429 332** (antes 313 324, +37 %).
- Validado contra la ingesta por API en una hora: 185.8 vs 188.7 compras por partida;
  net worth medio 14 476 vs 14 457. El `net_worth` por compra se deriva del muestreo
  `stats.net_worth` con ASOF, no de `net_worth_at_buy` (diferencia ≈ un intervalo de
  muestreo, declarada en el módulo).

### El motor deja de estar ciego

Corpus congelado de nuevo (`datos/corpus.json`) y estimador re-corrido con 200 réplicas:
**385 744 filas · 24 691 partidas · 21 ítems medidos**. `coach/valor.modo()` pasa de
`CIEGO` a **`MEDIDO`**: el artefacto ya coincide con la base.

## v1.0.2 — 2026-11-19

**Lo que motivó esto:** una respuesta del operador de la API que cambia una conclusión
que teníamos escrita al revés.

> «/v1/matches/live/urls you can call this however often you want 🙂 and for all match ids
> on there you can also make the per match call without it counting towards the rate limit»

Es decir: **el vivo con broadcast es gratis e ilimitado**. Lo que no escala es espectar una
partida que no está en el listado —tu propio ranked—, y eso no lo arregla una API key.

- `LISTA_TTL_S` 120 s → 30 s: refrescar el listado es gratis y lo que se gana es ver antes
  una partida que acaba de empezar a emitir.
- `tests/test_cuota_listado.py`: cuatro invariantes. Con URL del listado, `Escucha` no pide
  ficha (`especta=False`); sin ella, sí (`match_id=` en la consulta).
- El código no necesitó cambios de lógica: ya resolvía el escaparate antes de gastar. Faltaba
  saber que era cierto y dejarlo escrito.

## v1.0.1 — 2026-11-18 (noche, tras la 1.0)

**Lo que motivó esto:** cuatro cosas que no se veían jugando pero sí mirando el repo
desde fuera —en concreto, desde el ticket que pedía acceso a la API.

### Una sola identidad en las peticiones salientes

`coach/identidad.py`: `abrams-coach/1.0 (+https://github.com/DiegoCraft26/abrams-coach)`,
un solo string para todo. Antes había **seis variantes** —«(HUD remoto)», «(assets de
ítems)», «(analitica con presupuesto)»…— y la ruta que más pega, el watcher del live en
`ui/app.py`, iba **sin cabecera**: salía como `Python-urllib/3.x`. Para quien mira sus
registros eso no era una aplicación, eran siete clientes, uno anónimo.
`tests/test_user_agent.py` fija las cuatro invariantes, y encontró una ruta más:
`fuentes/live_api.py` construía su SSE con cabeceras de otro módulo.

### Fuera el espejo `datos/coach/`

81 módulos viejos del paquete copiados dentro de `datos/` (les faltaban `apertura.py`,
`cuota.py` y `camino_heroe.py`). Nadie los importaba, pero `grep` los devolvía como si
fueran código vivo. Archivados en `datos/coach-espejo-viejo-2026-11-18.tar.gz` (560 KB) y
borrados del árbol.

### El 429 de `demo/query` no era de la API

Diagnóstico real: `{"type":"IP","quota":{"limit":200,"period":3600},"requests":202,
"remaining":0}`. El techo es **200 peticiones por hora por IP** y cada partida gasta 2
trabajos más un sondeo cada 2-5 s por trabajo: la hora se agotaba en veinte minutos.
`CupoHorario` (170/h propias, contando sondeos) y sondeo cada 5-15 s. Aun así son ~12
partidas/hora: las 800 del Motor v3 no salen de preguntar por la API.

### MCP de deadlock-api

Registrado en DSH (`~/.dsh/cordis.patch.yml`, `mcp-deadlock`): SQL de solo lectura sobre
el data lake público, sin clave. 126 rutas en el OpenAPI, 1480 parches parquet.

## v1.0 — 2026-11-18 (noche)

**Lo que motivó esto:** cerrar el ciclo completo del jugador — antes, durante, después,
al final de la sesión — y quitar todo lo que no se sostenía con datos. No hay funciones
nuevas por novedad: cada una reemplaza una promesa que no se podía cumplir.

### El ciclo completo

| Momento | Comando | Qué da |
|---|---|---|
| Antes | `abrams-coach plan` | últimas ranked, metas, referencia de tu banda y **objetivo medible** de la sesión |
| Durante | panel, tarjeta, overlay | compra, camino, amenaza y chip de riesgo al pasar de 6 muertes |
| Al terminar | automático | nota con las reglas, la población y el histórico propio |
| Al cerrar | `abrams-coach sesion` | qué regla se te fue en la sesión, con números |

### Lo que se degradó porque los datos no lo sostenían

- **El 3 200 como meta**: 60 % vs 28,6 % en 24 demos propias, **55,1 % vs 53,0 % (p=0,20)**
  en 3 935 jugador-partida. Se informa, no se propone. `informes/lab/REGLA-3200-*.md`.
- **El ranking de ítems**: cerrado con 63 680 compras en 20 parches. Ningún ítem tiene
  efecto demostrado ni réplica; el límite es la muestra (~200 partidas de Abrams por
  parche). `informes/lab/PARCHES-MODELO-*.md`.
- **«Faltan N» y «te alcanza»**: fuera del panel, la tarjeta y el overlay (las almas
  llegan tarde). Tres pruebas fijan que no vuelvan.

### Lo que se añadió con evidencia

- **Datos por parche**: `datos/historico.db`, 9 731 partidas en 20 parches, 1,8 M de
  compras con net worth al comprar. Y la trampa documentada del `pub_date`.
- **Cuatro héroes**: Abrams (guía) + Haze, Rat King y Graves (apertura medida).
- **Fuerza por héroe y banda**: Graves 55,7 % vs Shiv 45,9 %; en la banda baja Abrams
  gana 55,2 %.
- **La nota sin demo**: el minuto del 3 200 sale del metadata, coincide a 0,01 min con
  la demo y funciona en todas las partidas.

### Windows: código que corre

`herramientas/probar_windows_wine.sh`: 10 comprobaciones bajo Wine con el Python embebido
de python.org. Overlay Win32 completo y captura GDI a **27,7 ms por cuadro** (contra
415–514 ms de KWin). Wine cazó dos fallos reales: `WNDCLASSW` no existe en
`ctypes.wintypes` y un `HWND` sin `restype` se trunca a 32 bits.

### Equipo portable

`plantillas/equipo/` + `herramientas/nuevo-equipo.sh`: contrato, estado, puertas y prompt
master en cualquier proyecto con un comando.

## v0.9 — 2026-11-18 (tarde)

**Lo que motivó esto:** el dueño pidió producto (tarjeta y overlay), datos masivos sin
capturar pantalla, y un objetivo concreto: subir de rango. El día encontró tres cosas que
cambian el proyecto más que cualquier función nueva.

### El corpus mezclaba dos modos

2 747 de las 20 500 partidas traen 8 jugadores y duran 894 s contra 2 228 s de las de 12:
no es muestra incompleta, es **otro modo**, con otra tienda (allí lo primero que compra
Abrams es Superior Cooldown). Metía 36 171 compras (11.5 %) de Abrams. Al filtrarlas, los
efectos se movían hasta 5 pp y aparecía un **+14.4 pp de Crushing Fists en la franja 0**,
que es confusión por indicación, no un hallazgo.

Consecuencia: `corpus.py` filtra a partidas completas, `valor.py` compara también filas y
partidas (no solo el hash de la base) y **el motor corre en modo CIEGO** hasta que haya un
artefacto que se sostenga. Informe: `informes/lab/CONTAMINACION-MODO-2026-11-18.md`.

### Las demos se pueden consultar por SQL

`POST /v1/matches/demo/query` corre SQL sobre las demos ya parseadas (998 tablas). Se
resolvió el mapeo (`purchaser_player_slot = entity_index − 1`; el slot del corpus es
`m_unLobbyPlayerSlot`) y el reloj con pausas (`tick − pausados`), y el piloto dio
**71/71 compras (100 % de recall)**. El oro no está en `GoldHistoryEvent` (0 filas) sino en
`CurrencyChangedEvent` con `currency_type = 0`. La retención es el límite: 5 de 12 demos
viejas dan 404. Detalle: `docs/DATOS-DEL-JUEGO.md` y `informes/lab/DEMOS-2026-11-18.md`.

### Tarjeta y overlay: solo certeza

`/tarjeta` (420×160) y `herramientas/overlay.py` (layer-shell) muestran **ítem, precio de
lista y camino**. Fuera «faltan», «te alcanza» y ETA: las almas llegan del broadcast con
20–25 s de retraso. Los tiles ya no llevan nombre (no cabía y truncaba); la cabecera baja de
22 a 16 px antes que cortar. El vigilante abre y cuida el overlay junto al coach.

### Aviso de riesgo en vivo: contexto, no predicción

`coach/motor.py` publica `riesgo` (muertes, participación, sus dos metas y el contexto con
su n) **solo** con KDA leído, reloj ≥5 min y datos de ahora; si no, `None`. El panel web lo
enseña como un chip de cabecera que aparece únicamente cuando el corte se cruza —ámbar para
muertes, rojo por encima de 8, y la participación cuando las muertes van dentro— con el
histórico en el `title`. No entra en la tarjeta ni en el overlay: ahí manda la regla de solo
dos cosas. Pruebas: `tests/test_riesgo.py`; capturas: `capturas/panel-riesgo-*.png`.

### Qué dicen los datos sobre subir de rango

- **Macro** (540 historiales): el único efecto sólido es el **pool estrecho** (0.63 vs 1.43
  héroes por 10 partidas, p=0.0001). Horario, sesión, cola, duplas, calibración y low-prio:
  nada. Y los «rápidos» empiezan una banda más abajo: parte del ascenso es margen.
- **Tu cuenta** (31 rankeadas): **38.7 % de WR**, insignia 56→55, −730; 4.9/7.8/8.9 de KDA
  y 46 935 de net worth contra 6.9/6.9/13.3 y 42 117 de los pares. Farmeas por encima de tu
  banda y peleas por debajo.
- Informe: `informes/PERSONAL-2026-11-18.md` y `informes/MACRO-QUEUE-2026-11-18.md`.

### Equipo y continuidad

`docs/EQUIPO.md` (contrato de agentes portable), `docs/ESTADO-ACTUAL.md` (estado para
retomar sin el chat) y `docs/WINDOWS.md` (diseño verificado: DXGI, overlay Win32,
PyInstaller; nada medido en Windows todavía).

## v0.8.2 — 2026-11-18

**Lo que motivó esto:** la puerta G4 — «¿el motor v2 puede reordenar la recomendación?» —
y la regla de que nada deje la app sin servir.

### G4: la medición que decide (y la que no)

Con corte temporal 60/20/20 por partida se midieron dos cosas distintas:

| Medición | Resultado | ¿Decide? |
|---|---|---|
| Valor de política (SNIPS) modelo vs popularidad | **+0.0054**, IC90 [−0.0093, +0.0216], P(>0)=0.72, ESS 2 618 de 60 665 | **No**: medio punto porcentual y el intervalo cruza cero |
| Replicación del efecto fuera de muestra | Spearman **0.796**, signo **90.5 %** (19 de 21) | **Sí**: el orden se sostiene y el signo en nueve de cada diez |

Spellbreaker y Hunter's Aura cambian de signo en partidas que el modelo no vio: esos no
pueden mandar en un empate.

**Corrección de la primera versión de esta entrada.** Publicaba «modelo 0.6522 vs
popularidad 0.5391, +11.6 pp». Estaba mal: la nuisance se ajustaba en el mismo test con el
que se evaluaba. La segunda revisión adversarial lo encontró y el número corregido es el de
la tabla. También se corrigió el mapeo de celdas de propensión (se re-rankeaban contra
test) y se añadió la exclusión de ítems ya poseídos (3.2 % de las filas recomendaban lo que
el jugador ya llevaba).

**Segunda corrección, de la revisión focalizada.** Tres defectos más, todos verificados:
la popularidad se estimaba con acciones de test (baseline ajustado en el conjunto de
evaluación: la ventaja del modelo baja de +0.0079 a +0.0054); el lookahead era un no-op
matemático — la continuación no dependía del oro restante y el parche que lo arreglaba no
se había aplicado, así que el «0 de 60 665» era real pero la explicación era falsa; y la
replicación usaba el shortlist de train en vez del conjunto de 21 ítems del artefacto.
Con los tres corregidos: el lookahead cambia 4 220 filas, la replicación sube a 0.796 y
Witchmail queda evaluada. Se añade `herramientas/lab/politicas.py`,
`marcar_oos.py` y `oos_signo` por ítem en el artefacto.

**Consecuencia en el producto:** `coach/valor.preferencia()` publica
`decision.desempate` — «el laboratorio prefiere X» — solo si la diferencia de score ya es
un empate, el ítem replicó fuera de muestra, su cota inferior supera +0.5 pp y es mejor
que la del elegido. **No se reordena**: mover la recomendación exige mover a la vez el
camino, la venta, los componentes y las alternativas. Informe: `informes/lab/G4-POLITICA.md`.

### Confiabilidad: caos

Suite completa: **361 pruebas** en verde.

`tests/test_resiliencia.py` (21 casos) rompe a propósito cada pieza: caches truncadas, JSON
basura, cupo sin permiso de escritura, artefacto del laboratorio destrozado, numpy dentro
del estado. Lo que salió:

- `json.dumps` del endpoint fallaba con un `numpy.int64` o un `set` en el estado y dejaba
  el panel en «sin coach». Ahora hay un conversor (`_json_default`) que respeta los
  números y, si aun así falla, sirve un estado honesto en vez de un 500.
- El resto ya aguantaba: se fija con pruebas para que siga aguantando.

## v0.8.1 — 2026-11-18

**Lo que motivó esto:** una revisión adversarial independiente sobre la v0.8 encontró **15
defectos** que las 326 pruebas no veían, porque comprobaban substrings y no lo que el
usuario ve. **Ninguno era P0** (el camino caliente está envuelto en try/except): todos eran
dato mal mostrado, regresiones de la poda y agujeros del cupo.

Los cuatro que más dolían:

1. **El panel decía «● en vivo» con el coach muerto.** `Sondeo` conservaba la última
   respuesta buena y la firma no cambiaba, así que el refresco salía sin repintar: cifras
   congeladas para siempre. Ahora, pasados 2× el intervalo con error, se marca `rancio`
   con la edad y la cabecera dice «datos congelados · hace N s».
2. **El freno de cuota era código muerto.** La única llamada que gasta los 6 espectáculos
   por hora es `/v1/matches/{id}/live/url` («This endpoint spectates a match», openapi) y
   no pasaba por el balde; `cuota.tomar` solo corría al abrir el SSE sin `url_tv`, cosa que
   la app nunca hace. Ahora la ficha se toma alrededor de esa llamada.
3. **El guard del sha256 era circular.** El artefacto copiaba el hash de `corpus.json` y se
   validaba contra ese mismo archivo, así que re-estimar con otra base no activaba el modo
   CIEGO. Ahora guarda el hash de la base medido al estimar.
4. **Dos clases CSS se aplicaban como una sola.** `"accion accion-espera"` y `"t11 aviso"`
   se guardaban como una clase inexistente: GTK borraba `.accion`/`.t11` y AHORRAR, VENDER y
   el «⚠ no respalda» salían sin color ni tamaño.

Arreglados además: el «faltan ~N» del panel web (leía `bolsillo.oro`; es un entero), la
apertura que se pintaba como «en vivo», TENDENCIA que nunca aparecía (clave `historial`),
CONTRA que siempre salía vacía (clave `contra_composicion`), la ficha que se devolvía
aunque el stream hubiera abierto, el reloj hacia atrás que regalaba capacidad, el fallo de
escritura del cupo que se tragaba en silencio, `valor.cargar()` que sí podía lanzar, la
firma de repintado de CONTRA incompleta y las cinco secciones inalcanzables sin el botón
«Más».

**Pruebas: 338 en verde**, incluidas las 12 de `tests/test_revision_adversarial.py`, que
comprueban clases CSS reales y estados que antes nadie miraba.

## v0.8.0 — 2026-11-18

**Lo que motivó esto (Diego):** «¿podemos hacer mejoras?», «el botón de errores y el de
más hay que quitarlos, solo lo simple», «cosas que no me permitan usar la app nunca
deberían pasar» y «el algoritmo quiero que sea una joya».

Tres frentes, ninguno cosmético.

### 1. La app ya no se queda sin servir

El fallo real: cuando no había URL del TV (un 504 del CDN, o la cuota de espectador
agotada), `run.py` publicaba `listo: false` y **se saltaba el modo pantalla**. Resultado:
panel vacío una hora con la partida en curso, aunque el HUD se estuviera leyendo.

1. **Cupo local persistido** (`coach/cuota.py`): balde de fichas en disco, 6/hora con
   ráfaga de 2. Se consulta **antes** de abrir el stream; si no hay ficha no se llama y se
   dice cuánto falta. Un 429 llega después de gastar; esto llega antes. Sobrevive al
   reinicio (era la vía por la que cada arranque metía una petición más) y devuelve la
   ficha si el fallo fue de red y no llegó al servidor.
2. **Sin broadcast se sigue con el HUD**: reloj, almas e inventario de la pantalla, con
   su nota de por qué. `abrams-coach jugar` arranca con `--pantalla`.
3. **Modos explícitos**: `SOLO_LOCAL` y `CIEGO` se ven distintos de «en vivo» en el
   panel; el pie dice de dónde viene el dato.

### 2. Panel: fuera el ruido

- Se elimina el botón **Revisar** (diagnóstico) y el toggle **Más**. El endpoint
  `/api/revisar` queda para soporte; ningún botón de la ventana lo expone.
- Las secciones **solo aparecen si tienen dato**: sin partida ya no hay ocho cajas
  vacías con «sin camino todavía».
- Panel web rediseñado al **contrato de siete zonas**: una columna de 640 px, el ítem
  como única acción dominante, precio y ETA en la misma línea, la amenaza como chip
  condicional, la evidencia con su intervalo y el inventario solo si hay una venta.
  Fuera el reloj y el oro a 22 px (el juego ya los muestra), la lista del plan, el
  roster de 12 jugadores y las tres frases libres del pie.
- «Contra su composición» pasa de cinco renglones por ítem a dos: qué es, contra quién
  y con qué respaldo. El resto, al tooltip.

### 3. Motor v2: el valor medido de una compra

| Pieza | Qué hace |
|---|---|
| `herramientas/lab/corpus.py` | 313 324 compras de Abrams, inventario reconstruido y corpus **congelado con sha256** |
| `herramientas/lab/estimador.py` | AIPW + logístico del desenlace + bootstrap agrupado por partida (200 réplicas, modelos reajustados) |
| `herramientas/lab/sintetico.py` | corpus con efecto **conocido** para saber si el estimador miente |
| `herramientas/lab/validar.py` | puertas de sesgo, cobertura y falsos positivos |
| `coach/valor.py` | lee el artefacto, valida el hash y sirve la evidencia al motor y al panel |

Corpus real (medido, no heredado): **20 500 partidas**, **313 324 compras**, WR 52.11 %,
170 ítems, un solo parche. El brief decía 5 300 partidas: la base tiene cuatro veces más y
el laboratorio estaba midiendo sobre un subconjunto.

Hallazgo que cambia la forma de medir: de 3 257 pares (franja, ítem) **solo 6** alcanzan
la muestra para detectar 2 pp; la mediana de los pares con n ≥ 30 necesita **14.9 pp**.
Por eso el efecto se agrega **por ítem**, no por celda: estratificar más no compra
precisión, la vende.

Resultado en el corpus real (efecto contra la compra alternativa, IC90):

| Ítem | Efecto | IC90 | n |
|---|---:|---|---:|
| Colossus | +3.9 pp | [2.6, 5.2] | 4 092 |
| Witchmail | +2.5 pp | [1.1, 4.0] | 3 248 |
| Phantom Strike | +2.3 pp | [1.4, 3.3] | 7 390 |
| Lifestrike | −1.6 pp | [−2.1, −1.1] | 13 642 |
| Warp Stone | −1.6 pp | [−2.6, −0.5] | 7 059 |

Con su E-value al lado: **1.36 el mejor**. Es decir, un confusor moderado —la habilidad
del jugador, que no está en la base— explicaría el hallazgo entero. El panel lo dice y no
promete winrate.

**Lo que el motor v2 NO hace todavía:** no reordena el ranking. La evidencia se adjunta a
la recomendación y el desacuerdo con la heurística se anota en telemetría
(`valor_desacuerdo`); darle la potestad de reordenar es la puerta G4, que exige comparar
los dos motores sobre partidas no vistas. Cambiar una heurística medible por otra peor
medida no es una mejora.

### Validación del estimador (corpus sintético con efecto conocido)

| Puerta | Valor | Criterio | Estado |
|---|---:|---|---|
| G1 sesgo medio con signo | +0.204 pp | \|·\| < 0.5 pp | pasa |
| G2 cobertura del IC90 | 88.5 % | 88 – 96 % | pasa |
| G3 falsos positivos | 8.1 % | no significativo vs 5 % | pasa |
| Sensibilidad a confusor de habilidad | 1.006 pp | se publica | — |

El detalle, incluidos los cuatro defectos que la validación encontró y cómo se
arreglaron, va en `informes/lab/VALIDACION-MOTOR-V2.md`.

### Pruebas

Suite completa en verde: **326 pruebas**. Nuevas: `test_cuota` (7), `test_valor` (11),
`test_estimador` (4), `test_panel_evidencia` (4). El contrato de UI (`test_panel_layout`, `test_panel_web`) se
reescribió para el nuevo panel: prohíbe un tamaño fuera de la rampa 12/14/20/30, exige
que la evidencia no se pinte sin intervalo ni muestra, y verifica que el reloj y el oro
ya no son protagonistas.

## v0.7.4 — 2026-11-18

**Lo que motivó esto (Diego):** «¿Cuánto tiempo falta entonces?» y, treinta y cinco
minutos después, «uuh, otra vez tengo el timeout?». Sí: a las 03:11:23 el panel volvía a
decir «cuota de espectador: la API pidió esperar 376 s».

**Lo que se encontró.** La cuota no subió de 6/hora: lo que subió fue el contador
`requests` del 429, 6 → 9 → 12, porque **los intentos rechazados también se registran**.
Así cada reintento aleja la recuperación en vez de acercarla: a las 03:11 la ventana tenía
**12** peticiones para un límite de 6. Y reiniciar el coach durante la espera gastaba otra
más, porque la pausa vivía solo en memoria.

**Arreglo.** Dos reglas nuevas:
1. **Una partida, un intento.** Tras un 429, `live_api` marca ese `match_id` en
   `_sin_cuota` y no lo vuelve a pedir mientras viva. El panel dice «cuota agotada para
   la partida N: no se reintenta; se sigue con el HUD» en vez de fingir que va a
   reintentar cada minuto.
2. **La pausa se guarda en disco** (`~/.cache/abrams-coach/cuota_pausa.json`) y se relee
   al arrancar: un reinicio ya no cuesta una petición extra.

De paso, el openapi explica el 504 de la noche: *load shedding* — si una consulta no
cacheada excede el tiempo, la **misma** petición falla al instante durante unos minutos.
Eso es lo que hacía que `matches/active?account_ids` respondiera 504 en 0.26 s una y otra
vez. Las pruebas cubren las dos reglas nuevas (42 comprobaciones en `test_live_api`).

## v0.7.3 — 2026-11-18

**Lo que motivó esto (Diego):** «La app está rota, solo fíjala.» El panel llevaba más de
una hora diciendo «cuota de espectador: la API pidió esperar», después de una noche en la
que el 429 no había vuelto a aparecer desde el 9 de noviembre.

**Lo que se encontró.** El disparón fue de la API (504 de Cloudflare entre 01:19 y 02:07,
que también tumbó `matches/active?account_ids`), pero la cuenta la pagamos nosotros.
A las 01:17:46 falló `live/url` → `url_tv=None` → `run.py` abrió el stream **por
`match_id`**, y abrir por `match_id` **especta** (openapi: 6/h por IP). La escalera de
reconexión (5/15/45 s) abrió cinco veces en ~65 s. El 429 de las 02:06:26 trae
`"type":"IP","requests":6,"remaining":0,"next_request_in":672`. Como la URL nunca se
cacheó, cada expiración de la pausa volvía a intentarlo por id: el panel siguió muerto
hasta pasado 02:20.

**Cuatro fallos encadenados, todos del mismo camino de respaldo.**
1. `/v1/matches/live/urls` (gratis) no se consultaba: se iba directo a `live/url` de pago.
2. Sin URL, el stream se abría por `match_id` y gastaba cuota, con la escalera corta.
3. `_guardar_cache_url()` estaba definido y **nunca se llamaba**: el archivo
   `~/.cache/abrams-coach/urls_broadcast.json` no existía, así que cada reinicio volvía a
   espectar. La caché en disco que el propio docstring prometía era código muerto.
4. El 429 no dejaba rastro útil: ni `type`, ni `requests`, ni una línea por apertura de
   stream. Auditar «quién gastó la cuota» era imposible.

**Arreglo.** El escaparate primero (caché 120 s), sin URL no se abre nada (HUD y
`console.log`, que son gratis, y reintento de la URL cada 60 s), sin URL no hay escalera
(`ESPERA_SIN_URL_S = 300`), la caché de disco se escribe de verdad, y la telemetría suma
`api_429` (type/limit/period/usadas/espera) y `api_sse` (especta sí/no). Cinco reglas
nuevas en `tests/test_live_api.py`, incluida la que mide que lo listado no llama a
`live/url`.

## v0.7.2 — 2026-11-18

**Lo que motivó esto (Diego):** «¿La versión de abrams coach que tengo en mi app abierta
es la misma que la más reciente que tenemos? ¿La actualizamos siempre? ¿Podemos
documentar eso?»

**Lo que se encontró.** Ese 18 a la 01:10 la respuesta era *sí*: la app abierta
(`run.py --fuente vivo`, pid 759485) había arrancado a las 01:09:53, después del último
cambio de código (23:32 del 17), y el repo local, `origin/master` y la copia de la PC
estaban todos en `b1fb1f8`, limpios. Pero **no había forma de comprobarlo desde la app**
ni de recordarlo después: `/api/salud` solo decía `ok`, nadie registraba con qué código
arrancó cada instancia, y el README seguía anunciando «v0.3» cuatro versiones después.
La única evidencia era la hora de los archivos frente a la del proceso, que no es una
respuesta sino una deducción.

**«¿La actualizamos siempre?»** No automáticamente, y el diseño lo justifica: el motor
se arma al arrancar y no hay recarga en caliente (el coach lee el HUD a 14 cuadros por
segundo; recargar módulos a media partida es peor que reiniciar). Desde la v0.7.1,
cerrar la ventana apaga el coach que esa ventana arrancó, así que abrir de cero sí
carga el código de ahora; el caso que engaña es dejar la app abierta, editar y volver a
mirar el panel.

**Arreglo.** `coach/version.py` calcula el estado del disco (commit, rama, limpio/sucio,
huella sha256 de los archivos que definen el comportamiento) y lee el marcador que
`servidor.arrancar()` escribe en `salida/version-en-vivo.json` con el commit y la huella
del arranque real. `comparar()` cruza ambos, añade el remoto (`HEAD...@{u}`) y da un
veredicto: `si`, `no`, `probable_si`, `probable_no`, `sin_app` o `sin_git`. La huella
existe porque un commit no lo cuenta todo: editar sin commitear deja el mismo commit y
otro panel. `/api/version` lo expone; `herramientas/version.py` lo da en terminal (sale
2 si quedó atrás) y `--subir` hace el `git pull --ff-only` explícito. Un marcador de una
instancia muerta se descarta por pid y `cwd`, para que una prueba en otro puerto no
falsee el veredicto.

**Documentado en** [`docs/VERSION.md`](docs/VERSION.md), con la regla operativa, lo que
la herramienta **no** hace y el estado verificado de ese día. `tests/test_version.py`
cubre los seis veredictos sin depender de git.

**Pendiente de Diego:** la app abierta al escribir esto es anterior al cambio, así que
hasta reiniciarla `/api/version` no existe todavía en ella. El CLI ya funciona porque
deduce por proceso y fecha; reiniciar la deja con la respuesta exacta.

## v0.7.1 — 2026-11-16

**Lo que motivó esto (Diego):** «la app de Abrams Coach, ¿siempre está abierta como
servicio? ¿no puede ser solo cuando abro la app?»

**La causa.** `abrir`/`jugar` lanzaban coach y panel con `nohup` y el proceso padre
salía enseguida. Los hijos quedaban dentro de la unidad transitoria que crea KDE al
abrir el `.desktop` (`app-abrams-coach@….service`), así que la unidad seguía «activa»
horas después de cerrar la ventana (había una de 9 h al revisar). El servicio
`abrams-coach-esperar` no tenía nada que ver: está desactivado.

**Arreglo.** `partida.sh prep pegado` arranca el panel sin `nohup`, como hijo directo,
y hace `wait`: la ventana pasa a ser el proceso principal de la unidad. Al cerrarla se
apaga el coach que arrancó esa sesión y no se toca uno que ya estuviera vivo. `abrir`,
`jugar` y `demo` usan el modo pegado; `ABRAMS_QUEDAR=1` recupera el comportamiento
viejo y `partida.sh prep` desde una terminal sigue dejándolo en segundo plano.

**Probado:** abrir en modo pegado → API en :8090 responde; cerrar la ventana → `prep`
termina, la API deja de responder y no queda ningún `run.py` vivo.

## v0.7 — 2026-11-16

**Lo que motivó esto (Diego, tras ranked):** «sigue sin tener una noción de venta… debería
poner en algún color diferente algún ítem de los que pueden ser vendidos en prioridad,
sobre todo en late» y «no está tan actualizado el timer de souls, sí cambia decisiones
justo cuando sabes que tienes al menos para el siguiente tier».

**Ventas con prioridad (`coach/decision/ventas.py`).** Nueva capa que responde solo «¿qué
de lo que llevo sale primero?»: ordena por residual con las medidas de siempre (residual,
`tasa_venta` de partidas reales, `min_venta`) y marca `ahora` (late ≥ 18 min o build
agotado) o `luego`. Se publica en `ventas` y se anota en cada ítem del inventario
(`vende`, `vende_pp`, `vende_motivo`). Antes, con 12 slots llenos y el camino agotado, el
panel decía «build completo» y no nombraba nada que soltar.

**Color de venta en los dos paneles.** Web: tira de inventario con borde rojo (sale
primero) y ámbar (candidato), etiqueta «vende» y línea «salida prioritaria». GTK: clases
`slot-vender-ahora` / `slot-vender-luego` y la tarjeta Ventas muestra la lista cuando no
hay compra pendiente.

**Vender para pagar.** Con el slot lleno, el hueco vale el precio completo del ítem que
sale: si el bolsillo no llega pero vender una pieza del mismo slot sí, la venta se nombra
(`venta.para_pagar`) en vez de dejar solo «faltan 2 800». Tope en el patrimonio
(`costo_lista <= almas`): sin él, estados imposibles (12 slots con 900 de patrimonio)
generaban compras que no se pagan y la invariante 1 lo cazó.

**Un solo «vende esto».** El motivo de la decisión y la venta final se reconciliaron: el
camino podía decir «vende X» (del ranking) y la venta «vende Y» (del slot del ítem). Ahora
el nombre, el color del inventario y la lista de prioridad apuntan al mismo ítem.

**ETA de almas real.** `motor.tasa_almas_historial` mide almas/s con las últimas muestras
del bucle (ventana 90 s, techo 90 almas/s), y `camino.tasa_almas(..., real=)` la usa en
vez del benchmark del héroe. El panel web cuenta hacia atrás con `ts` y `tasa_almas_s`:
«faltan ~N · ~Xs» y «ya te alcanza (estimado con tu ritmo)» entre lecturas del broadcast.
No cambia la acción a COMPRAR por proyección: pedir un ítem que el oro medido todavía no
paga rompería la invariante de caja.

**Puerta de calidad:** `pytest -q` en verde, invariantes 6/6. 6 pruebas nuevas en
`tests/test_ventas_late.py`. (En este equipo pytest está en `~/.dsh/bin/pylib`.)

**Sigue abierto:** el fin de partida congelado y el descubrimiento por cuenta en ranked
(ver 2026-11-15, noche 7).


## v0.6 — 2026-11-15

**Lo que estaba roto de verdad.** `run.py` tenía `bucle_ocr` y `bucle_auto` duplicados:
ganaba la definición vieja, que decidía una sola vez al arrancar, así que abrir la app en
el menú la dejaba en el lector de marcador para siempre. En ese modo el panel publicaba
«veo el marcador y las 12 almas» sin haber leído nada.

**Captura.** El hilo del HUD pedía el escritorio entero (4480×1440, 64 ms) cada 2 s para
recortar dos cajas de 100×40: ese readback es el tirón que se nota en peleas. Ahora se
pide caja por caja (reloj 0.9 ms, banda de oro 2.5 ms). El modo OCR ya no usa `spectacle`
(415 ms y 450 KB en disco por cuadro): KWin por región, sin PNG.

**Estado del juego.** El menú también pasa por `GameInProgress`, así que la fase sola
mentía. La señal que separa es el mapa (`dl_hideout`) y `Source2Shutdown` marca el cierre.
El panel dice «en el menú», «en partida · abre Tab», «esperando al juego» o «datos de hace
N s», nunca una partida que ya no existe.

**Datos.** Archivo local de partidas públicas (`herramientas/archivo_abrams.py`, 166 653
partidas en 21 MB, 1000 por petición), índice de composiciones y de pares
(`coach/historico.py`), ítems contra composición con muestra y cota (`coach/items_comp.py`)
y camino de compra por héroe (`coach/camino_heroe.py`). Descubierto en el camino: el array
`items` del metadata mezcla compras con **subidas de habilidad**; sin filtrar, la apertura
de Abrams eran sus tres habilidades.

**Visión.** Hugging Face devuelve HTTP 402 sin créditos; queda solo Command Code, que lee
la tira del HUD (4 kB) en 10.4 s.

**Panel web.** `/panel`, sin dependencias externas, verificado en Chromium a 1280×700 y
800×600.

**Pruebas.** 261. Un clon limpio pasa la suite (los módulos que necesitan assets se saltan
diciendo qué correr). `herramientas/verificar_v2.py` comprueba las once piezas de un
vistazo.

**Auditoría.** El banco completo (626 partidas) contra el motor anterior a Scourge:
alcanzable 59.4 % → 55.5 %, cobertura 9.3 % → 9.5 %, caro sin ahorrar 0 en los dos.

## v0.5 — 2026-11-11

- `coach/resultado.py`: resultado de partida desde la API (win/loss, duración, KDA) con
  parser puro y `desde_api` que **nunca lanza**. Sin cuenta ni slot y con dos Abrams,
  devuelve None en vez de adivinar.
- `abrams-coach resultado <id>` y `--todas`: llena `resultados`, que llevaba vacío desde
  el principio. `archivar` lo intenta al terminar y no falla si la red no responde.
- `tests/test_resultado.py` (15 comprobaciones): parser, casos ambiguos, API caída,
  guardado idempotente y `winrate_por_primer_item` con datos.
- Herramientas de API a prueba de red: `tesoros.py`, `investigar.py` y `residuales.py`
  salen con código 2 y un mensaje si no hay conexión, sin traza y sin tocar nada.
- `tests/test_herramientas_api.py`: API caída, caché que evita descargas repetidas y
  JSON corrupto rechazado.
- `abrams-coach resultado --acierto`: winrate real por primer ítem.

## v0.4 — 2026-11-11

- `herramientas/tesoros.py`: combinaciones raras que ganan, desde la API (permutaciones de
  2–3 ítems, filtrable por héroe, muestra y fechas). Wilson al 95%, estratos de coste y
  minuto, y cohorte `--max-networth` para no confundir «ganar» con «comprar caro».
- Apertura ponderada por progresión: un 800 que no compone nada (Extra Regen) pesa 0.60 y
  deja de ser el primero. La apertura pasa a Spirit Strike, Close Quarters, Extra Regen.
- `docs/hipotesis-meta.md`: método de caza de tesoros, cadencia por parche e hipótesis
  abiertas con su falsificación.
- Corregido el fondo del banco: la cobertura mide parecido, no calidad (se documentó por
  qué bajó de 13.8% a 9.3% con la apertura nueva).

## v0.3 — 2026-11-10

- Amenazas por enemigo: almas contra la media de tu equipo, con nivel
  (`critico`/`alto`/`parejo`/`flojo`). El crítico se marca `EVITAR` en la cabecera y en la
  rejilla, y no se busca solo.
- Counters atados a la amenaza: el counter del rival que va por encima pesa ×1.6, entra
  en el camino y pasa sin esperar la ventana de fase. El de composición sigue barato.
- Perfil de build (`contra`/`atras`/`arriba`/`base`): el camino deja de ser el mismo en
  todas las partidas. La apertura de tres piezas de 800 no cambia; lo de después sí.
- Elección de cada paso: frecuencia normalizada del grafo (0.60) + economía del perfil
  (0.28) + balance de slots (0.12).
- El panel dice por qué el camino cambió: línea de perfil sobre la tira y motivo en la
  tarjeta.
- `tests/test_amenazas.py` (24 comprobaciones) y `docs/amenazas-y-perfil.md`.
- `herramientas/linea_tiempo.py`: rejuega una partida real minuto a minuto y enseña qué
  recomienda el coach, con resumen de cambios de opinión, rachas y «build completo».
- El camino pasa de 9 a 12 pasos (los 12 slots) y se rellena con lo mejor que quepa: se
  acaba el «build completo» al minuto 17 con oro en el bolsillo.
- El counter de composición deja de cambiar la compra (Slowing Bullets salía media
  partida y oscilaba con el oro); solo el del rival que va por encima desvía el build.
- Medido en 40 partidas: cambios de opinión 3.42 → 3.17 por partida, «completo» 3.17 → 0,
  Slowing Bullets fuera del top 8 de ítems repetidos.
- Perfil `remontada` a partir del minuto 20 yendo atrás.
- `herramientas/banco_partidas.py`: corre el motor sobre las 626 partidas del cache (38 s,
  paralelo) y saca alcanzabilidad, calibración por tramo, cobertura, vaivén y sesgo de
  ítems contra el meta observado.
- `herramientas/meta_abrams.py` y `data/meta_abrams.json`: el meta se mide, no se copia
  de una guía. La apertura pasa a Extra Regen, Spirit Strike y Close Quarters.
- Arreglado el camino que se daba por completo al comprar un componente (partida 60142085)
  y el objetivo con «faltan» negativo que detectó el QA de invariantes.
- Cap de tier 4 antes del minuto 15 y de refuerzos de 800 pasados 20 minutos.
- `tests/test_banco.py`: 12 partidas en la batería como guardarraíl de comportamiento.

## v0.2 — 2026-11-09

- Panel nativo GTK4 en cuatro tamaños, con colocación automática en el monitor secundario.
- Modo pantalla: con el juego en ranked y sin broadcast, lee el reloj del HUD y publica
  el plan de apertura desde el minuto 0.
- El id de partida se lee del HUD, así que el broadcast se puede enganchar **sin cuenta**.
- Si no hay cuenta, `--mi-heroe` identifica tu columna cuando el héroe es único.
- Lectura del HUD a 7.9 Hz con captura KWin compartida; sin tirones en partida.
- Motor con componentes, frescura de datos y filtro por oro; 4.5 ms por decisión.
- Build como camino apertura → core → spike, con estado COMPRAR/AHORRAR/VENDER, ETA y
  componentes del objetivo. Baja de 4–5 a 1.4 ítems de 800 en los primeros 10 minutos.
- El objetivo ya no retrocede a la apertura a los 30 minutos ni ignora los upgrades de
  lo que llevas; la rama cambia con la composición enemiga cuando los datos la apoyan.
- Ventas con nombre y slot; huecos de inventario por categoría.
- Captura compartida a 2 Hz (antes 5.5) y menos trabajo de OCR por segundo.
- Bonus de categoría de 4,800: progreso visible y empujón suave, sin volver el build
  genérico.
- Base SQLite con archivado idempotente e informe de partida.
- Repo público: fuera datos personales, cuentas y arte de Valve; iconos en runtime.
- CI real: GTK bajo Xvfb, suite completa, motor sobre muestra anonimizada.

## v0.1 — 2026-11-07

- Primera versión: lector de marcador, motor con invariantes, modo en vivo y panel demo.
