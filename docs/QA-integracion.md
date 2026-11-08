# QA de integración — rama `wip/fixes-sesion-2026-11-08`

Revisión del árbol que dejaron tres implementadores en paralelo. No se tocó nada: no hay
commit, no hay `git checkout`, no se reinició el coach (127.0.0.1:8090) ni el panel, no se
mató ningún proceso, no se abrió el juego ni el navegador.

## Qué corrí

- `git status` / `git diff` completos (2 641 líneas de diff, 11 archivos modificados,
  4 nuevos + `docs/experto/` sin seguimiento).
- `/tmp/dlvenv/bin/python -m pytest -q` (suite completa, una vez).
- `compileall` de `coach/`, `run.py` y `panel_nativo.py`: sin errores de sintaxis.
- Import de los módulos nuevos (`nucleo_vivo`, `nucleo_demo`, `api_vivo`, `captura_kwin`,
  `revisar`, `run`): todos importan.
- `servidor.diagnostico()` y `motor.analizar_dict()` sobre estados armados a mano: solo
  local, sin red (no se llamó a la API).
- Conteo de líneas de los archivos tocados, HEAD contra el árbol de trabajo.

## Tests

```
1 failed, 27 passed in 74.14 s (0:01:14)
FAILED tests/test_ui.py::test_suite
```

Es el baseline conocido: 27 OK y el fallo ambiental de `test_ui` (3 capturas 47–59 KB por
debajo del umbral de 60 KB). **No hay regresión en tests.** El refactor no rompió ninguna
firma que los tests usen: `tests/test_vivo_run.py` sigue llamando `run.estado_desde_vivo` y
funciona porque `run.py` la reexporta desde `nucleo_vivo`.

## Veredicto

**Se puede usar en `--fuente simulado` y `--fuente ocr`. Para `--fuente vivo` hay que
arreglar P1 y P2 antes de confiar en el reloj y en el estado que muestra el panel**: los dos
mecanismos que debían corregir la latencia del broadcast y la partida muerta están escritos,
documentados y **desconectados**. No es que fallen: no se ejecutan nunca.

---

## Prioridad 1 · El descubrimiento de partida está duplicado y el que se usa es el tonto

`coach/fuentes/api_vivo.py` se reescribió entero (`descubrir()`, 3 capas, TTL 30 s,
cache-bust a los 3 vacíos, caducidad por 90 s sin señal). **Nadie lo llama.**
`run.py:60` usa `nucleo_vivo.buscar_match()` (`nucleo_vivo.py:41`), que hace
`en_vivo.partida_activa()` + `hud.leer_match_id()` — la versión de antes. Quedan sin una sola
llamada: `descubrir()` (`api_vivo.py:77`), `olvidar()` (`:157`) y `buscar_en_listado()`
(alcanzable solo desde `descubrir`).

Consecuencias concretas, todas verificables:

1. **La regla de los 90 s no corre.** `en_vivo.py:378` (docstring de `Escucha`) dice que el
   match lo suelta "el descubrimiento de `coach.fuentes.api_vivo` (90 s sin un solo estado)".
   Esa regla vive en `api_vivo._por_silencio()` (`:41`) y no la llama nadie.
2. **El match queda pegado.** `buscar_match()` devuelve `a.match` sin mirar nada más
   (`nucleo_vivo.py:47-48`) y lo fija de forma permanente cuando lo lee del HUD
   (`:64`). Si esa partida termina, el SSE de `Escucha` reintenta 5/15/45 s y después cada
   300 s **para siempre**, sin soltar nunca el id.
3. **El TTL de 30 s tampoco corre.** El bucle vivo consulta `matches/active` cada vuelta
   (la puerta de `en_vivo.INTERVALO_MIN_GOLPE_S = 3.0` la deja pasar cada 3 s), que es
   justo lo que el TTL de 30 s de `api_vivo` existía para evitar.
4. **`/api/revisar` miente por omisión.** `servidor.diagnostico()` lee
   `api_vivo.estado()` (`servidor.py:107`) y ese dict solo lo llena `descubrir()`. Medido:
   `{'via': None, 'detalle': 'sin buscar', 'edad_s': None}` — siempre, porque el caché
   nunca se escribe.

Arreglo: **una** ruta. O `buscar_match()` pasa a `api_vivo.descubrir(cuenta=a.cuenta,
con_hud=not a.sin_hud)` y se borra `buscar_match`, o se borran `descubrir`/`olvidar`/
`buscar_en_listado` y se corrige el docstring de `Escucha`. Dejar las dos es lo peor: la
mitad nueva no se usa y la vieja no tiene la caducidad.

## Prioridad 2 · El HUD nunca ajusta reloj ni oro, y el docstring dice que sí

`nucleo_vivo.ajustar_con_hud()` (`:146`) promete: "Cambia reloj y oro del broadcast por los
del HUD si la lectura es fresca". La condición de frescura es
`time.time() - estado_hud["ts"] >= 8` (`:151`) y **`estado_hud["ts"]` nunca se escribe**:
se inicializa en `0.0` (`nucleo_vivo.py:93`) y `hud_rapido.leer_actual()` no devuelve `ts`
(sus claves son `t`, `oro`, `caja_oro`, `ms_reloj`, `ms_oro`, `edad_captura_s`), así que el
`update(d)` del hilo (`:87`) no toca esa clave. Con `ts = 0.0` la resta siempre es enorme y
la función retorna en la primera línea.

