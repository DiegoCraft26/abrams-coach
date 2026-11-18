# Investigación del meta de Abrams — 2026-11-11

Objetivo: separar señal de sesgo en los candidatos del meta y decidir qué entra al motor.
Datos: `api.deadlock-api.com` (`item-permutation-stats`, `item-stats`, `hero-stats`),
caché en `data/api_cache/`. Cohorte «pobres» = `max_networth=25000`.

## Método

Para cada ítem candidato se mira:

- **wr propio**: winrate de Abrams cuando lleva ese ítem.
- **mejor par**: el combo con mejor winrate que lo contiene.
- **ventaja socio**: winrate(par) − winrate(socio individual). Si ≈ 0, el combo es el
  ítem arrastrando, no sinergia.
- **cohorte pobre**: repetir todo entre jugadores que terminaron con ≤25k. Si el ítem
  solo gana entre los ricos, es el sesgo de «voy ganando y compro caro».

## Resultados (pares, muestra ≥200, 45 días) — SUPERADO por la corrección

> Ojo: esta tabla es el **primer** corte (suma de pares). La sección «Corrección
> importante» la invalida: el residual ajustado dice lo contrario para Scourge y Frenzy.
> Se deja como registro de cómo se llegó al método bueno.

| Ítem | Global | Cohorte pobre (base 29.0%) | Veredicto |
|---|---|---|---|
| Scourge | 59.6% | **20.1%** | *Rechazado en este corte* — luego la regresión lo rehabilita (ver corrección) |
| Frenzy | 56.8% | **34.7%** (+5.7 pp sobre base, +10.0 vs su socio) | **Sobrevive**: único que sube en las dos cohortes |
| Magic Carpet | 60.2% | 15.9% | Rechazado: jugador rico, partida larga |
| Colossus | 59.6% | 27.8% | Rechazado: igual que Magic Carpet |
| Metal Skin | 42.1% | 10.4% | Trampa confirmada: se compra cuando vas perdiendo |
| Superior Duration | 55.1% | 18.3% | Normal: es el core del build, no un tesoro |
| Bullet Resist Shredder | 52.9% | 23.3% | Normal |

El caso de Scourge es el más instructivo: tenía el mejor `lift_residual` del catálogo
(+6.08 pp) y salía primero en el barrido simple. Al mirar solo a los que terminan pobres
cae a 20.1% con base 29% → **el residual alto viene de que lo compra quien ya ganó**.

## A/B en el banco

Se añadió `ABRAMS_FORZAR="id1,id2"` (en `coach/decision/camino.py`): mete esos ítems al
camino después de la apertura y el resto del build se reacomoda. Sirve para medir una
hipótesis sin tocar código, y desaparece si la variable no está definida.

Intento con Frenzy (`339443430`), 120 partidas:

| Métrica | Base | Frenzy forzado |
|---|---|---|
| residual medio top1 | +0.0288 pp | +0.0286 pp |
| estabilidad | 67.8% | 65.9% |
| en top3 vs compra real | 12.3% | 12.8% |
| latencia | 6.29 ms | 6.32 ms |

**Conclusión del A/B: nulo.** Forzar Frenzy no degrada el motor, pero el evaluador no
mide victorias, así que no prueba que sea mejor. Frenzy entra al camino solo cuando la
partida llega a 6,400 de arma, que es tarde en el 80% de los estados medidos.

## Control de duración (cohorte pobre)

Misma cohorte pobre, partiendo por duración de la partida (base = winrate de Abrams en
esa ventana):

| Ventana | Base | Frenzy | Scourge |
|---|---|---|---|
| todas | 29.0% | 36.7% (n=7,039) | 20.4% (n=2,402) |
| 20–40 min | 22.8% | 35.3% (n=6,715) | 18.1% (n=2,311) |
| 30–40 min | **7.6%** | **16.2%** (n=1,070) | sin muestra |

Frenzy sobrevive al control: en partidas de 30–40 min con jugadores que terminaron con
≤25k, quien lo lleva gana **2.1× la base**.

## Control por tramo de precio (pobres, 30–40 min)

Si el efecto fuera «compró caro porque tenía oro», todos los 6,400 se verían igual. No:

| Tramo | Mediana del tramo | Mejor del tramo |
|---|---|---|
| 800 | 4.8% | Headshot Booster 18.8% (n=1,113) |
| 1,600 | 4.0% | Swift Striker 16.2% (n=1,357) |
| 3,200 | 3.0% | Bullet Resilience 8.1% (n=24,080) |
| 6,400 | 3.3% | **Frenzy 18.2%** (n=1,211) · Juggernaut 12.6% |

Frenzy es el mejor de su tramo por 15 puntos sobre la mediana. Es el candidato más sólido
que ha salido del análisis. Con la misma lógica aparecen Headshot Booster y Swift Striker,
que el coach tampoco usa — quedan como hipótesis nuevas (H6, H7).

## Corrección importante: la agregación por pares engañaba

El veredicto anterior (Scourge malo, Frenzy bueno) salió de sumar pares, y eso **cuenta
doble a los ítems con muchos socios y no controla el minuto de compra**. El residual
ajustado (`herramientas/residuales.py`: logit(winrate) ~ log(coste) + minuto, ponderado
por muestra) dice lo contrario:

