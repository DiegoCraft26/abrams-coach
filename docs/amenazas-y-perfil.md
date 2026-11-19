# Amenazas, perfil de build y counters

Fecha: 2026-11-10. Pedido de Diego: «el coach tiende a ser general y siempre tiene una
build preestablecida; debería marcar personajes peligrosos del otro equipo para no
buscarlos solo y comprar counters, y ser más dinámico con las builds».

Tres piezas nuevas y una regla de convivencia entre ellas.

## 1. Amenazas (`coach/decision/amenazas.py`)

Compara las almas de cada enemigo contra la **media de tu equipo** (tú + aliados con
almas). No contra la media enemiga: así un rival que está dos ítems por delante no queda
diluido por los que van mal en su propio equipo.

| Nivel | Regla | Qué hace |
|---|---|---|
| `critico` | +35% o +8,000 almas | Se marca `evitar_solo` siempre |
| `alto` | +15% o +4,000 almas | `evitar_solo` si además va +25% o +2 bajas netas |
| `parejo` | resto | Sin marca |
| `flojo` | −20% o menos | Pelea ganable, se dice |

La ficha viaja al panel: chip rojo `EVITAR <HÉROE>` en la cabecera, fila teñida y etiqueta
`EVITAR` en la rejilla de enemigos, y el motivo («40,000 almas más que la media de tu
equipo (+50%)») en el tooltip.

Sin aliados con almas no hay comparación posible y se dice (`nivel: null`); no se
inventa una amenaza contra la media enemiga.

## 2. Counters atados a la amenaza (`coach/decision/situacionales.py`)

`bonus_contexto()` ya desbloqueaba ítems situacionales por composición. Ahora recibe la
lista de amenazas y multiplica su peso cuando el rival que justifica la señal es el que
va por encima: `critico ×1.6`, `alto ×1.25`. El motivo nombra al rival y su ventaja.

`camino._objetivo()` deja pasar el counter del crítico sin esperar la ventana de fase ni
el tope de precio del perfil: si ese rival está ganando la partida, se frena. El counter
de composición sigue siendo oportunista y barato (≤ 3,200): un tier 4 de 6,400 solo se
compra cuando el rival que lo justifica ya está ganando.

`contra_composicion` gana `urgente`, `contra_quien` y `peso_amenaza`, y los urgentes se
ordenan primero. El panel dice «frena a Haze: va por encima».

## 3. Perfil del camino (`coach/decision/perfil.py`)

`camino.construir()` cacheaba un único camino por héroe: la misma compra en las 50
partidas. Ahora el camino se construye con un perfil vigente, derivado del estado:

| Perfil | Cuándo | Efecto en el camino |
|---|---|---|
| `contra` | hay un enemigo `critico` | entra **un** counter de su kit; el resto sigue |
| `atras` | −10% de almas o menos | tope de precio 3,200 y los baratos primero |
| `arriba` | +10% o más | tope ampliado a 6,400: el spike se adelanta |
| `base` | partida pareja | camino histórico |

La **apertura no cambia** (`_base` sigue fijando las tres piezas de 800): lo que cambia es
lo de después, que es lo que se repetía partida tras partida.

La elección de cada paso mezcla frecuencia real del grafo (normalizada, peso 0.60),
economía del perfil (0.28) y balance de slots (0.12). Antes ganaba siempre la arista más
frecuente y el perfil no movía nada.

## Determinismo

Todo se calcula con el reloj en bloques de 10 s, el inventario y las almas: dos lecturas
del mismo momento dan la misma compra y el mismo camino (`tests/test_invariantes.py`,
18 consultas por estado). El perfil entra en la clave de caché del camino.

## 4. Estabilidad: el vaivén del oro

Medido con `herramientas/linea_tiempo.py` sobre 40 partidas reales, una muestra por
minuto. «Cambio de opinión» = cambia el objetivo **y** el anterior no se había comprado
(si se compró, es progreso del build, no un cambio de idea).

| Antes (build fijo de 9 pasos) | Ahora |
|---|---|
| 3.42 cambios de opinión por partida (1.02 por 10 min) | 3.17 (0.96 por 10 min) |
| «build completo»: 3.17 muestras por partida, máx 25 | **0** |
| Slowing Bullets: 113 muestras (top 5) | fuera del top 8 |

Dos causas del vaivén, las dos cerradas:

1. **El camino se acababa a los 9 pasos.** Con 9 ítems comprados y 12 huecos, el motor
   decía «build completo» al minuto 17 (visto en la partida 132719617, con 37k en el
   bolsillo). Ahora el camino tiene 12 pasos (los 12 slots), se rellena con lo mejor que
   quepa cuando el grafo se queda corto, y si aun así no hay nada dice la siguiente pieza
   del ranking en vez de «completo».
2. **El counter de composición competía con el camino.** Slowing Bullets aparecía como
   recomendación principal cada vez que dos enemigos eran móviles, y oscilaba con el oro
   («ahorra Hunter's Aura» ↔ «compra Slowing Bullets»). Desde el 2026-11-18 el counter
   de composición **entra en el camino como un paso más** (uno solo, marcado `counter`
   en la tira) y el panel no tiene caja aparte: una sola línea, sin consejos que se
   contradicen. Un 6 400 de composición no entra salvo que su rival sea `critico`.

## 5. Remontada

Yendo atrás (−10%) el camino se acorta a piezas de ≤3,200. Pasado el minuto 20 el perfil
se llama **remontada**: piezas baratas de impacto inmediato, nada de perseguir un 6,400
que no se paga, y nunca «build completa».

Lo que **no** hay todavía: un modelo entrenado con remontadas reales. `replay_cache.json`
solo guarda tu net worth, no el de los 12 jugadores, así que no se puede saber si ibas
perdiendo por equipo. La API sí trae `stats` por jugador (`/v1/matches/{id}/metadata`);
hace falta descargar una muestra con los 12 y reconstruir la curva de equipo para medir
«ítems que compran los que remontan». Es el siguiente paso, no algo hecho.

## Pruebas

`tests/test_amenazas.py`: 24 comprobaciones — nivel y alerta, perfil por economía, el
counter del crítico dentro del camino, inicio idéntico entre perfiles, y determinismo a
0 y 3 s.

## Lo que esto no hace (honesto)

- No mira el inventario de los enemigos para decidir el counter: usa su héroe y sus
  almas. El broadcast sí trae sus 12 ítems, así que es el siguiente paso natural.
- Los umbrales son criterio, no estadística del proyecto; están en `UMBRALES` para
  moverlos sin tocar lógica.
- La apertura sigue siendo fija a propósito.
