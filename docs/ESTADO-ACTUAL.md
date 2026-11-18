# Estado actual — Abrams Coach (para retomar sin leer el chat)

Actualizado: **2026-11-18 ~14:00 CST** (ronda 32). Si algo de aquí no coincide con el código o con un
informe, manda el código: abre un issue y corrige este archivo.

## Qué es hoy

Panel de decisiones para Deadlock, solo Abrams medido, en español. Lee la partida por
broadcast (1.3 s con URL) y por HUD (OCR a 2 Hz); la app vive en el segundo monitor y ahora
también como **overlay** en el borde derecho del HUD.

| Pieza | Estado | Dónde |
|---|---|---|
| Motor v2 (valor medido por compra) | **cerrado como resultado negativo**: con 20 parches y 63 680 compras ningún ítem tiene efecto demostrado ni réplica. El panel funciona con camino y reglas | `docs/MOTOR-V2.md` |
| Datos por héroe | **4 héroes**: Abrams (guía) + Haze, Rat King y Graves (apertura medida en `lab.db`) | `data/heroes/` |
| Tarjeta 420×160 (solo certeza) | hecho, commit `0831d22` | `coach/ui/tarjeta.py`, `capturas/tarjeta-*` |
| Overlay layer-shell (KDE) | funcionando y enganchado al vigilante (`--sin-overlay` lo apaga; respeta `~/.abrams-silencio`) | `herramientas/overlay.py`, `herramientas/vigilar.py` |
| Panel web `/panel` | hecho; sin «faltan/te alcanza», chip de riesgo en vivo y, sin partida, la última nota | `coach/ui/web.py` |
| Panel GTK4 | hecho, pesado (127 MB) | `coach/ui/app.py` |
| Datos multi-héroe en la PC | hecho (8 300 partidas, 4 héroes) | `~/abrams-coach` en `pc` |
| Ingesta de demos | mapeo resuelto y piloto 100 % (71/71). **Bloqueada por la cuota de la API** (429 en cadena desde las 13:00) | `herramientas/demos/` |
| Corpus por parche | **9 731 partidas en 20 parches**, 1,8 M compras con net worth al comprar | `datos/historico.db`, `docs/DATOS-DEL-JUEGO.md` |
| Windows | overlay y captura **ejecutados bajo Wine** (10 comprobaciones; GDI 27,7 ms/cuadro). Sin probar en Windows nativo | `docs/WINDOWS.md`, `herramientas/probar_windows_wine.sh` |
| Ciclo diario | `listo` → `plan` → panel/overlay → `nota` → `sesion` | `herramientas/cli.sh`, `docs/USO-DIARIO.md` |

## Números que se pueden citar

- Abrams: **51.86 %** de WR en 951 694 partidas desde el 5 nov (12.º de 44). **No es S+ tier.**
- Corpus Abrams: 17 751 partidas completas, **277 138** compras (tras quitar 2 747 partidas
de 8 jugadores que son otro modo). Base: 20 500 partidas, 235 011 jugadores.
- **Reglas con efecto**: ≤6 muertes 76,9 % vs 36,2 %; ≥0.40 k+a/min 70,9 % vs 12,8 %
  (3 538 partidas de Abrams con badge). No dependen de la banda.
- **Referencia sin efecto**: primer 3 200 antes del min 12 → 55,1 % vs 53,0 % (p=0,20) en
  3 935 jugador-partida. Se informa, no se propone.
- **Fuerza por héroe**: Graves 55,7 % vs Shiv 45,9 % (9,8 pp, IC sin solape). Abrams 53,6 %
  [52,1; 55,2]; en la banda baja 55,2 %.
- **Motor de ítems**: cerrado. 63 680 compras en 20 parches, 13/97 IC fuera de cero (7–11
  esperados por azar), réplica entre parches Spearman 0,091 y placebo 0,159 → el límite es
  la muestra. **El artefacto está invalidado y el motor corre en CIEGO** a propósito.
- Overlay: ~0 % CPU, **126 MB** RSS. Servidor simulado: 1 % CPU, 37 MB.
- Suite: **528 pruebas** en verde (con `gi` + `pytest` vía `PYTHONPATH=/tmp/pytestlib`).

## Decisiones tomadas (y por qué)

1. **El overlay solo muestra lo que se sabe**: ítem, precio de lista y camino. Sin «faltan»
   ni «te alcanza» (2026-11-18): las almas llegan con 20–25 s de retraso.
2. **Overlay siempre visible**, borde derecho a media altura: es el único hueco del HUD.
3. **Windows sí**, como módulo de captura (DXGI) + overlay Win32; el motor no se toca.
4. **Rust no** para el motor (p99 7 ms): el cuello es la captura y el broadcast.
5. **Datos masivos por demos** (SQL sobre demos de la API) antes que más heurísticas.
6. **No se lee memoria, no se inyecta, no se engancha el proceso.** Zona gris legal, pero
   ese es el límite que no se cruza.
7. **El equipo** se rige por `docs/EQUIPO.md`: adversario, alcance disjunto, evidencia.

## Reglas medidas (2026-11-18)

