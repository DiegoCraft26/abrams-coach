# Mecánicas de Deadlock aplicadas al motor

Medido el 2026-11-08 sobre `data/items.json`, `data/componentes.json`, `data/conocimiento.json`,
`data/mis_partidas.json` (577 partidas), y ejecutando el motor con estados sintéticos
(`/tmp/dlvenv/bin/python`, `Motor.analizar_dict`). Lo que no se pudo medir dice **sin medir**.

## 1. El árbol de upgrades real

**Cinco niveles, coste fijo por nivel.** `data/items.json` trae 250 ítems y `item_tier`/`cost`:

| Nivel | Ítems | Coste de lista |
|---|---|---|
| 1 | 32 | 800 |
| 2 | 68 | 1,600 |
| 3 | 67 | 3,200 |
| 4 | 60 | 6,400 |
| 5 | 23 | 9,999 |

**Cómo se encadenan.** 64 ítems declaran `component_items` (por `class_name`, resuelto a ids en
`data/componentes.json`, 1.7 KB, generado por `herramientas/construir_componentes.py`).
Profundidad medida: 57 cadenas de 2 niveles, 6 de 3 y 1 de 4 (`Timeless Emblem` 9,999 ←
`Transcendent Cooldown` 6,400 ← `Superior Cooldown` 3,200 ← …). Los componentes **no son
requisito**: son descuento. 60 de esos 64 están en `data/conocimiento.json`.

**Coste efectivo.** El componente aporta su coste completo; se paga sólo la diferencia y el suelo es 0:

| Ítem | Coste | Componentes | Pagas teniéndolos |
|---|---|---|---|
| Capacitor | 6,400 | Tesla Bullets (3,200) | 3,200 |
| Leech | 6,400 | Bullet Lifesteal + Spirit Lifesteal (3,200 c/u) | 0 |
| Shadow Weave | 3,200 | Sprint Boots (800) | 2,400 |
| Colossus | 6,400 | Extra Health (800) | 5,600 |

**Slots al completar.** 4 + 4 + 4 = 12 (`coach/estado.py:5`, `coach/motor.py:46`, y el panel pinta
12 slots: `informes/ui-revision.md:61`). Al completar un ítem, sus componentes se consumen y
devuelven su hueco; el ítem nuevo ocupa uno. Neto: 0 huecos si el componente era del mismo slot,
+1 hueco libre si era de otro. **5 cadenas cruzan de slot** (medido): `Shadow Weave`, `Kinetic Dash`,
`Spiritual Overflow` y `Ballistic Enchantment` absorben componentes de vitalidad/spirit.

El motor ya hace bien la cuenta: `coach/motor.py:307-309` calcula `ahorro` y `costo`, y
`coach/motor.py:335-336` devuelve el hueco con `libera`. Verificado: Colossus con Extra Health sale
a 5,600 y sin exigir venta.

Lo que no hace: `_es_mejora_de` (`coach/motor.py:122-125`) devuelve **siempre False** y su
comentario ("Deadlock no tiene árbol de mejoras") contradice al resto del archivo
(`coach/motor.py:276-279`) y a los datos. Es código muerto, no un cálculo.

## 2. Qué mueve hoy la recomendación

`score` = `coach/motor.py:373-386`. Descomposición medida a los 30 min (117 candidatos que pasan
filtros, patrimonio 20,000):

| Ítem | score | lift | counter | fase | flujo | tiempo | balance | presupuesto |
|---|---|---|---|---|---|---|---|---|
| Slowing Bullets | 10.35 | +5.24 | +2.18 | +0.54 | −0.10 | −2.60 | +0.90 | 0.00 |
| Colossus | 8.84 | +6.12 | +3.00 | +0.69 | +0.33 | −1.13 | +0.90 | −1.20 |
| Spellbreaker | 8.83 | +3.44 | +2.38 | +0.66 | −0.10 | −1.39 | +0.90 | −1.20 |

Los dos términos grandes (`lift`, `counter`) son **constantes por ítem**: no dependen de la partida,
sólo del matchup. Barrido con cada peso a 0 sobre el mismo estado: **sólo `w_tiempo` cambia el top-3**.

## 3. Factores que deberían mover la decisión y hoy no

