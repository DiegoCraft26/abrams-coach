# QA de rendimiento — 2026-11-08

Medido en la máquina de desarrollo (Ryzen 7 5700G, 16 núcleos, 15 GB de RAM, KDE Wayland,
escritorio 4480×1440 en dos monitores) con el árbol de trabajo `wip/fixes-sesion-2026-11-08`.
Carga media del sistema durante las mediciones: 1.03–1.17 sobre 16 núcleos.

Nada de esto se midió con el juego abierto: no se lanzó el juego (regla 1) y no había
partida. Todos los números de «con juego» están hechos con la comprobación de proceso
forzada a `True`, así que son el coste del camino real, pero **sin partida real**: el OCR
leyó el escritorio, no el HUD del juego.

## Cómo se midió

| Qué | Con qué |
|---|---|
| CPU de un proceso | `/proc/<pid>/stat` (utime+stime+cstime de todo el árbol), muestreado cada segundo; los hijos (`tesseract`) entran por `cutime`/`cstime` |
| RAM | `/proc/<pid>/statm`, y `ps` cuando hay que comparar con `docs/MEDICIONES.md` |
| Captura y OCR | `herramientas/medir_latencia.py` y bancos propios sobre `coach/hud.py`, `coach/fuentes/captura.py` y `coach/fuentes/hud_rapido.py` |
| Bucle con el API lento | `coach.en_vivo.partida_activa` envuelto con 10 s de retardo; cada publicación anotada con su hora |
| Panel | `coach.ui.Panel` construido contra un servidor con datos, **sin ventana visible** (no se tocó el escritorio) |
| Instancias | propias, en `:8099`. La del usuario (`:8090`) solo se miró con `/proc`, sin tocarla |

## Antes / después

### Procesos en reposo (sin juego abierto, sin partida)

| Proceso | Antes | Después | Nota |
|---|---|---|---|
| `run.py --fuente vivo` con HUD | **10.98 %** de un núcleo · **126.9 → 151.9 MB** | **1.10 %** · **52.8 → 53.3 MB** | el antes es el árbol sin el arreglo de esta sesión; la diferencia es la captura del escritorio encendida sin juego |
| `run.py --fuente vivo --sin-hud` | 0.45 % · 51.4 → 52.0 MB | 0.45 % · 51.4 → 52.0 MB | sin cambios |
| `run.py --fuente simulado` | 1.03 % · 33.8 MB a los 18 s | 1.03 % · 33.8 MB | igual que los 34.1 MB de `MEDICIONES.md` |
| `run.py --fuente vivo` del usuario (`:8090`, 2 h 30 arriba) | 0.02 % · 72.2 MB | — | solo lectura de `/proc` |
| Panel nativo (sin ventana) | 0.34 % · 78.9 MB | 0.34 % · 78.9 MB | payload de `/api/estado`: 11,800 B |

### Con datos: el camino de la visión, con el juego «abierto»

| Qué | Antes | Después |
|---|---|---|
| Hilo de captura compartida (escritorio 4480×1440) | `spectacle` cada 0.05 s: **~101 % de un núcleo** (8.77 % propio + 13.94 s de CPU de los hijos en 15 s), 2.20 capturas/s de 459 ms | KWin cada 0.15 s: **10.4 %**, 5.7 capturas/s de 37 ms |
| Captura de una caja del HUD | 415 ms (`spectacle -f` entero y recortar) | reloj **1.2 ms** · oro **3.1 ms** · MATCH **1.8 ms** |
| Captura del escritorio entero | 463 ms + PNG de 716 KB en disco | 34.9 ms en memoria, sin archivo |
| `leer_hud()` (reloj + oro) | 513 ms con el camino de `spectacle` | **3.9 ms** si los píxeles de las cajas no cambiaron · **279 ms** si cambiaron las dos |
| `leer_match_id()` | 466.7 ms | **1.4 ms** si el MATCH no cambió · **139.7 ms** la primera vez |
| Lectura completa del HUD (`hud_rapido`, reloj y oro en paralelo) | 127 ms, 7.9 lecturas/s (`MEDICIONES.md`) | **116 ms**, 8.6 lecturas/s |
| Coach entero con el juego «abierto» y el HUD a 2 Hz | sin medir antes (el árbol anterior no se puede correr sin cambiar de rama) | **49.89 %** de un núcleo · **175.5 → 175.7 MB** |

El «antes» de la fila de `leer_hud()` es el código nuevo con KWin apagado a propósito
(`captura_kwin.capturar` devolviendo `None`): cae a `spectacle -f` y recorta las mismas
cajas. Los 916 ms que dice `coach/hud.py` corresponden al `leer_hud` de HEAD, que capturaba
una vez por caja; no se reprodujeron aquí porque eso exigía correr el código de HEAD, y esta sesión no cambia de rama.

### El bucle cuando el API tarda 10 s

Retardo de 10 s inyectado en `partida_activa` y `buscar_en_listado`, midiendo la hora de
cada publicación:

| Situación | Hueco entre publicaciones | Qué se ve |
|---|---|---|
| API normal, sin partida | 3.08 s (17 publicaciones en 50 s) | build de apertura |
| API a 10 s, sin partida | **13.08 s** (10 s de espera + 3 s de pausa) | el bucle principal se queda bloqueado en la llamada; el hilo del HUD sigue por su lado |
| API a 10 s, con partida ya conocida | **3.00 s** | el API no se toca en el ciclo; el stream manda |

No hay desbordamiento ni reintentos en cascada: el bucle espera lo que tarde el API y
después sigue. Lo que sí pasa es que con el API a 10 s el panel se queda por encima del
umbral de 8 s (`UMBRAL_RANCIO_S`) entre publicación y publicación y marca los datos como
rancios; con contenido estático (build de apertura) lo marcó el 37 % de las muestras.

## Regresiones encontradas

1. **La captura del escritorio se encendía sin juego abierto.** `arrancar_hud()` llamaba a
   `captura.global_()` al arrancar y el hilo seguía capturando el escritorio entero a 5.7 Hz
   para siempre, aunque `hilo_hud` ya comprobaba `juego_abierto()` y no leyera nada.
   Coste medido: **10.98 % de un núcleo y +100 MB** en un coach sin partida.
   **Arreglado** en `coach/nucleo_vivo.py`: la captura se enciende y se apaga con
   `juego_abierto()`, el mismo chequeo que ya gateaba la lectura, así que no cambia nada
   de lo que ve el jugador.
2. **`medir_latencias()` arrancaba la captura solo para leer métricas.** Con
   `hud_ocr: false` y sin `--sin-hud`, el panel pagaba el hilo de captura para rellenar un
   número. **Arreglado**: `captura.metricas_si_arriba()` informa si ya está arriba y no la
   enciende; cuando no corre, el panel muestra `captura_ms` vacío, que es la verdad.

Ninguna de las dos es una regresión contra `docs/MEDICIONES.md` (ese documento no mide el
modo vivo sin partida): las dos son coste que ya venía del cambio de visión y que ahora
está apagado cuando no hace falta.

## Lo que empeoró (y no se arregla aquí)

- **El OCR del HUD cuesta 261 ms de CPU por lectura** (propio 20 ms + dos `tesseract` de
  ~120 ms cada uno, en paralelo): mediana de 116 ms de reloj. A los 2 Hz que pide
  `config/coach.yaml` son **~52 % de un núcleo durante toda la partida**, más el 10.4 % de
  la captura. No es nuevo (el camino de OCR es el mismo de HEAD), pero es el número más
  caro de la app y no está en `MEDICIONES.md`. Dos formas de bajarlo, ninguna aplicada
  porque cambian comportamiento y no son regresiones: leer a 1 Hz (el reloj del HUD cambia
  una vez por segundo) o no repetir el OCR cuando los píxeles de la caja son idénticos,
  como ya hace `coach/hud.py`.
- **175 MB de RAM** con el HUD y la captura arriba, contra 53 MB sin ellos. Estable: 175.5
  → 175.7 MB en 45 s, sin fuga.
- `juego_abierto()` lanza `ps -eo args` cada 5 s desde el hilo del HUD: 14.3 ms por
  llamada, ~0.3 % de un núcleo con el juego cerrado. Viene de antes y no se tocó.

## Comparación con `docs/MEDICIONES.md`

| Dato del documento | Documentado | Medido hoy | Veredicto |
|---|---|---|---|
| Captura `spectacle -f` 4480×1440 | 415–514 ms | 463 ms (mediana de 3, peor 666) | igual |
| Lectura del HUD (reloj + oro) | 127 ms · 7.9 /s | 116 ms · 8.6 /s | igual |
| RAM del coach simulado | 34.1 MB al arrancar | 33.8 MB a los 18 s | igual |
| RAM del panel | 127.5 MB | 78.9 MB sin ventana | no comparable (sin ventana no reserva superficies) |
| CPU del panel | 0.2 % | 0.34 % sin ventana | no comparable |
| Estabilidad 15 min | coach 33.8 MB, panel +1.6 MB | 33.7 MB a los 48 s; panel plano en 25 s | sin medir a 15 min |
| Latencia del broadcast (20–25 s) | 20–25 s | sin medir (no hubo partida) | sin medir |

## Reproducir

```bash
# coste de la visión: cajas por KWin contra spectacle
python3 herramientas/medir_latencia.py --url http://127.0.0.1:8099
# CPU y RAM de una instancia propia
python3 run.py --fuente vivo --puerto 8099 &   # y luego /proc/<pid>/stat durante 60 s
# el bucle con el API lento: 10 s de retardo en coach.en_vivo.partida_activa
```

## Veredicto

El cambio de visión mejora todo lo que tocó (captura 415 → 1–3 ms, cuadro compartido 101 % → 10.4 % de un núcleo, HUD 513 → 3.9 ms) y no hay ninguna regresión contra `docs/MEDICIONES.md`; la captura encendida sin juego (10.98 % de un núcleo y +100 MB) queda arreglada, y lo caro que sobra es el OCR del HUD a 2 Hz (52 % de un núcleo), que viene de antes y no se tocó.