**Con efecto demostrado a escala** (3 538 partidas de Abrams con badge):
- **≤ 6 muertes**: 76.9 % vs 36.2 %.
- **≥ 0.40 (kills+asistencias)/min**: 70.9 % vs 12.8 %. No depende de la banda de rango.

**Solo referencia, sin efecto demostrado**:
- **Primer 3 200 antes del min 12**: en 24 demos propias daba 60 % vs 28.6 %, pero en
  3 935 jugador-partida da **55.1 % vs 53.0 % (p=0.20)**. Se informa, no se propone.
  `informes/lab/REGLA-3200-2026-11-18.md`.
- El 6 400 temprano **no** separa (20.7 vs 20.8 min, p=0.51); las muertes antes del min 10
  tampoco. El diagnóstico completo: `informes/lab/PERSONAL-DEMOS-2026-11-18.md`.
- **Validadas en 3 538 partidas de Abrams** (no solo en tus 24): muertes ≤6 → 76.9 % vs
  36.2 %; participación ≥0.40 → **70.9 % vs 12.8 %**. La del 3 200 no se puede validar sin
  demos. `informes/lab/REGLAS-VALIDADAS-2026-11-18.md`.

## Dato que manda sobre el Motor v3 (2026-11-18 11:12)

Con 16 145 compras de 79 demos normalizadas: el **65.79 %** de las compras son «lo más caro
que podía pagar». La elección está dominada por el presupuesto, así que el contrafactual
tiene que ser **asequible y del mismo tramo de precio** (±50 %). Cobertura con ≥2
alternativas: 99.88 %. Tabla: `datos/demos_norm.csv.gz` (regenerable con
`herramientas/lab/demos_norm.py`).

## Automatización en la PC (2026-11-18)

- `abrams-crawler.timer`: descubre e ingiere demos de partidas recién terminadas. Desde el
  2026-11-18 13:12 va a **--paralelo 2 --rpm 60** (antes 3/120). **No sirvió**: en 30 min
  hubo 56 respuestas 429 y 1 partida completa. La cuota del endpoint `demo/query` es del
  proveedor, no de nuestro ritmo; el crawler respeta `Retry-After` y no pierde partidas,
  pero avanza a golpes. Con esto, llegar a 800 demos no está en nuestra mano. **Ritmo
  real medido el 2026-11-18 11:55: 23 demos en 105 min (~0.22/min, ~316/día)** y 46
  partidas sin demo (2 de cada 3). Jobs de demo/query de 143 a 1 088 s. La CDN directa de
  Valve se probó: ~300 KB/s y demos de decenas de MB, no es más rápida. **El 18 nov a las
  12:00 el pase completo dio 0 partidas en 25 min** y una consulta manual no volvió en 3
  minutos: el servicio está degradado, no solo lento. El cuello es externo.
- `abrams-v3.timer`: cada 6 h revisa si hay ≥800 demos; si sí, regenera la tabla
  normalizada, corre el estimador v3 (200 réplicas), pasa la puerta del sintético y escribe
  `informes/lab/V3-AUTO-<fecha>.md`. Si el sintético falla, no publica nada.
- Ver: `systemctl --user list-timers | grep abrams`. Apagar: `systemctl --user disable --now`.

## En curso

- Mapeo `purchaser_player_slot` ↔ `player_slot` y piloto de 5 demos (agente).
- QA de UI: nombres truncados en los tiles y tipografía (siguiente ciclo).
- Investigación de escalada de rango (qué hacen los que suben rápido).

## Huecos conocidos (por orden de impacto)

1. **Serie temporal**: el corpus es 8 h de un solo día y un parche. Sin holdout temporal no
   se puede decir «esto aguanta el próximo parche».
2. **MMR/badge**: nulo en 88 %; sin banda no se separa habilidad de build.
3. **Windows sin probar**: todo el documento es diseño; cero mediciones reales.
4. **Overlay**: no probado sobre una partida real en marcha (solo sobre escritorio).
5. **Retención de demos**: no se sabe cuánto tiempo atrás llega la API de demos.

## Cómo retomar

```bash
cd ~/Desktop/Chat/abrams-coach
git log --oneline -5           # último estado
# Suite completa EN EL ESCRITORIO (con gi y pytest juntos; el sistema no trae pytest):
uv pip install --target /tmp/pytestlib --python /usr/bin/python3 pytest
PYTHONPATH=/tmp/pytestlib /usr/bin/python3 -m pytest -q tests   # 528 pruebas
# En la PC: la suite necesita data/items.json (gitignored) o falla por archivo ausente.
#   scp data/items.json pc:~/abrams-coach/data/
python3 run.py --fuente simulado --puerto 8091 &
python3 herramientas/overlay.py --url http://127.0.0.1:8091
python3 -m pytest -q           # o en pc con /srv/scratch/abrams-bot-venv
abrams-coach nota --ultima     # las reglas de tu última partida
abrams-coach plan              # qué atacar hoy según tus últimas ranked
```

Leer, en este orden: `docs/EQUIPO.md`, este archivo, `ROADMAP.md`, `docs/DATOS-DEL-JUEGO.md`.
