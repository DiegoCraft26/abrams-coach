# Scoring por contexto

Que el peso de cada factor dependa del estado (fase, almas, composición, inventario) sin
volver errático al motor. Sin ML nuevo ni datos nuevos: se mueven los pesos que ya existen.

## Lo que hay hoy (medido 2026-11-08)

Reproducido con `python3 herramientas/evaluar_motor.py --partidas 200 --max-estados 3000`
sobre `data/replay_cache.json` (200 partidas, 2,157 estados), el mismo comando de
`docs/MEDICIONES.md`: residual top-1 **+0.0553 pp** · diversidad **21** · estabilidad
**70.6 %** · latencia **5.55 ms** medio / 8.06 ms máx.

1. Los 10 pesos son constantes: el mismo ítem suma lo mismo en cualquier minuto, economía y
   composición, y el coeficiente que ve el jugador (`lift_residual` de 1.9 M de partidas) es
   propiedad del ítem: en 300 estados ningún ítem del top-1 mostró dos (medido: 0 de 9).
3. Yendo 12 % atrás en almas el top-1 no cambia en **0.0 %** de 300 estados (medido); yendo
   12 % arriba cambia en 13.3 %. El déficit solo entra por el castigo de recuperación, que
   toca el coste, no el ranking.
4. `herramientas/evaluar_motor.py:60` arma el estado con `i["t"] <= t`: el ítem comprado en
   ese segundo ya está en el inventario y no puede recomendarse, así que `acierto` y
   `en_top3` dan **0.0 %** siempre (medido). Un carácter (`<`) recupera dos métricas; hasta
   entonces no las uses como criterio.

## La fórmula

Cinco ganancias: 1.0 en contexto neutro, acotadas a [0.60, 1.40], todas rampas lineales (sin
escalones, sin azar, sin tablas por héroe).

```
# contexto, dentro del bloque de 10 s que ya usa el motor (motor.py:256)
fase_pct = t_efectivo / duracion_tipica_s * 100      # 0..100
d        = economia.delta_pct                        # (mías - media enemiga) / media enemiga
señales  = situacionales.señales_composicion(heroes_enemigos)   # ya existe

early    = clip(1 - (fase_pct - 25) / 25)   # 1 hasta el 25 %, 0 desde el 50 %
late     = clip((fase_pct - 45) / 25)      # 0 hasta el 45 %, 1 desde el 70 %
atras    = clip(-d / 0.10)                 # 0 parejo o arriba · 1 yendo 10 % atrás
adelante = clip( d / 0.10)
comp     = clip(max(señales.values()) / 3) # 0..1, cuántos enemigos justifican un tag

g_lift    = 1.25 - 0.35*comp - 0.25*atras + 0.10*adelante   # 0.65 .. 1.35
g_counter = 0.70 + 0.45*comp + 0.15*early                   # 0.70 .. 1.30
g_precio  = 0.95 + 0.45*atras - 0.25*adelante               # 0.70 .. 1.40
g_cadena  = 1.25 - 0.25*late - 0.20*atras + 0.15*adelante   # 0.80 .. 1.40
g_venta   = 0.75 + 0.50*late                                # 0.75 .. 1.25

# aplicación: se multiplica el peso existente, no se agregan términos
score_base = la fórmula de hoy, sin tocar
score_din  = la misma con w_lift*g_lift, w_counter*g_counter, w_precio*g_precio,
             w_cadena*g_cadena (también sobre w_flujo) y w_venta*g_venta
score      = score_base + clip(score_din - score_base, -1.0, +1.0)
```

Por qué cada una: **lift** baja con composición cargada y yendo atrás (el promedio de 1.9 M
de partidas describe a otro jugador) y sube algo yendo arriba, que es cuando sí aplica.
**counter** sube con composición y en la fase temprana, cuando el matchup decide la línea.
**precio** sube yendo atrás (cada alma pesa) y baja yendo arriba (gastarla es correcto).
**cadena** sube temprano y arriba, y baja en el cierre, cuando el grafo del build ya no dice
nada. **venta** sube en el cierre: slots llenos y vender cuesta más.

El clip de ±1.0 lo convierte en desempate y no en volantazo: el hueco top-1/top-2 medido es
1.21 puntos de media (mínimo 0.03), así que solo se mueven decisiones ya casi empatadas.

## Por qué no baile

1. Todo es continuo: cruzar 25 %, 45 % o 10 pp de déficit no produce ningún salto.
2. El reloj ya va en bloques de 10 s (`motor.py:256`): dos lecturas del mismo momento dan
   exactamente el mismo número.
3. Nada de azar: sigue siendo una función determinista del estado (invariante 3 intacta).
4. Δ acotado a ±1.0 y ganancias a ±40 %: el cambio de score entre lecturas seguidas queda
   por debajo del `margen` (0.8) y del escape de quietud (+3.0) del `Estabilizador`, que no
   se toca (10 s de quietud, 2 lecturas).
5. La composición enemiga no cambia en la partida: sus ganancias son constantes de partida.
6. Medido: 200 estados reales, reloj +5 s por lectura, 13 lecturas, almas enemigas ±3 % y el
   `Estabilizador` en el bucle → **0 cambios de top-1**, igual que hoy (0 de 200).