| Factor | Señal calculable con lo que YA llega | Qué falta | Hoy |
|---|---|---|---|
| Momento de la partida | `t` + inventario propio → ritmo de compras vs. columna del grafo (`data/conocimiento.json` → `flujo.fases`); desvío contra `patrones.benchmark_almas` (`coach/decision/patrones.py:40-53`) | nada de datos; falta usarlo | sólo `min_compra` fijo por ítem (`coach/motor.py:128-132`, `:328-330`) y la rampa de apertura (`:225-239`) |
| Almas relativas | `oro` sin gastar (`m_iGold`) y patrimonio (`m_iGoldNetWorth`), ambos por jugador; delta contra el rival de tu equipo; KDA enemigo | el carril de cada jugador (existe `m_nHeroDraftPosition` en el esquema, **sin medir** su semántica) | `economia()` usa sólo la media rival (`coach/motor.py:81-91`); atrás → castigo plano de 0.9 si el ítem pasa de 3,200 (`:361-363`) |
| Presupuesto real | `oro` ya viaja en `coach/fuentes/api_vivo.py:144`… | …y `coach/estado.py:66-77` lo **descarta**: `Jugador` no tiene campo `oro` (`coach/estado.py:9-15`) | `coach/motor.py:345` compara el coste contra `almas` = **patrimonio**. Medido: con 20,000 de patrimonio y 200 de oro ofrece ítems de 6,400 |
| Composición enemiga | `heroe_id` de los 6 rivales (`coach/en_vivo.py:45`) | el mapeo héroe→amenaza real (curación/CC/burst) no está en `heroes.json`, que sólo tiene id y nombre | 16 ítems situacionales hardcodeados (`coach/decision/situacionales.py:14-68`) con bonus máximo de 4.0 puntos (`:119`). Medido: 5 curanderos vs 0 → top-1 idéntico |
| Composición aliada | héroes de los 5 aliados (llegan) y sus almas (llegan, `coach/motor.py:85-87`) | igual que arriba: falta el mapeo de kit | **cero**: sólo se muestran en el panel (`coach/motor.py:524-526`) |
| Ítems enemigos vistos | `m_vecUpgrades` de los 12 jugadores, ya decodificado (`coach/en_vivo.py:107-115`, `:158`) | nada de datos | **cero**: `api_vivo.py:112-128` borra `items` de aliados y enemigos antes de llegar al motor |
| Ítems aliados (no duplicar antiheal) | mismo campo `m_vecUpgrades` de aliados | nada | **cero**, mismo descarte |
| Estado del mapa/objetivos | `objectives_mask_team0/1`, `net_worth_team_0/1`, `start_time` en `/v1/matches/active` (`informes/investigacion-A-estado-vivo.md:60`), endpoint que la app **ya llama** | el significado de los bits del mask (**sin medir**) | `partida_activa()` devuelve sólo `match_id` y tira el resto (`coach/en_vivo.py:85-104`) |
| Fase del build | slots ocupados por categoría (`coach/motor.py:113-119`) y coste acumulado del inventario propio (suma de `cost` de `m_vecUpgrades`) | nada | se usa el **patrimonio** contra umbrales de coste del build (`coach/decision/patrones.py:63-72`), y ese "hito" se trata como meta de ahorro: castigo medido de −1.20 a todo tier 4 a los 30 min (`coach/motor.py:356-358`) |

## 4. Sesgos medidos del motor

| Sesgo | Evidencia |
|---|---|
| El ranking es casi una constante por ítem | Spearman(residual, score) = 0.87 a los 10 min, 0.34 a los 40 min; top-1 = residual máximo en 9 de 85 estados |
| Se repite lo mismo durante media partida | Partida simulada 10→50 min con almas de benchmark: **4 ítems distintos** como top-1 y un tramo de 19 min con el mismo (`Slowing Bullets`, 118 estados seguidos) |
| Las almas apenas pesan | ±4,000 de delta mueven el score del top-1 0.3 puntos (12.77 / 12.80 / 12.51) y no cambian el top-1 |
| La composición no cambia el ranking | 5 curanderos vs 0: top-1 idéntico; los antiheal salen con `coef` negativo (`−1.52` a `−5.70`) y quedan fuera del ranking a propósito (`coach/decision/situacionales.py:135-171`) |
| La heurística de composición tiene 4 claves rotas | `HEROES_CON` (`coach/decision/situacionales.py:74-79`) menciona `mcginness`, `talon`, `geist`, `arcanist`, que no existen en `data/heroes.json` (son `mcginnis`, `grey_talon`, `lady_geist`). Medido: comp de 5 con curación cuenta 4 |
| El panel retiene la recomendación 10 s | Histeresis de `quietud_s=10` y `+3.0` de score (`coach/estabilizador.py:68-73`) con diferencias reales de ~1.7 puntos entre el 5.º y el 1.º |
| Un tercio del catálogo no existe para el motor | `data/conocimiento.json` tiene 153 de los 173 ítems comprables, **0 de tier 5**→ nunca recomienda el cierre del build (`coach/motor.py:495-509` tampoco los propone como objetivo) |
| El residual no separa "bueno" de "comprado yendo ganando" | `lift_residual` = lift menos una regresión lineal sobre el minuto medio de compra, con **r² = 0.1444** (`coach/conocimiento.py:91-123`) |
| No planifica dos compras | Cada candidato se puntúa aislado; el hueco que libera un componente de otro slot (`coach/motor.py:335`) no habilita nada en el mismo ciclo |
| Ofrece swaps que no explica | Medido con el slot de arma lleno: 29 candidatos piden venta y `sugerir_venta()` devuelve `None` |
| El banco de pruebas no puede ver el error de caja | `data/replay_cache.json` sólo trae `neto`; `herramientas/evaluar_motor.py:49-60` reconstruye el estado sin oro sin gastar |
| Coste de ítem sin dato | `Extra Charge` (800, componente de una cadena) no está en `conocimiento.json`: `_costo_de` (`coach/motor.py:287-288`) devuelve 0 y el ahorro se pierde |

## 5. Qué archivos tocar por hallazgo

| Hallazgo | Archivos |
|---|---|
| Caja = oro sin gastar, no patrimonio | `coach/estado.py` (campo `oro`), `coach/motor.py:345,352,461`, `herramientas/evaluar_motor.py` |
| Ítems enemigos y aliados al motor | `coach/fuentes/api_vivo.py:112-128`, `coach/estado.py`, `coach/motor.py` (`_bonus_counter` y nuevos usos) |
| Claves de héroe rotas en la heurística | `coach/decision/situacionales.py:74-79` |
| Tier 5 y coste de componentes ausentes | `coach/conocimiento.py` (regenerar con los 20 que faltan) |
| `_es_mejora_de` muerto | `coach/motor.py:122-125,338,406` y `coach/dominio.py:155` |
| Fase del build por inventario, no por patrimonio | `coach/decision/patrones.py:63-82`, `coach/motor.py:356-358` |
| Objetivos y economía de equipo | `coach/en_vivo.py:85-104` |
| Presupuesto de ahorro mal calibrado (hito como meta) | `coach/motor.py:356-358` |
