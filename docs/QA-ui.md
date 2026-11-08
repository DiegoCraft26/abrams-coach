# QA de interfaz del panel

Revisión del panel nativo GTK4 (`panel_nativo.py` → `coach/ui/app.py` y
`coach/ui/componentes/*.py`) el **2026-11-08**, en la máquina de desarrollo.
Alcance del arreglo: solo `coach/ui/componentes/*.py` y `coach/ui/tema.css`.
Lo que vive en `coach/ui/app.py`, `herramientas/` o el servidor queda aquí como hallazgo,
sin tocar.

## Cómo se midió

| Qué | Cómo |
|---|---|
| Capturas de los 4 tamaños, panel vacío | `/tmp/dlvenv/bin/python herramientas/capturar_ui.py --url http://127.0.0.1:8090 --salida /tmp/qa-ui2-8090` |
| Capturas con datos | el mismo comando contra un demo aparte: `run.py --fuente simulado --puerto 8095` (el coach de 8090 no se tocó) |
| Capturas con datos al límite | estado inyectado a los componentes: nombres de héroe largos, 13 ítems en el inventario, coste de 1 234 567 almas, `coalesce` de nulos, ganancia negativa, `historial` desordenado (`/tmp/qa_extremo.py`) |
| Tests | `/tmp/dlvenv/bin/python -m pytest -q` → 27 OK y 1 FALLA (`tests/test_ui.py::test_suite`, las 3 capturas por debajo de 60 KB). Igual que el baseline: no es regresión |

Estado real del coach a las 11:33 del 2026-11-08: `/api/estado` devolvía
`listo: false`, `rancio: true`, `edad_s: 4849.7`. **No hubo partida real en vivo durante
esta revisión**: todo lo que se ve con datos de partida es demo o estado inyectado. El
caso "partida real por el broadcast" queda **sin medir** en esta pasada.

Las capturas de esta revisión están en `/tmp/qa-ui2-8090` (vacío),
`/tmp/qa-ui2` (demo) y `/tmp/qa-extremo2` (límite). Son temporales: se regeneran con los
comandos de arriba.

## Resultado por tamaño

| Tamaño | Reparto | Veredicto |
|---|---|---|
| 1920×1080 | amplio (3 columnas) | Se ve bien, salvo que la tendencia ocupa ~630 px de alto (A1) |
| 1280×720 | amplio (3 columnas) | Se ve bien; el inventario se parte 10 + 2 (A2) |
| 960×1080 | medio (2 columnas) | Se ve bien; hueco muerto en la columna derecha entre COMPRAS y VENTAS (M4) |
| 800×600 | medio + compacto | Se ve bien; se ocultan VENTAS, CONTRA y TU EQUIPO como está previsto; la tendencia queda cortada por el borde y hay que bajar con la rueda |

Los cuatro tamaños se construyen y pintan, sin texto fuera de su caja y sin solaparse con
el pie. Los defectos que quedan son de reparto, no de recorte.

## Alto

### A1. La tendencia se come el panel (sin arreglar: `app.py`)

`coach/ui/app.py:209` pone `self.tendencia.set_vexpand(True)` justo debajo de un comentario
que dice lo contrario ("La tendencia no se estira: un gráfico de 700 px de alto no se lee").
El comentario describe lo correcto; el código hace lo otro.

Medido sobre las capturas: a 1920×1080 la zona de dibujo va de y≈400 a y≈1030
(**~630 px de alto para dos polilíneas**); a 960×1080, ~570 px; a 800×600 el gráfico se
lleva lo que queda de ventana y obliga a desplazarse.

Arreglo propuesto (una línea): `set_vexpand(False)` y dejar el `set_size_request(-1, 170)`
que ya está en la línea siguiente. Que el espacio sobre lo ocupe el relleno.

### A2. El inventario se parte en dos filas irregulares (sin arreglar: `app.py`)

`coach/ui/app.py:201` fija `columnas=6` en modo angosto y `12` en el resto. La columna
principal mide 616 px a 960×1080 y 644 px a 1280×720 (descontados márgenes, separaciones y
la columna de 300 px), y 12 slots de 44 px con 4 px de separación necesitan 572 px más
márgenes, así que el `Gtk.FlowBox` decide solo y parte 10 + 2 (1280×720), 11 + 1
(estado vacío a 1280) y 8 + 4 (800×600). Se lee como error de maquetación.

Arreglo propuesto: usar 6 columnas también en `medio`/`amplio` (6×2 se lee de un vistazo y
nunca se parte), o medir el ancho asignado al `FlowBox` y elegir 12/10/6.

### A3. Signo doble en VENTAS — **arreglado**

`coach/ui/componentes/ventas.py:48` anteponía un `+` fijo al número, así que una ganancia
negativa salía como **"+-3.2 pp de residual"**. Vista en la captura de datos al límite.
Ahora el signo lo pone el formato (`{gp:+.1f}`) y el color acompaña: acento si suma, aviso
si resta.

