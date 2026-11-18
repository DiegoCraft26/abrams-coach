# Banco de partidas: probar el motor contra 626 partidas sin abrir el juego

Fecha: 2026-11-10. Pedido de Diego: «¿no puedes testear múltiples partidas de toda la
partida y así siempre? ¿usar el meta de Abrams para ver outliers o cosas infrautilizadas?
¿automatizar el testeo local y revisar si está sesgado?».

## Qué hay

| Pieza | Para qué |
|---|---|
| `data/replay_cache.json` | 626 partidas reales de Abrams: hora de cada compra y net worth |
| `herramientas/linea_tiempo.py` | una partida, minuto a minuto: qué recomienda y por qué |
| `herramientas/banco_partidas.py` | todas las partidas: métricas, sesgo, outliers (paralelo) |
| `herramientas/meta_abrams.py` | meta observado: qué compran de verdad los Abrams |
| `data/meta_abrams.json` | el meta anterior, con muestra y fecha |
| `tests/test_banco.py` | 12 partidas en CI: guardarraíl de comportamiento |

```bash
abrams-coach linea --match 132662221 --cada 60
abrams-coach banco --partidas 120 --cada 30
abrams-coach banco --enemigos atras          # simula ir perdiendo
abrams-coach meta                            # recalcula data/meta_abrams.json
```

El banco tarda **38 s** con 626 partidas y 48701 muestras (14 procesos). Los enemigos no
vienen en el cache: `--enemigos atras|parejo|arriba` los simula y la salida lo dice.

## Qué mide

- **alcanzable**: el ítem recomendado, ¿se paga con el bolsillo de ese momento?
- **caro sin ahorrar**: recomendar algo que no alcanza sin decir AHORRAR (debe ser 0).
- **800 tarde**: 800 recomendados después del minuto 10 (sin contar componentes).
- **completo**: veces que dice «build completo» (debe ser 0 mientras queden slots).
- **6400 antes del minuto 16**: un tier 4 pagado a medias demasiado pronto.
- **cambios solo por el reloj**: cambia el objetivo con el inventario idéntico. Es el
  «cambia de opinión solo con pasar el tiempo» de Diego.
- **cobertura ±1 min**: % de compras reales que el coach tuvo como objetivo cerca.
- **calibración por tramo**: coste medio recomendado vs coste medio real de ese tramo.
- **sesgo**: cuota de cada ítem en las recomendaciones menos su cuota en las compras
  reales. Negativo = el coach lo usa menos que el meta (infrautilizado); positivo = más.

## Números de hoy (626 partidas, cada 30 s, enemigos parejos)

| Métrica | Valor |
|---|---|
| alcanzable | 61.4% |
| caro sin ahorrar | 0 |
| 800 después del minuto 10 | 411 |
| «build completo» | 0 |
| cambios solo por el reloj | 1.04% |
| cobertura ±1 min | 13.8% |
| cambios de opinión | 4.05 por partida |

Calibración (recomendado vs real): 0–10 min 1,017/1,103 · 10–20 1,786/2,207 ·
20–30 2,548/3,621 · 30+ 3,580/4,973. **El coach sigue comprando más barato que el meta en
el cierre**; es el hueco más claro que queda.

Sesgo: el coach usa **más** Superior Duration (+12.3 pp), Bullet Resist Shredder (+7.4) y
Berserker (+5.8) que el meta; y **menos** Duration Extender (−3.6), Melee Charge (−2.6),
Arcane Surge (−2.6), Enchanter's Emblem (−2.6), Golden Goose Egg (−2.6).

## Lo que el banco ya arregló

1. **La apertura no era el meta.** `data/heroes/abrams.json` (guía) decía Restorative
   Shot; las 626 partidas dicen Extra Regen, Spirit Strike y Close Quarters. Ahora manda
   `data/meta_abrams.json`. Restorative Shot pasó de 15.3% de las recomendaciones a no
   aparecer.
2. **«Camino completo» al minuto 4.** `indices` adelantaba el camino cuando tenías un
   *componente* de un paso, así que comprar un Healing Booster te dejaba sin build. Se
   vio en la partida 60142085. Ahora solo adelanta lo que de verdad tienes.
3. **El objetivo con «faltan» negativo.** La fila sintética del objetivo nacía como no
   alcanzable y el QA de invariantes lo cazó (S03). Arreglado.
4. **Tier 4 antes del minuto 15 y refuerzos de 800 al 25.** Ambos capados.

## Lo que falta (honesto)

- El cache no trae el net worth del equipo, así que **no se puede entrenar remontadas**
  todavía; el perfil `remontada` es criterio, no estadística. La API sí trae los 12
  jugadores por partida: es el siguiente trabajo.
- La calibración del cierre (20+ min) está 1,100–1,400 almas por debajo del meta.
- La cobertura del 13.8% no significa que el coach falle tanto: está recomendando un
  camino distinto al que el jugador siguió. Es una señal para mirar, no un veredicto.
