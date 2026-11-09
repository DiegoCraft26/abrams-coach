# QA de comportamiento esperado

Fecha: 2026-11-08 · rama `wip/fixes-sesion-2026-11-08` · 6 escenarios con estados inyectados.

Nada de esto se probó jugando: los estados son sintéticos (armados con `data/conocimiento.json`,
`data/catalogo.json` y `data/componentes.json`) y se pasan por el mismo motor, el mismo
servidor y el mismo bucle que corren en partida. No se abrió el juego, no se tocó el
navegador, no se reinició nada de lo que está corriendo y el servidor de `127.0.0.1:8090`
no se tocó: los chequeos por HTTP abren un puerto libre aparte.

Arnés: `herramientas/qa_comportamiento.py` (32 comprobaciones, ~10 s, exit 0 si todo pasa).

```bash
cd .
/tmp/dlvenv/bin/python herramientas/qa_comportamiento.py              # los 6
/tmp/dlvenv/bin/python herramientas/qa_comportamiento.py --escenario 2 # uno solo
```

## Tabla

| # | Escenario | Esperado | Pasó | Comando | Veredicto |
|---|---|---|---|---|---|
| 1 | Extra Health en la mochila, 6,000 almas | Ofrecer Colossus pagando sólo la diferencia (5,600) y sin pedir venta | Colossus entra con `costo=5600` (`lista=6400`, `ahorro=800`), `requiere_venta=False`, `venta=None`, y la razón dice «aprovecha lo que ya llevas (Extra Health)». El motor lo deja **3.º de 10**; el panel enseña las 3 primeras, así que se ve | `--escenario 1` | **OK** (no es la primera recomendación: los ítems baratos puntúan más alto, 8.37 vs 6.42) |
| 2 | 4 slots de vitalidad llenos | Un upgrade entra igual; un ítem nuevo no entra sin venta | Con 4 de vitalidad (Extra Health, Sprint Boots, Grit, Extra Stamina): Colossus entra con `costo=5600` y `requiere_venta=False` (el upgrade devuelve el hueco). Witchmail entra **sólo** con `requiere_venta=True` y la app propone vender Grit. Con 4 ítems no vendibles, ningún ítem nuevo de vitalidad aparece en el ranking | `--escenario 2` | **OK** |
| 3 | Partida pausada (tick congelado) | El reloj del broadcast se congela; la app no avanza tiempo ni marca fresco | Se publica **un solo** estado con `t=900.0` y después un único aviso `listo=False` («el broadcast dejó de mandar datos (último tick 57600); reintentando»); nada se republica. En el servidor, republicar el mismo estado deja `edad_s` creciendo: `rancio=True` a los 1.4 s (umbral 0.6 s) y el tiempo del panel sigue en 900.0 | `--escenario 3` | **OK** |
| 4 | Partida terminada | Pasar a rancio y no seguir mostrando la última compra como actual | Con el último estado fresco (`edad=0.0`, `rancio=False`), al dejar de llegar datos la edad crece y `rancio=True`. El aviso final no lleva `recomendaciones` ni `compras`, así que la tarjeta pasa a «SIN PARTIDA» y el feed de compras se vacía (`coach/ui/componentes/recomendacion.py:67`, `compras.py:15`) | `--escenario 4` | **OK** |
| 5 | Determinismo vs. reloj | El mismo estado dos veces, la misma recomendación; 60 s de diferencia pueden cambiarla | Igual estado dos veces: ids, costos y scores idénticos, también con la capa de la app (estabilizador). Dos procesos distintos dan la misma huella. Con 60 s de diferencia (t=600 → t=660) la recomendación cambia: Melee Lifesteal → Slowing Bullets | `--escenario 5` | **OK** |
| 6 | Sin conexión al API | No colgarse y no mentir: decir qué falta | No se cuelga (`partida_activa` 0.00 s, `descubrir` 6.00 s, el bucle sigue publicando), pero **miente**: el descubrimiento dice «la cuenta <tu_cuenta> no está en ningún listado (0 partidas activas)» cuando no pudo consultar, el diario de red queda **vacío** (el diagnóstico no tiene nada que contar) y el panel recibe la apertura sin `listo=False`, o sea que la cabecera pinta «● en vivo» con «Build de apertura mientras llega el broadcast» | `--escenario 6` | **FALLA** (3 de sus 7 comprobaciones OK) |