### A4. El rango de la tendencia iba al revés — **arreglado**

Medido en las capturas de demo, tres veces: `30:00 → 20:00`, `15:00 → 10:00`,
`10:00 → 0:00`. La causa está en dos sitios:

1. `coach/ui/componentes/tendencia.py:60` (antes) tomaba `_puntos[0]` y `_puntos[-1]` como
   extremos del rango, pero el `historial` de `run.py:225` es un `deque` que arrastra
   muestras de la vuelta anterior: no está ordenado por tiempo.
2. La polilínea se dibujaba en el orden de la lista, así que retrocedía en horizontal.

Ahora los puntos se ordenan por tiempo al entrar (`tendencia.py:50`) y el rango sale del
primero y el último punto cronológicos: `0:00 → 39:59 · 80 muestras`.

## Medio

### M1. Nombres de héroe crudos, con guion bajo — **arreglado**

Los ids de `data/heroes_index.json` son `grey_talon`, `lady_geist`, `mo_&_krill`,
`the_doorman`. `enemigos.py` y `equipo.py` les aplicaban `.capitalize()` y se veía
**"Grey_talon", "Lady_geist", "Mo_and_krill"**. Ahora pasan por `base.nombre_heroe()`
(`base.py:66`), que cambia el guion bajo por espacio y capitaliza cada palabra:
"Grey Talon", "Mo & Krill".

### M2. La columna de almas se desalineaba con nombres largos — **arreglado**

`enemigos.py:49` (antes) solo ponía elipsis. Con `set_size_request(74)` como *mínimo* y sin
techo, "Mo_and_krill" medía más de 74 px y empujaba la columna: en la captura de límite las
almas caían en x=415, x=397 y x=470 en tres filas seguidas. Ahora `elipse(nom, 10)` fija el
techo en caracteres y deja el nombre completo en el tooltip. Las almas y el KDA vuelven a
alinearse.

### M3. Las compras largas se cortaban sin forma de leerlas — **arreglado**

`compras.py:32` ponía elipsis sin tooltip. Una línea como "Un enemigo compró «Improved
Spirit Armor» y otro compró «Superior Stamina» en el mismo minuto" quedaba en "…en el
mismo…" para siempre. Ahora usa `elipse()` (elipsis + tooltip).

### M4. Hueco muerto en la columna de contexto (sin arreglar: `app.py`)

`app.py:243` mete un `_relleno()` con `vexpand` entre COMPRAS y VENTAS para empujar lo
secundario abajo. A 960×1080 eso deja ~250 px de vacío entre COMPRAS y VENTAS y corta la
columna en dos bloques que no se relacionan. A 1280×720 el hueco es menor pero existe.
Propuesta: quitar el relleno (el `Gtk.ScrolledWindow` ya evita que nada se pierda) y dejar
las secciones seguidas.

### M5. Chip de fase contradictorio con "sin partida" — **arreglado**

Con el coach sin partida, la cabecera decía "● sin partida" a la izquierda y el chip
"INICIO" a la derecha: dos estados a la vez, y el segundo inventado
(`cabecera.py:76` ponía `or "INICIO"` como valor por defecto). Ahora el chip solo se ve
cuando el servidor manda una fase y hay partida (`cabecera.py:77`).

### M6. Icono roto de GTK en el estado vacío — **arreglado**

Sin recomendación, la tarjeta grande pintaba el icono `image-missing` de GTK: un folio con
un círculo rojo, justo en el sitio de más peso visual del panel. Se leía como un fallo.
Ahora la imagen se oculta cuando no hay ítem (`recomendacion.py:111`) y vuelve a mostrarse
en cuanto llega uno (`recomendacion.py:72`).

### M7. "media enemiga 11,679.8" — decimal en un contador de almas — **arreglado**

`tendencia.py:59` (antes) formateaba con `:,` sobre un `float`: "tú 12,295" al lado de
"media enemiga 11,679.8". Ahora los dos pasan por `fmt_num()` y quedan como enteros con
separador de miles.

### M8. "faltan 3,100" sin unidad — **arreglado**

`plan.py:37`: la línea del objetivo decía "faltan 3,100" y "faltan 100" en las capturas de
demo. Ni la unidad ni el contexto estaban en el panel: ahora dice "faltan 3,100 almas".

### M9. El motivo del ajuste se repite idéntico en cada ítem de CONTRA (sin arreglar)

