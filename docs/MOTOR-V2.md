# Motor v2: el valor medido de cada compra

Qué cambia, por qué, cómo se reproduce y qué **no** se puede afirmar todavía. Si algo de
aquí no coincide con el código, manda el código y este documento está mal: ábrele un
issue con la versión (`abrams-coach estado`).

## En una línea

Cada compra de Abrams en 20 500 partidas reales se usa para estimar **cuánto sube la
probabilidad de ganar comprar ese ítem en ese estado, contra la compra alternativa**, con
su intervalo y su muestra; y el panel lo enseña solo cuando hay evidencia suficiente.

## De dónde salen los números

| Pieza | Archivo | Qué hace |
|---|---|---|
| Corpus | `herramientas/lab/corpus.py` | Lee `datos/lab.db`, reconstruye el inventario al momento de cada compra y **congela** los conteos con el hash de la base |
| Estimador | `herramientas/lab/estimador.py` | AIPW + modelo logístico del desenlace + bootstrap agrupado por partida → `datos/modelo_v2.json` |
| Verdad conocida | `herramientas/lab/sintetico.py` | Genera un corpus donde el efecto se elige, para medir si el estimador miente |
| Puertas | `herramientas/lab/validar.py` | Sesgo, cobertura, falsos positivos y sensibilidad a un confusor |
| Consumo | `coach/valor.py` | Lee el artefacto, valida el hash y sirve la evidencia al motor y al panel |

```bash
python3 herramientas/lab/corpus.py                       # congela el corpus (hash + conteos)
python3 herramientas/lab/estimador.py --bootstrap 200    # escribe datos/modelo_v2.json
python3 herramientas/lab/validar.py --repeticiones 20    # puertas G1-G3 sobre sintético
python3 -m pytest -q tests/test_estimador.py tests/test_valor.py
```

## Qué se mide exactamente

El estimando **no** es «P(ganar si compro X)». Es la diferencia contra la compra
alternativa del shortlist:

```
τ(e, a) = E[ Y(a) − Y(ã) | franja = e ]
ã       = la compra que se habría hecho en ese estado (media del shortlist)
```

Se estima con AIPW (doblemente robusto: vale si acierta el modelo del desenlace **o** la
propensión), propensión por conteo suavizado sobre el shortlist de cada franja, y
bootstrap que remuestrea **partidas** —nunca compras— reajustando los dos modelos en cada
réplica. Ese último detalle importa: con los modelos fijos el intervalo salía demasiado
estrecho (cobertura 83 % y 20 % de falsos positivos, medido).

El efecto se agrega **por ítem**, no por celda. La razón está medida: de 3 257 pares
(franja, ítem) solo 6 alcanzan la muestra necesaria para detectar 2 pp; la mediana de los
pares con n ≥ 30 necesita 14.9 pp para detectarse. Estratificar más no compra precisión,
la vende.

## Qué se enseña en el panel

Cinco campos, y si falta uno no se pinta:

```
{ efecto_pp, ic90: [bajo, alto], n, n_partidas, etiqueta, parche }
```

Etiquetas, por número de compras del ítem:

| Compras | Etiqueta | ¿Se muestra? | ¿Decide? |
|---|---|---|---|
| ≥ 2 149 | `medido` | sí, con IC y n | sí (solo como evidencia) |
| 150 – 2 148 | `preliminar` | sí, con IC y n | no |
| 40 – 149 | `debil` | solo el signo y su MDE | no |
| < 40 | `sin_senal` | **nada** | no |

## G4: ¿puede reordenar la recomendación?

Se midió el 2026-11-18 con corte temporal 60/20/20 por partida. Dos resultados, uno que
no decide y otro que sí:

- **Comparación de políticas con el estimador SNIPS: no concluyente.** Modelo 0.5532
  contra popularidad 0.5482 (winrate del test 0.532); diferencia +0.0054 con IC90
  [−0.0093, +0.0216] y ESS del 4 %. La política observada da 0.5314, que es su winrate:
  el estimador está sano, pero con esa varianza no distingue una política mejor de una
  moneda.
- **Replicación fuera de muestra: sí concluyente.** Spearman train vs test **0.796** y
  acuerdo de signo **90.5 %** (19 de 21). Spellbreaker y Hunter's Aura cambian de signo:
  esos no pueden mandar.

Por eso el motor publica `decision.desempate` («el laboratorio prefiere X») **solo** si
el ítem replicó su signo, su cota inferior supera +0.5 pp y la diferencia de score ya era
un empate. No se reordena: mover la recomendación exige mover a la vez el camino, la
venta, los componentes y las alternativas.

Informe completo: `informes/lab/G4-POLITICA.md`.

## Qué NO hace (y hay que decirlo)

1. **No identifica causalidad** si la habilidad no observada se correlaciona con lo que se
   compra. No hay MMR en la base (`badge` nulo en 88 %). Cada cifra sale con su E-value:
   con el corpus actual el mejor hallazgo tiene E-value ≈ 1.2, o sea que un confusor
   moderado lo explica entero. Por eso el panel no dice «mejora tu winrate».
