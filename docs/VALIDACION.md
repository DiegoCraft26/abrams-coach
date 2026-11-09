# Validación con partidas reales

Fecha: 2026-11-06. Sin jugar: se rejuegan compras reales de Abrams desde
`api.deadlock-api.com`.

## Cómo funciona

`coach/evaluador.py` baja partidas recientes con Abrams, reconstruye en cada compra el
estado (minuto, oro, ítems propios, composición enemiga) y compara lo que el motor
recomienda con lo que el jugador compró.

`herramientas/datos/optimizar.py` busca pesos contra ese juez; `herramientas/calibracion/replay.py` imprime ejemplos de desacuerdo.

## Resultado 1: imitar al jugador es la métrica equivocada

| Intento | Acierto top-1 | Acierto top-3 |
|---|---|---|
| Predecir el ítem exacto que compró el jugador | **0.0%** | **0.0%** |

No es un bug: es que los jugadores no compran el ítem de mayor valor. Compran lo que su
build, su costumbre y su oro disponible permiten. Además el oro reconstruido desde
`net_worth` es una estimación gruesa (la API da 10 muestras por partida).

Conclusión: **imitar no mide calidad**, mide popularidad.

## Resultado 2: el lift residual sí predice ganar

Se comparó el residual medio de los ítems comprados después del minuto 10, entre
partidas ganadas y perdidas:

| Grupo | Partidas | Residual medio |
|---|---|---|
| Ganadas | 50 | **+2.78 pp** |
| Perdidas | 63 | **+2.30 pp** |
| Diferencia | — | **+0.48 pp** |

Prueba de permutación (2,000 remuestreos): **p = 0.0015**.

Es una señal real y estadísticamente significativa, pero **modesta**: el residual explica
poco del resultado. Un coach de ítems no sustituye a jugar mejor.

## Resultado 3: cuánto mejora la decisión

Sobre 114 compras comparables:

| | Residual medio |
|---|---|
| Lo que recomienda la app | **+4.57 pp** |
| Lo que compró el jugador | **+2.27 pp** |
| Ventaja teórica | **+2.29 pp por compra** |

La app elige un ítem de mayor residual que el jugador en **88%** de las compras.

Advertencia honesta: ese +2.29 pp es sobre *nuestra* métrica, que a su vez vale +0.48 pp
de diferencia entre ganar y perder. La mejora esperada en winrate es pequeña, no
transformadora.

## Bugs estructurales encontrados y corregidos en estas rondas

1. **Ítems comprados sin datos** ocupaban slots en la simulación → el motor veía el
   inventario lleno y no recomendaba nada.
2. **Slots llenos**: el motor descartaba candidatos en vez de proponer venta. Ahora
   permite el cambio y lo explica.
3. **Cobertura**: solo 120 de 250 ítems tenían datos; al bajar el mínimo a 200 partidas
   subió a **153**, con contracción por muestra para no sobrevalorar ítems raros.
4. **Filtro de fase duro** excluía compras reales; se cambió por un castigo proporcional
   a la distancia con el minuto típico de compra.
5. **Término de counter sin techo**: un matchup ruidoso dominaba el ranking. Ahora está
   acotado a ±4 pp y ponderado por muestra.

## Resultado 4: el modelo aprendido no superó a las reglas

Se entrenó una regresión logística (8 rasgos, 255 combinaciones probadas, búsqueda de
hiperparámetros hasta 255 ciclos) sobre **135 partidas: 180 en caché, 60 del perfil de
la máquina de desarrollo** y 429 compras.

| Modelo | AUC en test |
|---|---|
| Regresión logística, 135 partidas | **0.588** |
| Regresión logística, 410 partidas y 1,294 compras | **0.596** |
| Regresión logística, **520 partidas** (490 de Diego) y 1,577 compras | **0.576** |
| Reglas actuales | comparable y explicable |

Los pesos aprendidos incluso contradicen el dominio (counter con signo negativo), señal de
confusión y muestra escasa. **Decisión: no se adopta.** Queda en `coach/modelo.py` y
`entrenar.py` para volver a probarlo cuando haya 500+ partidas.

Más datos **empeoraron** el resultado (0.596 → 0.576): la señal es débil, no falta muestra.
Con 410 partidas el modelo solo retenía un rasgo (`tier`). En ningún corte superó a las
reglas de forma significativa.

Regla de calidad aplicada: un cambio que no mejora la métrica no entra, aunque sea más
sofisticado.

## Lo que sigue abierto

- El oro reconstruido es la mayor fuente de error del evaluador. Con lecturas reales de
  pantalla el oro es exacto, así que este problema desaparece en uso real.
- El objetivo del optimizador sigue sin resolverse: imitación no sirve y no hay
  contrafactual público. La alternativa sería medir su winrate real durante 40 partidas.