En las capturas de demo los dos ítems de CONTRA SU COMPOSICIÓN traen el mismo
`motivo_ajuste` palabra por palabra ("coeficiente ajustado ×0.93: vas 5% arriba en almas y 3
enemigos con esa amenaza y a esta altura la media de partidas pesa menos") y la sección
enseña el bloque dos veces, 4 líneas cada uno. Es el texto más largo del panel y no aporta
nada la segunda vez. Propuesta: pintarlo una sola vez por sección, o recortarlo a
"×0.93 por contexto" con el detalle en el tooltip. No lo toqué porque cambia qué
información ve el jugador por ítem, y eso lo decide quien diseñó la sección.

## Bajo

| # | Hallazgo | Estado |
|---|---|---|
| B1 | `contra.py`: "3 enemigo(s)" — plural entre paréntesis | **arreglado**: "1 enemigo" / "3 enemigos" (`contra.py:67`) |
| B2 | `pie.py`: "fuente en_vivo" enseñaba el identificador interno del servidor | **arreglado**: "fuente en vivo" (`pie.py:45`) |
| B3 | El reloj sin datos (`reloj(None)` → `"--:--"`) se lee como un glitch de glifos a 24 px: los guiones son cortos y el dos puntos parece un punto | sin arreglar: cambiar el marcador es decisión de diseño; candidato: `—:—` o "sin reloj" |
| B4 | `.slot-valor` es 10 px y la escala del tema es 11/12/13/15/18/24/32 | sin arreglar: subirlo a 11 px puede desbordar el slot de 44 px con el icono de 38; hay que probarlo con el inventario lleno |
| B5 | El pie dice "ajustando" sin sujeto cuando `estable == False` | sin arreglar: candidato "ajustando lectura" |
| B6 | La marca del objetivo en PLAN es un `"$"` que no se explica | sin arreglar: candidato "→ objetivo" o un icono |
| B7 | INVENTARIO no explica qué significan el borde verde/rojo ni el número del slot (residual en pp); solo está en el tooltip | sin arreglar: añadir leyenda es sumar texto, y la sección ya se lee por color |
| B8 | `Gtk-WARNING: GtkGizmo (slider) reported min width -2` en cada repintado, 2 por ventana | no es del tema: se reproduce con un `Gtk.ScrolledWindow` pelado y CSS propio cargado o no (probado). Es de GTK 4; no se arregla desde aquí |
| B9 | `herramientas/capturar_ui.py --preguntar` llama a `win.copiloto`, que ya no existe en `coach/ui/app.py` | **rompe**: `AttributeError` dentro de `siguiente()`, la app no programa capturas y el proceso se queda colgado (verificado: 60 s sin PNG y sin salida). El copiloto se retiró del panel pero la herramienta sigue prometiéndolo. Arreglo: borrar la opción `--preguntar` de la herramienta |
| B10 | `coach/ui/componentes/revisar.py` (nuevo, sin seguimiento en git) no está importado en `app.py`: el botón "Revisar" no existe en el panel | sin arreglar: es trabajo en curso de otra sesión; o se conecta o se borra |
| B11 | El `historial` del demo se mezcla al reiniciar el reloj: la tendencia muestra "tú 12,295" mientras la cabecera dice "0:00 300 almas" | dato del demo, no de la UI: con una partida real el reloj solo crece. Queda anotado por si alguien lee capturas del demo |

## Lo que se arregló (resumen)

| Archivo | Cambio |
|---|---|
| `coach/ui/componentes/base.py:66` | `nombre_heroe()`: id con guion bajo → nombre legible |
| `coach/ui/componentes/enemigos.py:36,51` | nombre legible + `elipse(nom, 10)`: el nombre largo ya no desalinea las almas |
| `coach/ui/componentes/equipo.py:41,43` | lo mismo en TU EQUIPO |
| `coach/ui/componentes/compras.py:35` | elipsis con tooltip en el feed de compras |
| `coach/ui/componentes/contra.py:67` | "1 enemigo" / "3 enemigos" |
| `coach/ui/componentes/plan.py:37` | "faltan N almas" |
| `coach/ui/componentes/tendencia.py:50,62,63` | puntos ordenados por tiempo; rango correcto; almas sin decimales |
| `coach/ui/componentes/ventas.py:48` | signo único y color según el signo |
| `coach/ui/componentes/recomendacion.py:72,111` | se oculta el icono roto cuando no hay ítem |
| `coach/ui/componentes/cabecera.py:38,45,77` | el chip de fase solo existe si hay partida |
| `coach/ui/componentes/pie.py:45` | "en vivo" en lugar de "en_vivo" |

`coach/ui/tema.css` no se tocó: no encontré ningún defecto de tema que arreglar sin
medir antes el inventario lleno (B4).

Verificación: capturas regeneradas en los 4 tamaños con el panel vacío, con datos de demo y
con datos al límite; `pytest -q` sigue en 27 OK + la FALLA conocida de `test_ui.py`. Las
capturas del panel vacío pesan 3.5–5.2 KB menos que antes (41–62 KB contra 47–66 KB) justo
por los dos elementos que ya no se pintan (chip y icono roto); eso no cambia el diagnóstico
de esa falla: el umbral de 60 KB se puso para capturas con partida.
