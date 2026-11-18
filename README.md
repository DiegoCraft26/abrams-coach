# Abrams Coach

[![ci](https://github.com/DiegoCraft26/abrams-coach/actions/workflows/ci.yml/badge.svg)](https://github.com/DiegoCraft26/abrams-coach/actions/workflows/ci.yml)

Panel de decisiones para Deadlock. Lee tu partida desde la pantalla (HUD y marcador) y,
cuando hay broadcast público, desde la API de espectador. Te dice **qué comprar y qué viene
después**, te avisa cuando pasas de seis muertes, y al terminar te devuelve una nota con las
reglas que importan. Vive en un segundo monitor y, si quieres, como una tarjeta encima del
HUD: **no lee memoria, no inyecta y no engancha el proceso del juego**.

Estado: **v1.0** (historial en [`CHANGELOG.md`](CHANGELOG.md)). Cuatro héroes con datos
(Abrams por guía; Haze, Rat King y Graves con la apertura medida en 4 000 partidas). Con
otro héroe el panel usa el camino de Abrams y lo dice.

Lo que se afirma está medido y lo que no, se calla: **dos reglas tienen efecto demostrado**
(seis muertes o menos y 0,40 de participación, en 3 538 partidas) y el **ranking de ítems
por «valor medido» está apagado**: con 63 680 compras en 20 parches ningún ítem pasó la
prueba. Detalle en [`docs/MOTOR-V2.md`](docs/MOTOR-V2.md).

![Panel en modo demo a 1280x720](capturas/ui-1280x720.png)

La captura es del modo demo (`abrams-coach demo`), con datos de ejemplo: el panel es
el mismo que ves en partida. En partida la cabecera dice «en vivo» o «pantalla» y las
almas de los rivales llegan del broadcast.

## Medir y probar contra partidas reales

El motor no se ajusta a ojo: se mide contra las 626 partidas de Abrams de
`data/replay_cache.json`, sin abrir el juego.

```bash
abrams-coach linea --match 132662221 --cada 60   # una partida, minuto a minuto
abrams-coach banco --partidas 120 --cada 30      # todas: métricas, sesgo, outliers
abrams-coach banco --enemigos atras              # simulando ir perdiendo
abrams-coach meta                                # meta observado de Abrams
abrams-coach tesoros                             # combos raros que ganan (API)
abrams-coach resultado 132662221                 # guarda el win/loss de una partida
```

`resultado` cierra el bucle: guarda si la partida se ganó, y con eso `winrate_por_primer_item`
empieza a medir acierto real (no parecido). Si la API falla, el comando lo dice y sigue;
nunca rompe el archivado.

`tesoros` busca combinaciones que rinden por encima de su estrato de coste y minuto, con
cohorte de jugadores pobres para no confundir «ganar» con «comprar caro». Metodología e
hipótesis abiertas en [docs/hipotesis-meta.md](docs/hipotesis-meta.md).

`banco` tarda 38 s con las 626 partidas y saca alcanzabilidad, calibración por tramo,
cobertura de compras reales, cambios de opinión y qué ítems usa de más o de menos frente
al meta. Detalle en [docs/banco-partidas.md](docs/banco-partidas.md).

## Plataforma

| Sistema | Estado |
|---|---|
| KDE Plasma 6 + Wayland | **probado** (es el entorno de desarrollo) |
| KDE Plasma + X11 | sin probar; la captura usa KWin por D-Bus, debería funcionar |
| GNOME / otro escritorio | **no funciona**: no hay KWin ni `org.kde.KWin.ScreenShot2` |
| Windows / macOS | no |

La captura va por `org.kde.KWin.ScreenShot2` (unos 40 ms por cuadro, sin tirones) y
`spectacle` como respaldo. Por eso el requisito de KDE es real, no una preferencia.

## Requisitos

Python 3.11 o más, GTK 4 con PyGObject, Pillow, NumPy, PyYAML, `tesseract` y `spectacle`.

**Arch / CachyOS / Manjaro** (probado):

```bash
sudo pacman -S --needed python-gobject gtk4 tesseract spectacle \
                       python-pillow python-numpy python-yaml
```

**Debian / Ubuntu**:

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 libgtk-4-1 tesseract-ocr spectacle \
                 python3-pil python3-numpy python3-yaml
```

**Fedora** (nombres equivalentes, sin probar):

```bash
sudo dnf install python3-gobject gtk4 tesseract spectacle \
                 python3-pillow python3-numpy python3-pyyaml
```

## Instalación

**Con git** (para seguir el desarrollo):

```bash
git clone https://github.com/DiegoCraft26/abrams-coach.git
cd abrams-coach
./instalar.sh
abrams-coach demo
```

**Con el paquete** (3.3 MB, sin git, sin datos de partidas ni iconos):

```bash
tar xzf abrams-coach-v0.9-<commit>.tar.gz
cd abrams-coach-v0.9-<commit>
./instalar.sh
abrams-coach demo
```

El tarball lo construye y lo prueba `herramientas/empaquetar.sh`: lo desempaqueta en un
directorio temporal, arranca el coach en modo simulado y falla si `/api/estado` no responde
con camino y recomendaciones. Un paquete que no arranca no se publica.

`instalar.sh` comprueba las dependencias, dice cuál falta y deja `abrams-coach` en
`~/.local/bin`. No instala paquetes ni usa `sudo`.

El arte del juego no viene en el repo: la primera vez que arranca, la app baja unos
9 MB de iconos del bucket público de `deadlock-api` a `data/iconos/` (ignorado por git).

### La cuenta es opcional

Para el modo en vivo hay dos caminos:

- **Sin cuenta**: la app lee `MATCH: …` del HUD y engancha el broadcast de esa partida.
  Funciona en cualquier ranked, práctica o bots, sin pedirte el SteamID. Con
  `--mi-heroe abrams` intenta saber cuál jugador eres; si hay dos Abrams en la partida,
  no adivina y te lo dice.
- **Con cuenta**: `abrams-coach jugar` la lee de `.cuenta` (ignorado por git), de
  `ABRAMS_CUENTA` o de `--cuenta`. Así sabe sin ambigüedad qué columna es la tuya y
  puede avisar si tu cuenta no está en la partida.

Nunca hay una cuenta de fábrica en el código.

## Uso

```bash
abrams-coach ayuda      # el ciclo de una sesión, en una pantalla
abrams-coach listo      # chequeo previo: cuenta, red, captura, overlay, puerto, disco
abrams-coach demo       # panel con datos de ejemplo, sin abrir el juego
abrams-coach jugar      # prepara la máquina, abre coach y panel
abrams-coach esperar    # arranca solo cuando abres Deadlock y archiva al salir
abrams-coach plan       # antes de jugar: últimas ranked, metas y objetivo de la sesión
abrams-coach nota       # las reglas de la última partida
abrams-coach sesion     # al cerrar: qué regla se te fue en la sesión
abrams-coach estado     # qué corre, cuánta RAM usa, qué leyó
abrams-coach archivar   # guarda la sesión en la base local
abrams-coach informe    # resumen de la última partida
abrams-coach medir      # mide la cadena de latencia
abrams-coach parar      # cierra todo
```

Sin instalador:

```bash
./arrancar.sh simulado && python3 panel_nativo.py
python3 run.py --fuente vivo                    # HUD, sin cuenta
python3 run.py --fuente vivo --cuenta TU_ID     # broadcast identificado
```

Atajos del panel: `1` compra, `2` enemigos, `3` compras, `?` ayuda, `Esc` cerrar. La
ventana recuerda tamaño y posición.

**Panel web** (sin instalar nada, en cualquier navegador):

```bash
python3 run.py --fuente vivo --puerto 8090
# y abre http://127.0.0.1:8090/panel  (o http://<tu-ip>:8090/panel desde otro equipo)
```

Mismo dato que la app nativa: estado de la economía, compra recomendada con sus razones,
plan, composición y el histórico de la composición («esta comp ya la jugaste, así te
fue») con su muestra. No carga nada de fuera: si se cae el coach, lo dice. Ver
`capturas/panel-web.png`.

### Abrirla sin pensar

- `abrams-coach abrir` abre el coach y el panel ahora, y lo coloca en el monitor
  secundario. La app vive mientras su ventana viva: al cerrar el panel se apaga el
  coach (nada de unidad de systemd activa toda la tarde). `ABRAMS_QUEDAR=1` lo deja
  corriendo, como antes.
- `abrams-coach esperar` se queda en segundo plano y hace lo mismo **cuando abres
  Deadlock**; al salir archiva la partida. `instalar.sh` puede dejarlo al iniciar sesión.
- Atajo global: Ajustes → Atajos → añadir comando → `abrams-coach abrir` (por ejemplo
  `Meta+J`). Funciona con el juego en primer plano porque lo captura KWin, no el juego.
- No hay botón *dentro* del juego: sería un overlay y el proyecto no dibuja ni inyecta
  nada. El atajo y el arranque automático hacen lo mismo sin tocar Deadlock.

#### Que no aparezca nada (modo silencio)

```bash
touch ~/.abrams-silencio     # el vigilante espera, pero no abre el panel
rm ~/.abrams-silencio        # vuelve a abrirlo solo
```

El vigilante también trae dos defensas que salieron de un incidente real (2026-11-09:
quedó uno viejo corriendo junto al servicio de systemd y cada uno abría su panel):

- **un solo vigilante**: bloqueo exclusivo en `/tmp/abrams-vigilar.lock`; el segundo
  proceso sale en vez de duplicar ventanas;
- **freno de reapertura**: si el panel muere solo, no se reabre más de una vez cada
  5 minutos;
- la ventana **no pide foco** (`set_visible`, no `present`) y el script de KWin la deja
  debajo y sin entrada en la barra de tareas.

## Qué te dice

| Sección | Contenido |
|---|---|
| Cabecera | reloj, oro sin gastar, patrimonio, ventaja de almas y estado táctico |
| Compra | el siguiente paso del build, con estado **COMPRAR / AHORRAR / VENDER**, cuánto falta y ETA |
| Inventario | tus 12 slots y el rendimiento de cada ítem frente a lo esperado |
| Enemigos | almas y KDA de los cinco rivales |
| Plan | las compras que suelen seguir, del grafo de partidas públicas |
| Contra su composición | ítems que la amenaza enemiga justifica, con su fuente |
| Ventas | cuándo vender rinde más que seguir ahorrando |
| Pie | latencia real de cada eslabón |

## Cómo funciona

1. **Captura** la pantalla con KWin (D-Bus) y reutiliza el último cuadro entre lectores.
2. **Lee** el reloj, el oro y el id de partida del HUD con OCR; el marcador, con
   plantillas del propio juego. Nada de memoria del proceso.
3. **Engancha** el broadcast público por `deadlock-api` usando el id del HUD o tu cuenta.
4. **Decide** siguiendo un camino de build: tres aperturas de 800, tres piezas de core
   (1,600–3,200) y los spikes. Si no alcanza, no te empuja a otro 800: te dice cuánto
   falta y en cuántos segundos. Los componentes del objetivo se compran siempre.
5. **Publica** el estado en `http://127.0.0.1:8090`; lo consumen el panel nativo y el
   panel web (`/panel`).
6. **Consulta** lo que ya sabe: tus 626 partidas para el camino y un archivo local de
   partidas públicas para las composiciones («esta comp ya la jugaste, así te fue»).

Detalle técnico: [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md).
Qué hace y qué no hace con el juego: [`POLITICA.md`](POLITICA.md).
Qué viene: [`ROADMAP.md`](ROADMAP.md).

### El build como camino

El motor ya no puntúa ítems sueltos. Arma una secuencia con el grafo de compras reales
(apertura → core → spike) y en cada lectura te dice el siguiente paso:

- **COMPRAR** si lo pagas (o si pagas un componente suyo, que se absorbe al subir).
- **AHORRAR** si no alcanza: `faltan N almas`, `ETA` en segundos, y si es un ítem caro
  el modo es `rush`; si el ETA es largo, `farm`.
- **VENDER** si el slot está lleno: dice **qué ítem** y de qué slot, no un icono suelto.
- **Rama por composición**: con dos o más móviles entra antimovilidad, con control entra
  anticontrol, con burst spirit entra antispirit, pero solo si el matchup de 1.9 M de
  partidas lo respalda. Si los datos no apoyan el counter, no se inventa.
- El inventario muestra los huecos por categoría (`arma 3/4 · vitalidad 4/4 · espíritu 2/4`).
- El bonus de categoría (4,800 almas) se vigila y se avisa cuando falta poco, pero no
  se persigue a ciegas: forzarlo convierte cualquier build en uno genérico.

Medido sobre 626 partidas reales: **1.39 ítems de 800** de media en los primeros 10
minutos (máximo 3), 1.8 ms por decisión. Antes eran 4–5.

## Qué añadió la v2 (noviembre 2026)

Todo esto se puede comprobar sin abrir el juego con `python3 herramientas/verificar_v2.py`.

| Pieza | Qué hace |
|---|---|
| **Captura por caja** | KWin entrega solo la caja del HUD (1–3 ms) en vez de la pantalla entera (415 ms con `spectacle`). Sin autostart: se abre con `arrancar.sh`. |
| **Estado del juego** | Menú, partida y cierre se leen del `console.log` con un `stat`: `dl_hideout` es menú, `Source2Shutdown` es juego cerrado. El panel no afirma una partida que ya no existe. |
| **Histórico de composiciones** | `data/historico.json.gz` con 151 653 partidas públicas: cuántas veces viste esa comp y cómo acabó, y qué ítems aparecen en las que ganan contra esos rivales. |
| **Camino por héroe** | `herramientas/camino_heroe.py` deriva apertura y tramos de cualquier héroe desde sus timelines. Con otro héroe el panel usa su camino y avisa de que la economía sigue siendo la de Abrams. |
| **Archivo local** | `herramientas/archivo_abrams.py` baja partidas por el endpoint en bloque (1000 por petición, ~1.5 s). 166 653 partidas en 21 MB. |
| **Panel web** | `/panel`: mismo dato, sin instalar nada y sin dependencias externas. Ver `capturas/panel-web.png`. |
| **Medición** | `herramientas/medir_impacto.py` mide GPU, CPU y RAM sin overlays; la CPU por diferencia de ticks en `/proc`, porque el `%CPU` de `ps` promedia desde el arranque. |

Por qué la v2 es así, con números: [`docs/meta-triangulado-2026-11.md`](docs/meta-triangulado-2026-11.md)
y `RELEVO.md` (local, fuera del repo público).

## Privacidad

- Solo lee píxeles de tu pantalla. No abre el proceso del juego, no lee memoria, no
  inyecta, no usa overlays ni macros.
- Las capturas y la base de partidas se quedan en tu máquina (`salida/`, `datos/`).
- Al API pública solo se le pide el id de partida o tu SteamID64; no se sube nada.
- La app no tiene telemetría.

## Límites conocidos

- **El contador de almas del HUD no se publica**: `tesseract` no acierta con la fuente
  del juego (0 de 12 configuraciones) y falta el banco de plantillas propio. El reloj y
  el id sí se leen.
- El broadcast llega 20–25 s tarde. Se muestra con su edad; no se disimula.
- **La puntuación de economía es solo de Abrams**: el camino, los contras y el ranking de
  ítems salen de sus 626 partidas. Para otro héroe el panel da su apertura y su camino
  observado (si hay timelines descargados) y lo dice en la cabecera.
- Solo español.
- La calibración del HUD depende de la resolución y del parche; hay un calibrador.
- El marcador solo se lee con Tab abierto.
- Probar la lectura real necesita tus propias capturas en `verdad/`; sin ellas, esas
  pruebas se saltan y lo dicen.

## Desarrollo

```bash
python3 -m compileall -q coach herramientas tests run.py panel_nativo.py
python3 -m pytest -q
python3 coach/iconos.py                                  # baja el arte (una vez)
python3 herramientas/evaluar_motor.py --partidas 60      # A/B del motor
```

La CI corre en Ubuntu 24.04 con GTK bajo Xvfb, en Python 3.12 y 3.13: descarga los
iconos y ejecuta la suite completa, incluida la puerta de pintado de la UI.

### ¿La app abierta es la última?

El panel no se recarga en caliente: si editas código con la app abierta, sigue
mostrando lo viejo sin avisar. Se comprueba en un comando:

```bash
python3 herramientas/version.py    # 0 si está al día, 2 si quedó atrás
curl -s http://127.0.0.1:8090/api/version   # con la app corriendo
```

Regla: **si tocas código, reinicia antes de creerle al panel**. Detalle, veredictos y
limitaciones en [`docs/VERSION.md`](docs/VERSION.md).

## Assets y licencia

Código bajo licencia MIT ([`LICENSE`](LICENSE)). El arte de Deadlock es de Valve y **no**
se distribuye: ver [`NOTICE`](NOTICE). Deadlock es una marca de Valve Corporation; este
proyecto no está afiliado ni respaldado por Valve.
