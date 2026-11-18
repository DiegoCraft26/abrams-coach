# Hipótesis del meta: cómo se cazan cosas raras sin engañarse

Fecha: 2026-11-10/11. Pedido de Diego: análisis histórico de parches, combinaciones raras,
«expertos en análisis» que busquen estrategias que los grupos de Deadlock no ven, y
módulos que se actualicen por parche con hipótesis y su porqué.

## La regla que ordena todo

Una combinación que gana mucho **no es un tesoro** hasta descartar que gane por ir ganando.
El primer barrido lo demostró: con 45 días de datos salían «Colossus + Magic Carpet»,
«Juggernaut + Magic Carpet», «Frenzy + Witchmail» con 64–67% de winrate. Todos eran el
mismo sesgo: **los ítems de 6,400 los compra quien ya iba ganando**.

Por eso cada hipótesis pasa por tres filtros antes de tocar el motor:

1. **Estrato** (`herramientas/tesoros.py`): cada combo se compara contra la mediana de los
   combos del mismo coste y del mismo minuto, no contra la media global.
2. **Cohorte** (`--max-networth`): se repite con jugadores que terminaron con poco oro.
   Si el combo solo brilla entre los ricos, es sesgo, no tecnología.
3. **Contraste con lo medido** (`coach/conocimiento.json`): el `lift_residual` del proyecto
   ya descuenta coste y minuto. Un candidato tiene que aguantar ahí también.

Si no hay explicación mecánica («compone a X», «resiste su daño», «da movilidad»), se
queda como **hipótesis en pruebas**, no como regla.

## Herramientas y cadencia

| Pieza | Qué hace | Cuándo |
|---|---|---|
| `herramientas/tesoros.py` | combos por estrato y cohorte desde la API | por parche o cada 2 semanas |
| `herramientas/meta_abrams.py` | qué se compra de verdad, con muestra | por parche |
| `herramientas/banco_partidas.py` | el motor sobre 626 partidas | con cada cambio de reglas |
| `herramientas/linea_tiempo.py` | una partida minuto a minuto | al depurar una hipótesis |
| `data/tesoros/*.json` | fotos fechadas para `--comparar` | cada corrida |

`tesoros.py --comparar <foto-anterior>` marca los combos **nuevos** respecto a la foto
guardada: eso es el cambio de parche visto con datos, sin depender de las notas.

## Hipótesis abiertas

| # | Hipótesis | Evidencia | Falsificación |
|---|---|---|---|
| H1 | **Scourge** está infrautilizado por el coach | Mejor `lift_residual` del catálogo (+6.1 pp, n=85k) y aparece arriba en combos por estrato | Si al meterlo en el camino el residual medio del banco baja |
| H2 | **Frenzy** es pieza de remontada | Entre jugadores que terminan con ≤25k gana 37–40% vs ~19% de la cohorte | Si el efecto desaparece al controlar por net worth intermedio |
| H3 | **Magic Carpet / Colossus** son «tesoros» falsos | Desaparecen al mirar solo la cohorte pobre | Si sobreviven a los tres filtros |
| H4 | **Extra Regen** ya no es meta | No compone ningún ítem (`data/componentes.json`); su presencia es popularidad temprana, no progresión | Si su residual sube al controlar por minuto |
| H5 | **Metal Skin** es compra de perdedor | 40% de winrate con mucha muestra | Si sube al controlar por duración y oro |

H4 ya está aplicada a medias: la apertura de `data/meta_abrams.json` pondera «progresa»
(1.0 si compone algo, 0.60 si no), así que Extra Regen queda tercero y no primero.

## Lo que costó y lo que hay que vigilar

- La **cobertura** (±1 min) bajó de 13.8% a 9.3% con la apertura nueva. Es esperado: mide
  parecido con lo que la gente compra, no calidad. Un build mejor pero distinto baja ese
  número. En `tests/test_banco.py` se vigila que no caiga a cero, no que sea alto.
- La API acepta `min_unix_timestamp`, así que un «parche» se puede medir como ventana de
  fechas. Falta automatizar la lista de parches (fechas de parche no vienen en la API).
- Los combos de 3 tardan más en tener muestra suficiente (usar `--min-matches 150`).