## Cómo se verifica

```
cd abrams-coach
/tmp/dlvenv/bin/python -m pytest -q     # 27 OK + test_ui (fallo ambiental conocido)
/tmp/dlvenv/bin/python herramientas/evaluar_motor.py --partidas 200 --max-estados 3000 --etiqueta base
# la misma corrida con la config nueva: --etiqueta dinamico, y comparar las dos salidas
/tmp/dlvenv/bin/python herramientas/escenarios_motor.py      # 8 escenarios sintéticos
```

Y dos pruebas que el evaluador no cubre, hoy en `/tmp/bamboleo2.py` (estado congelado con
reloj y almas enemigas moviéndose) y `/tmp/contexto.py` (mismo estado, tres economías); si se
adopta la fórmula, van a `herramientas/`. Medido con ella y `w_fase` en 0:

| Config | residual | diversidad | estabilidad | top-1 cambia atrás | top-1 cambia arriba | latencia |
|---|---|---|---|---|---|---|
| actual | +0.0553 pp | 21 | 70.6 % | 0.0 % | 13.3 % | 5.55 ms |
| propuesta, Δ ±1.0 | +0.0558 pp | 18 | 70.2 % | 11.3 % | 24.0 % | 6.11 ms |
| propuesta, Δ ±2.0 | +0.0552 pp | 19 | 68.8 % | sin medir | sin medir | 6.2 ms |

Criterio de no-regresión —si falla cualquiera de los seis, se revierte:

1. residual medio top-1 ≥ 0.0550 pp (base 0.0553, tolerancia −0.0003).
2. estabilidad ≥ 69.0 % (tolerancia −1.6 pp) **y** bamboleo = 0 cambios en 200 estados. El
   bamboleo es criterio duro; la estabilidad del evaluador es un proxy y cae ~1 pp con
   cualquier reordenamiento, porque mide el orden entre compras consecutivas, no el panel.
3. diversidad ≥ 18. 4. alcanzable 100 % e `tests/test_invariantes.py` 6/6 en verde.
5. latencia media ≤ 8 ms y máxima ≤ 15 ms (base 5.55/8.06; propuesta 6.11/9.75).
6. sensibilidad entre 5 % y 35 % yendo 12 % atrás: 0 % = la fórmula no entra; >35 % = el
   clip está mal puesto y reescribe el ranking.

`pytest` completo no sirve como criterio: `tests/test_ui.py::test_suite` ya falla por
ambiente (capturas 5-13 KB por debajo de 60 KB). Se compara contra 27 OK + ese fallo.

## Qué borrar (sin perder calidad)

1. `_es_mejora_de()` (`motor.py:122-125`) y la variable `mejora`: siempre `False`. Queda
   `if libre <= 0:` y se van 4 líneas. Ídem `economia()["media_aliada"]` (`motor.py:90`),
   `ventana_fase` (`motor.py:62`, `config.py:39` y `:89`) y el `flex` de `_cap()`: nadie los
   lee (verificado) y `flex` está fijo en 0.
2. `_fase_fit()` (`motor.py:128-132`) y `w_fase` (`motor.py:375`): duplican `w_tiempo`, las
   dos miden `|t_rel - min_compra|`. Medido con `--config '{"w_fase": 0.0}'`: residual
   **+0.0557** (mejor que +0.0553), estabilidad igual (70.6 %), diversidad 18.
3. `sugerir_venta()` (`motor.py:418-478`, 60 líneas): recalcula el scoring con solo residual
   y counter, ignorando fase, flujo, cadena, presupuesto y contexto, así que puede
   contradecir al ranking. Sale de las filas de `candidatos()` (ya traen coste, slot y score)
   contra el peor vendible del slot lleno: una fórmula en vez de dos.
4. El bloque `objetivo` de `recomendar()` (`motor.py:493-509`): repite el filtrado con otra
   regla (`dist > 30`). Sale de la lista ya calculada: primer candidato con `costo > almas`.
5. `coach/modelo.py` (84 líneas) y `herramientas/datos/entrenar.py`: regresión logística que
   la app no importa. Congelarla o borrarla: es el "ML nuevo" que este documento evita.
6. Rampas superpuestas del minuto 10: `peso_apertura()` (480-720 s) y la interpolación de
   `fase_flujo()` corrigen el mismo escalón del QA. Con una alcanza; falta medir cuál
   sostiene la invariante de los 10 s (sin medir).
7. Dos interruptores para lo mismo: `contexto_activo` (`motor.py:68`) y
   `flags.patrones_nuevos` (`run.py:518`). Uno.

Para que el jugador lo vea: cada fila lleva `peso_lift` (la ganancia aplicada) y `coef_pp` =
residual en pp × `g_lift`; el panel muestra ese número y una línea del motivo ("peso
ajustado: vas 12 % atrás"). El coeficiente deja de ser constante por ítem.

No se hace: pesos aprendidos, bandits o regresiones nuevas; ruido aleatorio para "parecer
vivo" (dos consultas del mismo estado darían distinto y se rompe la invariante 3); tocar
`data/conocimiento.json` o reentrenar el lift.