2. **No reordena el ranking.** El artefacto se adjunta a la recomendación, el desacuerdo
   se anota en telemetría (`valor_desacuerdo`) y un empate puede llevar el aviso
   `desempate` si el ítem replicó fuera de muestra. G4 (ver arriba) no autorizó más.
3. **No reajusta la propensión con celdas finas**: son franjas de tiempo × riqueza ×
   inventario. Con celdas más finas cada una tendría una sola compra.
4. **Un solo parche y un solo día** en el corpus. Toda generalización temporal es una
   extrapolación, y el artefacto lleva su fecha para que se note.

## Modo CIEGO

Si `datos/modelo_v2.json` no existe, o su `sha256` no corresponde al corpus congelado, el
motor **no usa ningún número** de efecto: sigue recomendando con la heurística de siempre
y el panel no enseña evidencia. Es preferible quedarse sin el dato a enseñar el de otra
muestra. `coach/valor.py:modo()` lo dice, y `resumen()` lo publica para el diagnóstico.

## Las puertas

| # | Qué mide | Umbral | Cómo se corre |
|---|---|---|---|
| G1 | Sesgo absoluto medio del efecto | < 0.5 pp | `validar.py` |
| G2 | Cobertura del IC90 | 88 – 96 % | `validar.py` |
| G3 | Falsos positivos con efecto nulo | ≤ 8 % | `validar.py` |
| — | Sensibilidad a un confusor de habilidad | se publica, no es puerta | `validar.py` |

El resultado de la última corrida completa está en `informes/lab/VALIDACION-MOTOR-V2.md`.

## v3 y el techo de este diseño (2026-11-18)

Se probó el arreglo que faltaba: **comparar cada compra contra alternativas del mismo tramo
de precio** en la misma franja, en vez de contra el promedio del shortlist (que en franja 0
es 88.6 % ítems de 800–1 600).

| Ítem | τ franja 0 antes | después |
|---|---|---|
| Crushing Fists | +14.04 | **+2.01** [+0.89, +3.02] |
| Colossus | +13.65 | +0.06 (n=7) |
| Phantom Strike | +11.83 | −2.06 |
| Restorative Shot | −3.18 | −0.73 |
| Extra Regen | −3.38 | −1.00 |

La conclusión que importa: **el +14 pp era «gastar 6 400 temprano contra relleno de 800»,
no el ítem**. Al quitar ese escalón, los efectos residuales son pequeños y **no replican**:
11 de 21 ítems cambian de signo y la réplica fuera de muestra cae de 0.816/0.857 a
0.577/0.762; solo 7 de 21 tienen IC90 agregado que excluye cero (antes 15).

**Con este corpus no se puede publicar un ranking de ítems.** Lo que queda honesto es:
camino por héroe (heurística medida contra partidas), reglas de ritmo y participación, y
la evidencia apagada. Para volver a encenderla hace falta lo que este diseño no tiene:
oro real en el instante de la compra (`CurrencyChangedEvent` de las demos) y alternativas
que el jugador **podía pagar**. Informe: `informes/lab/MOTOR-V3-COMPARABLES-2026-11-18.md`.

## Cierre del frente de ítems (2026-11-18, 20 parches)

Se hizo la prueba que faltaba, con la serie temporal completa: **63 680 compras de Abrams
en modo Normal, 3 988 partidas, 20 parches** (`datos/corpus_parches.csv.gz`, de
`datos/historico.db`). Estimador: plug-in con LPM, bins flexibles de minuto y net worth, SE
agrupado por partida; AIPW descartado porque `ê ≈ 1/menú` en este diseño.

| Prueba | Resultado |
|---|---|
| Efecto agregado (97 ítems) | 10 más comprados entre **−1,26 y +2,22 pp** |
| IC95 que excluye 0 | **13 de 97** (por azar y con la tasa real de FP se esperaban 7–11) |
| Réplica temporal 60/40 | Spearman **0,091** · signo **55,6 %** · top-10 **2/10** |
| Placebo del mismo periodo (300 splits) | Spearman **0,159** · signo 57,5 % |
| Heterogeneidad entre parches | `sd(τ)/SE = 1,03` · Q p mediana 0,49 → **ningún ítem es «de un parche»** |
| Inyección de efecto conocido (6 pp) | el estimador recupera **29–54 %** (atenúa a la mitad) |
| MDE real | **5–7 pp** agregado · **20–55 pp** por parche |

**Conclusión: no hay ningún ítem con efecto demostrado, y el ranking no replica.** No es
que el meta cambie entre parches —no hay exceso de heterogeneidad—, es que **~200 partidas
de Abrams por parche no alcanzan**. Para responder «¿este ítem funciona en este parche?»
harían falta dos órdenes de magnitud más de datos, y aun así el efecto tendría que ser
grande.

Lo que el panel puede seguir haciendo, y es lo que hace: **camino por héroe** (heurística
medida contra partidas), **reglas de ritmo y participación** (validadas en 3 538 partidas),
**aviso de riesgo** y **la nota de después**. Lo que no: enseñar «evidencia» por ítem.
Ese frente queda cerrado con datos, no por pereza. Informe:
`informes/lab/PARCHES-MODELO-2026-11-18.md`.
