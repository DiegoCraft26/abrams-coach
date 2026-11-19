# Uso diario: antes, durante y después

Lo que hay que hacer para que el coach sirva, en orden. Nada de esto requiere abrir el
juego primero.

## Antes de encolar

```bash
abrams-coach listo      # cuenta, red, captura, overlay, puerto, disco, silencio
abrams-coach plan       # qué atacar hoy y objetivo de la sesión
```

`listo` revisa las siete cosas que, si fallan, te dejan sin coach a mitad de partida, y
cada fallo trae el comando que lo arregla. Lo que no puede comprobar (que el overlay se
vea encima del juego) lo dice en vez de fingirlo.

```

Dice tus últimas 10 ranked contra las dos metas medidas y una referencia, y **elige un enfoque**:

```
Últimas 10 ranked · 5V-5D · 50.0 % · 2026-11-15 → 2026-11-18
  muertes:        8.7 ✗ (meta ≤6)  · cumple el 40.0 % de las partidas
  participación:  0.42 ✓ (meta ≥0.4)  · cumple el 50.0 %
  3 200:          11.2 ✓ (meta ≤12.0)  · medido en 7 de 10

Enfoque de hoy: baja las muertes
Referencia en tu banda (baja, badge 55): Abrams gana 55.2 % [52.4; 58.1], n=1 166 · tú 50.0 % en tus últimas 10
Objetivo de hoy: 3 de 5 con ≤6 muertes · vas 0/0
```

La línea de referencia compara tu winrate con el de Abrams **en tu banda de rango**, medido en
109 812 jugador-partida. Si tu héroe gana 55 % donde juegas y tú ganas 40 %, el hueco no es
el héroe: es el juego.

El objetivo se guarda en `salida/plan_actual.json` y **se renueva solo** cuando se cumple,
cuando se agotan las 5 partidas o a las 24 h. Progreso en cualquier momento:

```bash
abrams-coach plan --progreso
```

Con `--nuevo` se renueva a mano si quieres cambiar de foco antes.

Si no hay partidas de la temporada, lo dice y no inventa un plan.

## Durante la partida

- **Panel** (segundo monitor): ítem a comprar, camino, amenaza y —si el broadcast está
  vivo— el chip de riesgo (`7 muertes · meta ≤6`).
- **Overlay** (esquina derecha): solo ítem, precio de lista y camino. Sin partida enseña
  **el objetivo de la sesión** (`3 de 5 con ≤6 muertes`). Si no aparece, revisa que no
  exista `~/.abrams-silencio` (apaga todas las ventanas).
- Arrancar todo: `abrams-coach esperar` deja al vigilante listo y abre coach y panel cuando
  detecta Deadlock. El overlay encima del HUD está apagado: `esperar --overlay` lo enciende.

Lo que el panel **no** hace: decir «te alcanza» ni estimar cuánto falta. Las almas llegan con
retraso; fingir precisión de oro costaba credibilidad.

## Al cerrar la partida

El vigilante lanza la nota solo (30 s después, cuando la demo está):

```
139293743 · Abrams · victoria · 35:38
3 200 al min 10:37 ✓ (referencia 12:00) · 6 muertes ✓ (meta ≤6) · 0.39 k+a/min ✗ (meta 0.40)
Población (3 538 partidas de Abrams): ≤6 muertes gana 76.9 % · ≥0.40 k+a/min gana 70.9 %
```

La línea de población se añadió porque tu cohorte (24 partidas) es chica para decidir sola:
3 538 partidas dan el contexto, y el histórico propio dice si ese perfil ya se había visto.

La deja en `salida/ultima_nota.txt`, sale como notificación y **aparece en el panel** la
próxima vez que lo abras sin partida. A mano: `abrams-coach nota --ultima`.

Si la demo todavía no está ingerida, la nota sale parcial y lo dice. No rellena el 3 200 con
la mediana de nadie.

## Al cerrar la sesión

```bash
abrams-coach sesion
```

Lee las notas archivadas (el vigilante guarda una por partida con `--guardar`) y resume:

```
Sesión: 4 partidas · 2V-2D · 50.0 %
  muertes:       6.2 de media (meta ≤6)
  participación: 0.44 de media (meta ≥0.40)
  3 200 antes del min 12: 3/4
  6 muertes o menos: 2/4
  ≥0.40 k+a/min: 3/4
Lo que más se te fue: 6 muertes o menos: 2/4 (50 %)
```

## Una vez por sesión de juego

Mira el `plan` al final: si el enfoque cambió (muertes → participación), es que la anterior ya
se movió. Solo esas dos tienen efecto demostrado; el 3 200 se mide como referencia.

## Qué NO esperar

- **Evidencia por ítem**: el motor está en modo CIEGO a propósito. Ningún ítem tiene muestra
  suficiente; cuando la tenga, el panel lo dirá solo.
- **El 3 200 como meta**: se mide como referencia. A escala (3 935 partidas) el corte de 12
  minutos no separa nada; llegar tarde solo indica que ibas corto de oro.
- **Predicciones de si ganas**: las reglas son descriptivas. Marcan el marcador que hay que
  mover, no adivinan el resultado.
- **Windows**: no existe todavía. `docs/WINDOWS.md` es el diseño, sin una sola medición.