| Ítem | Todos | Reciente | Pobres 30–40 min |
|---|---|---|---|
| **Scourge** | +4.19 pp · 4.º/153 | +3.93 pp · 6.º/152 | **+8.12 pp · 4.º/148** |
| Frenzy | +1.49 pp · 40.º | +1.97 pp · 33.º | +1.86 pp · 45.º |
| Headshot Booster | −7.23 pp · 131.º | — | — |
| Swift Striker | −9.10 pp · 140.º | — | — |

O sea: **Scourge es el candidato real y Frenzy era un artefacto** del agregado por pares.
Headshot Booster y Swift Striker, que en el corte crudo parecían oro, caen al fondo al
controlar coste y minuto. Por eso la regla del proyecto es el residual, no el winrate.

## A/B con Scourge (120 partidas reales, top1)

Se corrigió el forzado para que el ítem entre en el sitio que le toca por su `min_compra`
y desplace la pieza más floja de su slot (no se mete en el paso 4):

| Métrica | Base | Scourge |
|---|---|---|
| residual medio top1 | +0.0351 pp | **+0.0357 pp** |
| estabilidad | 63.2% | **67.5%** |
| diversidad | 32 | 29 |
| en top3 | 12.6% | 12.1% |

No degrada nada y mejora estabilidad. Con la regla de decisión (sube en cohorte pobre,
ventaja de socio, aguanta duración, A/B sin daño) **Scourge pasa las cuatro**.

## Bug encontrado por el A/B

El «último recurso» de `_objetivo` no aplicaba `_elegible`, así que podía recomendar un
6,400 antes del minuto 15. El A/B lo contó **1,064 veces** en 48,701 muestras. Corregido:
el banco vuelve a 38–125.

## El mecanismo de Scourge (por qué gana)

Del catálogo real (`data/items.json`): Scourge es **spirit tier 4, activo, se puede lanzar
sobre un aliado o sobre uno mismo**. Da:

- +40 de resistencia spirit, +20% de resistencia a debuffs y +100 de vida;
- un aura de 10 m sobre el objetivo que hace daño **proporcional a la vida máxima** del
  enemigo (2.3% por segundo durante 10 s) y **reduce los debuffs existentes**;
- 35 s de cooldown.

No es un ítem de daño personal: es un ítem de pelea de equipo y anti-control. Para Abrams
—que vive en el centro de la pelea— tiene sentido: se lanza sobre él o sobre el carry,
aguanta el burst mágico y castiga a los tanques por vida máxima. **No es un error de
calibración**: el residual alto tiene un porqué mecánico coherente.

## Ventanas de parche (histórico)

Mismo residual, dos ventanas de 16 días:

| Ventana | Scourge | Frenzy |
|---|---|---|
| 11–27 oct | +4.50 pp · 4.º/150 (n=44,066) | +1.08 pp · 51.º (n=16,868) |
| 27 oct–11 nov | +3.92 pp · 6.º/152 (n=55,684) | +1.83 pp · 36.º (n=18,947) |

Scourge se mantiene arriba en las dos ventanas; Frenzy sube un poco pero sigue a media
tabla. Y las «trampas» son estables: Decay, Disarming Hex y Toxic Bullets repiten
−13 a −16 pp en ambas (ítems anti-curación/anti-control que se compran cuando vas
perdiendo: es el sesgo conocido, no una señal nueva).

## Triples (sinergias)

18,658 triples de la cohorte pobre, filtrados a ≤1 ítem de 3,200+ (para no volver a
premiar «tres caros»):

| Ventaja sobre el mejor individual | n | Combo |
|---|---|---|
| +2.27 pp | 3,618 | Enduring Speed + Hunter's Aura + Return Fire |
| +2.23 pp | 4,471 | Hunter's Aura + Extra Regen + Return Fire |
| +5.98 pp | 182 | Melee Charge + Crushing Fists + Extended Magazine |

Las de muestra grande apenas pasan +2.2 pp: **no hay sinergia triple fuerte** con estos
datos. Las de +5 pp tienen n<200 y no aguantan una decisión. Return Fire aparece en las
dos mejores con muestra grande, pero su residual individual es negativo: queda como
hipótesis, no como regla.

## Lo que falta (siguiente ronda)

0. **Modelo de regresión** (logística con presencia de ítem, duración y net worth) en vez
   de la agregación por pares, que cuenta doble a los ítems con muchos socios.
1. **Triples** (`comb_size=3`, 162k combos descargados): buscar sinergias que no aparezcan
   en pares. Ojo con el tamaño de muestra: `--min-matches 150`.
2. **Control por duración para Frenzy**: repetir la cohorte pobre con
   `min_duration_s=1800&max_duration_s=2400` para descartar el efecto «partida larga».
3. **A/B con impacto**: usar `item-stats` con `hero_build_id` (builds publicadas) para
   comparar winrate de builds que incluyen Frenzy vs las que no, controlando por rango.
4. **Ventanas de parche**: `tesoros.py --desde/--hasta` con dos ventanas y `--comparar`.

## Regla de decisión

Un ítem entra al build solo si: (a) sube en la cohorte pobre, (b) su ventaja_socio > +3 pp,
(c) aguanta el control de duración, y (d) el A/B no degrada estabilidad ni residual.
Hoy solo Frenzy va por (a) y (b); falta (c) y (d) con una métrica de victoria.