Medido con un `estado_hud` fresco (`t=900`, `oro=2500`) sobre un crudo con `t=870`:
`t` sigue en 870, `latencias['broadcast_s']` sigue en `None`, `notas` queda vacío.

Esto **no lo introdujo esta sesión** (en `HEAD:run.py:122/148` el patrón es idéntico), pero
el refactor lo aisló en un módulo propio con un docstring que afirma lo contrario, y el pie
del panel sigue diciendo "latencia del broadcast" como si estuviera medida. O se guarda `ts`
al actualizar `estado_hud` (una línea) y el modo vivo pasa a tener reloj real, o se borra
`ajustar_con_hud` y se quita la promesa del docstring y de `/api/revisar`.

## Prioridad 3 · Tres formas de capturar la pantalla y las cajas calibradas duplicadas

| Mecanismo | Dónde | Quién lo usa |
|---|---|---|
| Hilo compartido del escritorio (KWin completo, 0.15 s) | `coach/fuentes/captura.py` | solo `hud_rapido` |
| Recorte + OCR del cuadro compartido, cajas en `config/coach.yaml` | `coach/fuentes/hud_rapido.py` | camino vivo de reloj/oro |
| Captura KWin **por región**, con caché de píxeles y cajas escritas en el código | `coach/hud.py` (`_Cajas`) | `leer_match_id()` desde `buscar_match` |
| `spectacle -f` a PNG | `lector.capturar()` | modo OCR |

Dos de estos caminos leen lo mismo: `hud.leer_hud()` (`hud.py:145`) lee reloj y oro, igual
que `hud_rapido.leer()`, y no lo llama nadie salvo el `__main__` de su propio archivo. Las
coordenadas están copiadas en dos sitios: `hud.CAJA_RELOJ/CAJA_ORO/CAJA_MATCH`
(`hud.py:46-49`) son idénticas a `hud_rapido.CAJAS_DEFECTO["reloj"|"banda_oro"|"match"]`
(`hud_rapido.py:23-28`). Si se recalibra el HUD hay que acordarse de los dos, o el panel
mezcla lecturas de una calibración vieja con otra nueva.

`docs/experto/captura_vision.py` es una tercera copia del mismo DBus de KWin (prototipo).

Arreglo: dejar `hud.leer_match_id()` haciendo solo eso (que es para lo único que se usa) y
tirar `leer_hud`/`_oro_amplio`/`_capturar`, o al revés. No las dos.

## Prioridad 4 · `almas_12` se calcula en cuatro sitios, con dos órdenes distintos, y no lo lee nadie

Se arma en `crear_analizador.analizar` (`run.py:233`), en `bucle_simulado` (`:39`), en
`bucle_vivo` (`:116`) y en `bucle_ocr` (`:139/151`). El consumidor que tenía
(`componentes/equipo.py`) migró a la lista `aliados`, y hoy el único que menciona el campo es
`tests/test_vivo_run.py`, que lo arma por su cuenta. Además los cuatro no coinciden:

- `analizar` y los bucles vivo/simulado: `[yo, aliados…, enemigos…]`.
- `bucle_ocr`: `lec["almas"]["aliados"] + lec["almas"]["enemigos"]`, o sea los 6 aliados
  incluido yo primero.

Dos órdenes para el mismo campo es una trampa para el próximo que lo consuma. En el mismo
saco: `publicar_sin_columna()` (`run.py:179`) publica `almas_aliados`, `almas_enemigos` y
`tiempo_s`, también sin consumidor. Y `publicar_congelado` / `publicar_fuera_de_partida`
(`nucleo_vivo.py:124` y `:134`) son de un solo uso: son tres funciones envolviendo un
`EST.publicar(dict)`.

Arreglo: borrar `marcador_12` y las cuatro asignaciones (−30 líneas) o dejar **una** en
`analizar`.

## Prioridad 5 · Tres reglas para "¿me alcanza?" y dos `objetivo`/`faltan` distintos

1. `motor.candidatos`: `alcanzable = costo <= almas` (patrimonio) — `motor.py:420`.
2. `motor.sugerir_venta`: vuelve a comprobar `f["alcanzable"]` y además
   `f["costo_lista"] > almas` — `motor.py:548-552`.
3. `nucleo_vivo.filtrar_por_oro`: filtra por **oro sin gastar** y **reescribe**
   `recomendaciones` a mano (`pagables[:3]`, o una sola con `alcanza: False`/`faltan`),
   pisando la lista de hasta 10 que arma `recomendar()`.

Con el cambio de esta sesión (el motor ya no descarta por `costo > almas`, ahora marca
`alcanzable`) hay dos "objetivo" en el sistema: `recomendar()["objetivo"]` (el primero no
alcanzable de `filas`, sin filtro de fase desde que se quitó `dist > 30`) y el que fabrica
`filtrar_por_oro`. El panel recibe el de `run.py`; el del motor viaja y no se usa, o peor,
dice otra cosa. Una regla, no tres: el motor decide qué es comprable con oro y `run.py` solo
recorta la lista.

