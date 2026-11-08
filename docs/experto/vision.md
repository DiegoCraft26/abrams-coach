# Visión: captura barata con KWin (ScreenShot2)

Medido el **2026-11-08** aquí: KWin 6.8.2 Wayland, DP-2 2560x1440 en +1920+0, HDMI-A-1
1920x1080 en +0+360 (escritorio 4480x1440), Python 3.14 con `gi` y PIL 13. No había partida
abierta: lo que no se pudo medir con el juego va marcado **sin medir**.

| Vía | Mediana | PNG en disco | Veredicto |
|---|---|---|---|
| `spectacle -f` (lo que usa `coach/hud.py`) | 402 ms | sí, 707 KB | caro |
| `spectacle -m` / `-a` | 316–425 / 328 ms | sí | sigue en cientos de ms |
| `spectacle -r` | cuelga | — | inservible en background |
| **`ScreenShot2.CaptureArea`** | **1.6–4.7 ms** | **no, 0 bytes** | ganadora |

## La interfaz, tal como está hoy

```
$ qdbus6 --xml-interface org.kde.KWin /org/kde/KWin/ScreenShot2
property read uint Version                                   -> 5
method QVariantMap CaptureArea(int x, int y, uint width, uint height,
                               QVariantMap options, QDBusUnixFileDescriptor pipe)
method QVariantMap CaptureActiveScreen(QVariantMap options, QDBusUnixFileDescriptor pipe)
method QVariantMap CaptureActiveWindow(QVariantMap options, QDBusUnixFileDescriptor pipe)
method QVariantMap CaptureWorkspace(QVariantMap options, QDBusUnixFileDescriptor pipe)
```

Opciones: `{"include-cursor": true|false}` (las dos responden). Devuelve
`{'format': 16, 'width': 2560, 'height': 1440, 'stride': 10240, 'scale': 1.0, 'type': 'raw'}`;
`CaptureActiveScreen` añade `'screen': 'DP-2'` y `CaptureActiveWindow` añade `'windowId'`.
`format 16` = `QImage::Format_RGBX8888` y `type` es `raw`: píxeles, **nunca** PNG.

Cuatro trampas, comprobadas a golpes: (1) `qdbus6` y `gdbus` no sirven, no pasan descriptores;
(2) en el argumento `h` va el extremo de **escritura** del pipe — con el de lectura devuelve
metadatos correctos y **0 bytes**; (3) KWin **no cierra su extremo**, no hay EOF: se leen
`stride*height` bytes y se corta (esperar el cierre del hilo lector cuesta 10 s); (4) el pipe
son 64 KB y el compositor escribe síncrono, hay que drenarlo en otro hilo o la llamada no vuelve.

## Receta concreta

Está en [`docs/experto/captura_vision.py`](captura_vision.py), copiable y autocontenida: crea el
pipe, pasa el extremo de escritura, drena en un hilo y devuelve un `PIL.Image` en modo `RGBX`
sin copiar memoria ni tocar disco.

```
$ python3 docs/experto/captura_vision.py 3150 8 115 44
115x44 10.06 ms
$ python3 docs/experto/captura_vision.py 1950 1080 500 360
500x360 16.66 ms
$ python3 docs/experto/captura_vision.py 4050 1330 430 110
430x110 12.56 ms
```

Cada invocación de consola es **proceso frío**: paga la primera captura y, sobre todo, los
imports (`gi` + PIL = 70–77 ms una vez). En caliente, dentro del coach, la misma caja cuesta
**min 1.25 / mediana 1.58 / p95 2.52 / max 4.28 ms** (20 capturas seguidas).

| Medición | Valores (ms) | Referencia |
|---|---|---|
| `spectacle -f` a 4480x1440 | 391 / 402 / 430 | 402 |
| `spectacle -m` (contenido ligero / pesado) | 312-323 / 425-426 | 316 / 425 |
| `spectacle -a` / `-r` con `timeout 6` | 323 / 328 / 331 · sin fichero | 328 · cuelga |
| DBus reloj 115x44, en caliente | 1.25 / 1.58 / 4.28 | 1.58 |
| DBus oro 500x360, en caliente | 2.8 – 7.8 | 4.65 |
| DBus las 3 cajas en un ciclo, 20 vueltas | 7.3 – 10.5 | 8.29 |
| DBus `CaptureActiveScreen` 2560x1440 | 21.7 / 24.6 / 25.8 | 24.6 |
| DBus `CaptureWorkspace` 4480x1440 | 30.8 / 33.8 / 37.1 | 33.9 |

## Región mínima y coordenadas

`coach/hud.py` sigue vigente con esta geometría: sobre
`salida/calibracion/marcador_real_juego.png` (2560x1440, juego en DP-2) la caja del reloj
`(3150, 8, 3265, 52)` recorta **7:40** completo, sin cortar el primer dígito.

| Qué | Caja en escritorio | Tamaño | Coste |
|---|---|---|---|
| Reloj | `(3150, 8, 3265, 52)` | 115x44 | 1.6 ms |
| Bloque de oro de `_oro_amplio` | `(1950, 1080, 2450, 1440)` | 500x360 | 4.7 ms |
| "MATCH:" esquina inferior derecha | `(4050, 1330, 4480, 1440)` | 430x110 | 2.9 ms |

Tres `CaptureArea` (8.3 ms) baten a un cuadro completo recortado (`Workspace`, 33.9 ms): lo
barato es pedir poco, no reutilizar un cuadro grande. La caja del "MATCH:" **no está
verificada**: en la única captura real disponible esa esquina está vacía y `tesseract` no
encuentra "MATCH" en toda la imagen; confirmar con partida abierta mirando `/tmp/vision-ultimo.png`.

## Pantalla completa y foco

`CaptureActiveScreen` devolvió `'screen': 'DP-2'` y capturó bien una ventana a pantalla completa
(contenido real, no negro): el compositor entrega superficies de ventana. Con el **juego** a
pantalla completa, enfocado y sin enfocar: **sin medir** (no había partida abierta). Pendiente:
`python3 docs/experto/captura_vision.py 3150 8 115 44` con partida abierta y comparar el reloj.

## Plan B si ScreenShot2 no estuviera

`spectacle -m -b -n -o` cuesta 316–425 ms y sirve si el juego está en un solo monitor. El portal
`ScreenCast` + PipeWire daría flujo continuo pero pide permiso una vez (**sin medir** su coste).
`grim`, `wf-recorder` y `flameshot` no están instalados. `import` de ImageMagick falla en 31 ms
y solo vería XWayland.

## Riesgos

- **Sin medir con el juego abierto**: no comprobé la inclusión de un juego Vulkan a pantalla
  completa (posible scanout directo); un vídeo a pantalla completa sí salió bien.
- Cada `CaptureArea` fuerza al compositor a componer un cuadro: a 15 Hz, ~2 % de un núcleo.
  Impacto en el fps del juego: sin medir.
- Depende de `kwin_wayland` Version 5 y de la misma sesión; `gi` y `PIL` deben existir en el
  intérprete del coach (el `python3` del sistema los tiene).
- La API **no pide permiso**: cualquier proceso del usuario lee la pantalla. Es el modelo de
  KWin; conviene saberlo antes de exponerla fuera de la máquina.
- Coordenadas atadas a 4480x1440: si cambia la disposición de monitores, recalcular las cajas.
- Un `EPIPE` si el proceso muere a mitad deja aviso en el journal de KWin: inofensivo, ruidoso.