Resultado global: **28/32 comprobaciones OK**, los 6 escenarios corridos; los 4 fallos son
del escenario 6 (3 de sus 7 comprobaciones pasan).

## Escenario 6: qué falla y por qué

Los cuatro síntomas son el mismo problema: **el fallo de red se pierde antes de llegar a
ningún sitio**, y lo que se muestra es el estado por defecto («no juegas», «partida
iniciando»), que es falso.

| Síntoma medido | Causa | Archivo:línea |
|---|---|---|
| `descubrir()` responde «la cuenta … no está en ningún listado (0 partidas activas)» | el mensaje se arma igual si la consulta falló que si de verdad no hay partida; `activas=0` es el valor de una consulta que nunca llegó | `coach/fuentes/api_vivo.py:127-129` |
| el diario de red queda vacío (`red.errores == []`) con `URLError` | `partida_activa`, `listado_activo` y `buscar_en_listado` atrapan `URLError/OSError` y devuelven `None`/`[]` sin anotar nada en `DIARIO` | `coach/en_vivo.py:241`, `:261`, `:287` |
| el bucle publica la apertura como si hubiera partida | cuando no hay `match` se publica `publicar_apertura()` sin `listo=False` ni motivo, y el bucle hace `continue` | `coach/run.py:61-68`, `coach/nucleo_vivo.py:103-121` |
| la cabecera dice «● en vivo» | sólo mira `listo is False` y `fuente == "simulado"`; un payload de apertura cae en la rama «en vivo» | `coach/ui/componentes/cabecera.py:43-60` |

Arreglos de una línea que **no apliqué** (los cuatro archivos están modificados en esta
misma rama por otro agente, y `run.py`/`nucleo_vivo.py` además cambian de firma en curso):

1. `coach/en_vivo.py`, en los tres `except`: anotar antes de devolver.
   `except (urllib.error.URLError, OSError, ValueError, ErrorCuota) as exc:` +
   `DIARIO.error(f"partida_activa: {exc}"); return None`.
2. `coach/fuentes/api_vivo.py:127`: si `activas == 0` y el diario tiene un error de red del
   último golpe, decir «no pude consultar la API: …» en vez de «no está en ningún listado».
   Esto ya son dos líneas y toca el texto del panel.
3. `coach/nucleo_vivo.py` `publicar_apertura`: añadir `"listo": False` y un `mensaje` con el
   motivo cuando no hay match. Cambia el comportamiento legítimo de «stream conectando», así
   que hay que decidir el texto, no es un parche ciego.
4. `coach/ui/componentes/cabecera.py`: la rama «en vivo» no debería pintarse con
   `fuente == "apertura"`.

Mientras eso no esté, lo único honesto que tiene la app es `/api/revisar`, y hoy tampoco
sirve: sin errores en el diario, el diagnóstico informa «sin errores» y «la cuenta no está
en ningún listado».

Ojo con el cruce: `docs/QA-integracion.md` (P1) ya señala que el bucle no usa
`api_vivo.descubrir` sino el `buscar_match()` viejo. Aquí, además, aunque lo usara, el
mensaje de esa capa tampoco distingue «no hay red» de «no estás jugando».

## Notas de lo medido

- Colossus (6,400) absorbe Extra Health (800): `costo=5600` en todos los casos probados
  (1, 5, 7, 8 y 12 mil almas). En ningún caso pide vender ni aparece en `venta`.
- Fortitude **no** es un ítem nuevo para este inventario: también absorbe Extra Health
  (ahorro 800). Para probar «ítem nuevo con slot lleno» hay que usar Witchmail, que no
  absorbe nada de lo puesto.
- Con el slot lleno y sin nada vendible en ese slot (Colossus, Witchmail, Phantom Strike,
  Unstoppable), ningún ítem de vitalidad entra al ranking: 107 filas con vendibles → 69 sin
  ellos.
- La invariante de los 10 s se sostiene: el mismo `t` da el mismo número, y el
  estabilizador sólo retiene un cambio durante 10 s de reloj de pared (`quietud_s`), que en
  partida son 10 s reales.
- La suite del proyecto sigue en el baseline conocido: 27 tests OK y
  `tests/test_ui.py::test_suite` fallando por las 3 capturas de 41–55 KB (ambiental, no se
  tocó).