---

## Secundarios (no bloquean)

| # | Problema | Evidencia |
|---|---|---|
| 6 | Config muerta: `flex`, `w_fase` y `ventana_fase` siguen en `config/coach.yaml:8,30,31` y en `coach/config.py:24,27,39,75,88,89`, pero el motor ya no los lee (`_cap()` ignora `flex`, no hay `_fase_fit`, no hay `ventana_fase`). `docs/experto/scoring.md` dice explícitamente que se borraban de `config.py:39` y `:89`; no se hizo. Medido: `cargar().motor` trae las tres claves. Igual `fuentes.timeout_s/reintentos/backoff_s`: sin consumidor desde que se borró `FuenteApiVivo`. | `config/coach.yaml`, `coach/config.py` |
| 7 | `/api/revisar` no tiene interfaz: `coach/ui/componentes/revisar.py` (101 líneas, botón + área de texto) no lo importa nadie, `app.py` no lo monta. El endpoint funciona por `curl`; `veredicto()` y `proveedor_flash()` solo existen para él. O se monta en el panel o se borra el componente. | `grep -rn "Revisar"` |
| 8 | `docs/experto/api.md:88,91` describe "lo que sobra hoy" citando `api_vivo._traducir()`, `_backoffs()` y `_resolver_match()`: los tres ya no existen. El doc quedó escrito contra el código de antes del refactor. | `docs/experto/api.md` |
| 9 | `coach/fuentes/base.py`, `compuesto.py` y `simulador.py` son una interfaz (`FuenteDatos`) que la app ya no implementa ni usa: solo la ejercitan los tests. `api_vivo` era el último que la implementaba. | `tests/test_fuentes.py` |
| 10 | `herramientas/evaluar_motor.py:60` sigue con `i["t"] <= t` (el bug que `scoring.md` documenta: `acierto` y `en_top3` dan 0.0 %). Y `tests/test_invariantes.py:474,508` imprime causas que citan `_es_mejora_de()`, borrada en esta sesión. | `herramientas/`, `tests/` |
| 11 | Cobertura: las 578 líneas nuevas de `nucleo_vivo`/`nucleo_demo`/`captura_kwin` + la reescritura de `api_vivo` no tienen un solo test. El único que toca `run.py` es `test_vivo_run`. | `tests/` |

## ¿La app quedó más simple?

En `run.py` sí, mucho: 594 → 325 líneas, con los bloques anidados convertidos en funciones y
la duplicación de `_publicar_hud()` (código muerto detrás de un `return False`) eliminada.

En el conjunto, no. Líneas de los archivos tocados, HEAD contra ahora:

| | HEAD | ahora |
|---|---|---|
| `run.py` | 594 | 325 |
| `en_vivo.py` | 336 | 567 |
| `motor.py` | 563 | 675 |
| `servidor.py` | 185 | 313 |
| `hud.py` | 119 | 168 |
| `api_vivo.py` | 216 | 164 |
| `captura.py` | 118 | 132 |
| `contra.py` | 59 | 74 |
| `situacionales.py` | 171 | 188 |
| `proveedor.py` + `agente/__init__.py` | 223 | 241 |
| nuevos (`nucleo_demo`, `nucleo_vivo`, `captura_kwin`, `revisar`) | — | 578 |
| **total** | **2 584** | **3 425** |

De esas 841 líneas de más, unas 400 son del diagnóstico `/api/revisar` (servidor + proveedor
+ `revisar.py`) que **ninguna interfaz muestra**, y 140 de `captura_kwin.py`, que sí está
justificado (0.9–34 ms medidos contra 415 ms de `spectacle`). El resto es scoring por
contexto y comentarios. La app no quedó más simple: quedó mejor organizada y más grande, y
con dos caminos escritos para el mismo problema en tres sitios (descubrimiento, captura,
"alcanza").

## Lo que está bien y no hay que tocar

- `run.py` partido en `nucleo_demo` / `nucleo_vivo` sin cambiar firmas: `test_vivo_run`
  sigue pasando.
- La puerta de ritmo y cuota de `en_vivo` (un golpe cada 3 s, `retry-after` respetado,
  `ErrorCuota` propagado) es una sola para todas las llamadas, incluido el stream.
- Las claves de `HEROES_CON` corregidas contra `data/heroes_index.json` (`mcginnis`,
  `grey_talon`, `lady_geist`, y `arcanist` fuera, que no existe). Verificado: con `haze` +
  `lady_geist` en el equipo enemigo salen los ítems de espíritu con su coeficiente.
- El coeficiente contextual (`coef` = residual × ganancia, con `coef_global` al lado) es
  coherente entre `motor.py` y la lista de composición, y `contra.py` repinta cuando cambia.
- `sugerir_venta()` usando las filas de `candidatos()` en vez de su propia fórmula: una
  fórmula, no dos. Es exactamente el criterio que hay que aplicar en P1, P3 y P5.
