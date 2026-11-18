# Prompt de relevo — Abrams Coach (2026-11-11)

Pega esto en una sesión nueva para continuar la investigación sin releer todo el historial.

---

## Contexto

Estoy trabajando en `~/Desktop/Chat/abrams-coach` (Python, GTK4, repo git). Es un coach
para Deadlock centrado **solo en Abrams**: lee la partida (API o pantalla), decide qué
comprar y mide sus decisiones contra partidas reales. No dibuja nada sobre el juego.

Tres capas:

1. **Motor** (`coach/`): `motor.py` puntúa ítems, `decision/camino.py` arma el build,
   `decision/amenazas.py` marca rivales peligrosos, `decision/perfil.py` decide el perfil
   (`contra`/`atras`/`arriba`/`remontada`/`base`).
2. **Datos**: `data/conocimiento.json` (lift residual de 1.9M de partidas, counters por
   héroe, grafo de compras), `data/items.json` (catálogo), `data/componentes.json`,
   `data/replay_cache.json` (626 partidas de Abrams con hora de compra y net worth),
   `data/meta_abrams.json` (meta observado), `data/api_cache/` (respuestas de la API).
3. **Herramientas** (`herramientas/`): `banco_partidas.py` corre el motor sobre las 626
   partidas en 38 s y saca métricas y sesgos; `linea_tiempo.py` rejuega una partida minuto
   a minuto; `meta_abrams.py` calcula el meta observado; `tesoros.py` busca combinaciones
   raras en la API; `investigar.py` descompone un ítem (propio vs par vs socio);
   `residuales.py` ajusta logit(winrate) ~ log(coste) + minuto por cohorte y ventana;
   `evaluar_motor.py` mide residual/estabilidad del top1.

## Estado actual

- Batería en verde: `for t in tests/test_*.py; do python3 "$t"; done` (las gráficas, con
  `~/.local/bin/xvfb-coach`; tres suites piden `pytest` y no está instalado).
- Commits recientes: banco de partidas, meta observado, amenazas, perfil de build,
  caza de tesoros.
- Hallazgo principal (corregido con el residual ajustado): **Scourge es el candidato**
  (+4.19 pp global, 4.º/153; +8.12 pp en pobres 30–40 min; estable en dos ventanas de
  parche) y **Frenzy es ruido** (+1.5 pp, 33–45.º). El A/B con Scourge mejora estabilidad
  (63.2% → 67.5%) sin empeorar residual. Frenzy quedó descartado.

## Lo que hay que hacer (en orden)

1. **Triples**: `investigar.py --combo 3 --min-matches 150` y buscar sinergias que no
   salgan en pares. Filtrar siempre por estrato y cohorte pobre.
2. **Hecho**: Frenzy con control de duración y residual ajustado → descartado.
3. **A/B con impacto real**: comparar winrate de builds publicadas
   (`item-stats?hero_build_id=...`) que llevan el ítem vs las que no, controlando por
   rango (`min_average_badge`/`max_average_badge`).
4. **Ventanas de parche**: `tesoros.py --desde A --hasta B` dos veces y `--comparar`;
   anotar qué combos aparecen/desaparecen por parche.
5. Si un ítem pasa (a) sube en cohorte pobre, (b) ventaja_socio > +3 pp, (c) aguanta
   duración y (d) el A/B no degrada estabilidad/residual → proponerlo en
   `docs/hipotesis-meta.md` y solo entonces tocar el motor. **Scourge ya pasa las cuatro**;
   falta decidir cómo entra (¿sección de tesoros en el panel o pieza del camino?).

## Reglas

- **Nada de números inventados.** Si no se midió, se dice. Toda cifra lleva su muestra.
- Antes de creer un combo: estrato de coste/minuto, cohorte pobre y Wilson al 95%.
  El sesgo de «voy ganando y compro caro» ya nos engañó una vez con Magic Carpet.
- Cada cambio de reglas se mide con `banco_partidas.py` antes de commitear.
- Commits pequeños, en español, con el porqué. No reescribir historia.
- La UI no abre ventanas sin pedirlo: pruebas gráficas con `~/.local/bin/xvfb-coach`.
- No tocar el navegador de Diego ni plataformas de trabajo pagado.
- Si el hilo se atasca, dejar el estado en `RELEVO.md` y parar.

## Comandos

```bash
cd ~/Desktop/Chat/abrams-coach
abrams-coach banco --partidas 120 --cada 30
abrams-coach banco --enemigos atras
abrams-coach linea --match 132662221 --cada 60
abrams-coach meta
abrams-coach tesoros --top 10 --max-networth 25000
python3 herramientas/investigar.py --cohorte pobres --min-matches 100
ABRAMS_FORZAR=339443430 python3 herramientas/evaluar_motor.py --partidas 120
```

Documentos: `docs/banco-partidas.md`, `docs/hipotesis-meta.md`,
`docs/investigacion-2026-11-11.md`, `RELEVO.md` (estado del día).
