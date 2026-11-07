# Abrams Coach — informe de minería (v0)

Datos bajados y analizados el 2026-11-06 desde `api.deadlock-api.com`.
Todo reproducible: `python3 herramientas/datos/mineria.py && python3 herramientas/datos/analisis.py`.

## Base

| Dato | Valor |
|---|---|
| Partidas de Abrams | **1,945,004** |
| Winrate base de Abrams | **49.19%** |
| Ítems de tienda (type=upgrade) | 250 |
| Ítems con datos suficientes | 154 |
| Combinaciones de 2 ítems descargadas | 7,737 |
| Builds de Abrams con ≥150 partidas | 136 |
| Filas de counter Abrams vs 65 héroes | 1,892 |

## Hallazgo 1: el winrate crudo mide el estado de la partida, no el ítem

Correlación entre el lift de winrate de un ítem y su **minuto medio de compra**:

```
r = 0.483   (n = 109 ítems con ≥5,000 partidas)
pendiente = +0.110 pp por unidad de tiempo relativo
```

Casi una cuarta parte de la variación del winrate la explica **cuándo** se compra el ítem.
Los ítems de tier 4 (6,400 almas) solo se compran si ya vas ganando.

Prueba directa — lift medio por banda de costo:

| Banda | Pares | Lift medio |
|---|---|---|
| ≤4,000 | 386 | **+2.66 pp** |
| 4,000–8,000 | 671 | **+4.76 pp** |
| 8,000–14,000 | 347 | **+9.19 pp** |

El "mejor" ítem sube de calidad conforme sube el precio. Eso no es calidad: es supervivencia.

## Hallazgo 2: el ranking honesto es el lift residual

Lift residual = winrate observado − winrate que predice el minuto de compra.

### Mejores por residual

| Ítem | Residual | Crudo | Min. compra | n |
|---|---|---|---|---|
| Magic Carpet | **+6.66 pp** | +12.02 pp | 76 | 10,076 |
| Restorative Shot | **+5.03 pp** | +2.88 pp | 8 | **718,764** |
| Scourge | +4.97 pp | +10.91 pp | 82 | 85,444 |
| Escalating Exposure | +4.88 pp | +10.64 pp | 80 | 55,003 |
| Colossus | +4.81 pp | +10.70 pp | 81 | 295,331 |
| Slowing Bullets | +4.53 pp | +8.15 pp | 61 | 40,600 |
| Witchmail | +4.50 pp | +10.27 pp | 80 | 207,323 |

`Restorative Shot` es el hallazgo interesante: 800 almas, comprado al minuto 8 relativo,
**718,764 partidas** y aún así +5.03 pp por encima de lo esperado. Ese es señal, no ruido.

### Trampas confirmadas de Abrams

| Ítem | Residual | Crudo | n |
|---|---|---|---|
| Disarming Hex | **−15.82 pp** | −11.24 pp | 8,817 |
| Metal Skin | **−11.81 pp** | −6.62 pp | **51,646** |
| Titanic Magazine | −9.49 pp | −6.87 pp | 6,467 |
| Silence Wave | −8.97 pp | −3.77 pp | 6,350 |
| Cursed Relic | −8.96 pp | −2.78 pp | 11,199 |

`Metal Skin` con 51,646 partidas y −11.81 pp residual es la trampa más clara del héroe.
`Return Fire` aparece en 3 de los 3 peores pares baratos: nunca lo compres en Abrams.

## Hallazgo 3: pares con señal real (banda barata, controlada por costo)

| Par | Lift | n | z |
|---|---|---|---|
| Slowing Bullets + Bullet Resist Shredder | **+10.79 pp** | 24,362 | 33.7 |
| Stalker + Slowing Bullets | +9.71 pp | 23,295 | 29.6 |
| Compress Cooldown + Mystic Vulnerability | +9.08 pp | 22,792 | 27.4 |
| Melee Charge + Slowing Bullets | +8.57 pp | 39,194 | 33.9 |
| Slowing Bullets + Close Quarters | +8.51 pp | 37,772 | 33.1 |

`Slowing Bullets` aparece en 3 de los 5 mejores pares baratos. Es el eje del build temprano.

## Pendiente

- Combinaciones de 3 ítems: el endpoint devolvió 504 (timeout del servidor). Reintentar con
  `min_matches` más alto y `comb_size=3` aislado.
- Condicionar por composición enemiga (`enemy_hero_ids`) en los pares: eso convierte el
  ranking estático en counter real.
- Condicionar por `bucket` (rango): un par bueno en Eternus puede ser malo en Arcanist.
