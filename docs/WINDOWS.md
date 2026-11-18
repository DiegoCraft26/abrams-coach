# Windows: diseño de la versión, con fuentes y sin fingir

Estado: **diseño, no implementación.** Este documento no reporta ninguna medición hecha en
Windows. No hubo acceso a una máquina Windows para escribirlo; todo lo que sigue son fuentes
consultadas el **2026-11-18**, aritmética propia marcada como tal, y una lista de
experimentos que hay que correr antes de afirmar nada.

Cada afirmación lleva etiqueta:

| Etiqueta | Significa |
|---|---|
| **[F]** | Dato de fuente: está escrito en el enlace que acompaña. |
| **[E]** | Estimación nuestra: aritmética o inferencia a partir de lo anterior. |
| **[?]** | No se puede resolver sin una máquina Windows. Va con el experimento que lo resuelve. |

Base interna: [ARQUITECTURA.md](ARQUITECTURA.md), [DATOS-DEL-JUEGO.md](DATOS-DEL-JUEGO.md),
[MEDICIONES.md](MEDICIONES.md), [../herramientas/overlay.py](../herramientas/overlay.py),
[../coach/fuentes/captura.py](../coach/fuentes/captura.py).

---

## Estado real (2026-11-18)

- **Hecho y verificado en Linux**: el motor se importa sin GTK. `tests/test_plataforma.py`
  carga `coach.estado`, `coach.motor`, `coach.valor`, `coach.servidor`, `coach.historico` y
  `coach.fuentes.captura` en un subproceso con un `gi` falso que falla. La captura de KWin
  pasa a import perezoso, así que una máquina sin KDE no estalla al arrancar.
- **CI**: trabajo `plataforma` en `windows-latest` que corre esa prueba. Se ejecutará en el
  próximo push; no se ha visto correr todavía en un runner real.
- **Escrito y sin probar en Windows**: `coach/fuentes/captura_windows.py` (dxcam →
  DXGI, o mss → GDI, y un `RuntimeError` con el comando de instalación si no hay
  ninguno). `CapturaCompartida` acepta un backend inyectable, y hay cinco pruebas con
  backends falsos que verifican el hilo, los fallos y la selección por plataforma. En
  Linux el módulo se importa y falla con motivo al usarse.
- **Escrito y ejecutado bajo Wine** (2026-11-18): `coach/ui/overlay_windows.py` — ventana
  `WS_POPUP` con `LAYERED|TRANSPARENT|NOACTIVATE|TOOLWINDOW`, topmost por `SetWindowPos`,
  pintado por `UpdateLayeredWindow` (DIB 32 bits) y posición por esquina.
  `herramientas/probar_windows_wine.sh` descarga el Python embebido de python.org, lo corre
  bajo Wine y verifica el ciclo completo: `RegisterClassW`, `CreateWindowExW` (devuelve
  HWND), `UpdateLayeredWindow`, `ShowWindow`, `DestroyWindow`. **9 comprobaciones, todas en
  verde.**
- **Lo que Wine cazó y Linux no podía**: `ctypes.wintypes` **no** trae `WNDCLASSW` (hay que
  declararla) y sin `restype` explícito un `HWND` de 64 bits se trunca a 32. Las dos cosas
  habrían hecho fallar `crear()` en un Windows real.
- **La captura también se ejecutó bajo Wine** con `mss` (GDI) y Pillow reales: devuelve
  una imagen **RGB de 2560×1440 en 27,7 ms**. Contra los 415–514 ms de KWin en Linux, el
  camino de Windows es **unas 15 veces más barato**, incluso sin DXGI.
- **Lo que Wine no sustituye**: DXGI de verdad (`dxcam` no está en ese entorno), el
  compositor de Windows, la composición sobre un juego en ventana completa y el coste
  dentro del juego. Eso sigue necesitando una máquina Windows.
- **Sin empezar**: plantillas del HUD a 1080p/1440p y el empaquetado.

## 0. Las tres decisiones, en corto

1. **Captura: DXGI Desktop Duplication** (`IDXGIOutput1::DuplicateOutput` +
   `IDXGIOutputDuplication::AcquireNextFrame`), con [dxcam](https://github.com/ra1nty/DXcam)
   como envoltorio en la primera fase. Razón: entrega el escritorio por GPU sin borde
   amarillo del sistema y sin diálogo de consentimiento, y documenta sus propios errores de
   recuperación; WGC dibuja borde y exige consentimiento, y `mss` va por GDI.
2. **Overlay: ventana Win32 con `WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE |
   WS_EX_TOOLWINDOW`**, alfa por píxel con `UpdateLayeredWindow`, y *topmost* por
   `SetWindowPos`. Razón: la documentación de Microsoft describe exactamente ese conjunto
   para "pintar sin recibir ratón" y "no activarse al clic"; no hay layer-shell en Windows
   y no hace falta inventarlo.
3. **Empaquetado: PyInstaller `--onedir --windowed` + un script de PowerShell** que
   descarga, verifica SHA-256, descomprime en `%LOCALAPPDATA%`, agrega al PATH del usuario y
   registra el autostart. Razón: `--onefile` descomprime en temporal en cada arranque
   ([documentado](https://pyinstaller.org/en/stable/usage.html)), lo peor posible para una
   app que arranca con el juego.

Detalle y porqués abajo. Lo que **no** se puede sostener sin medir está en §6.

---

## 1. Captura

### 1.1 Qué tiene que reemplazar

Hoy la captura cuesta **415–514 ms por cuadro** con `spectacle -f` a 4480×1440 y **34–38 ms**
con KWin `CaptureWorkspace`, a 2 Hz, con un solo hilo que publica el último cuadro
([MEDICIONES.md](MEDICIONES.md), [../coach/fuentes/captura.py](../coach/fuentes/captura.py)).
En Windows no existe `org.kde.KWin.ScreenShot2` ni `spectacle`, así que esa pieza se tira
completa; lo que **sí** sobrevive es el contrato: un hilo, un cuadro, marca de tiempo,
métricas de duración y fallos. Eso se conserva tal cual y se le cambia el motor por dentro.

El cuadro no se usa para "verse": se recortan cajas y se leen con tesseract. Por eso el
criterio no es FPS sino **latencia de un cuadro a 2 Hz y frescura** (que el cuadro sea de
ahora, no uno repetido).

### 1.2 Las cuatro rutas

| Ruta | API concreta | Windows mínimo | Qué entrega | Borde / consentimiento |
|---|---|---|---|---|
| **DXGI Desktop Duplication** | `IDXGIOutput1::DuplicateOutput`, `IDXGIOutputDuplication::AcquireNextFrame` | **Windows 8** [F](https://learn.microsoft.com/en-us/windows/win32/api/dxgi1_2/nf-dxgi1_2-idxgioutputduplication-acquirenextframe); existe también con Platform Update en Win7 [F](https://learn.microsoft.com/en-us/windows/win32/api/dxgi1_2/nf-dxgi1_2-idxgioutput1-duplicateoutput) | Textura D3D11 del escritorio + rectángulos sucios y de movimiento | Ninguno: no dibuja nada en pantalla [F](https://learn.microsoft.com/en-us/windows/win32/direct3ddxgi/desktop-dup-api) |
| **Windows Graphics Capture (WGC)** | `GraphicsCaptureItem`, `Direct3D11CaptureFramePool`, `GraphicsCaptureSession.StartCapture` | **Windows 10 1803 (10.0.17134)** [F](https://learn.microsoft.com/en-us/uwp/api/windows.graphics.capture.graphicscapturesession) | Textura por `FrameArrived` o `TryGetNextFrame` | **Borde amarillo del sistema** alrededor de lo capturado [F](https://learn.microsoft.com/en-us/windows/apps/develop/media-authoring-processing/screen-capture) |
| **`mss`** | `BitBlt` desde `GetWindowDC(0)` a un DIB (`CreateDIBSection`) | Cualquier Windows | Bytes RGBA en memoria del sistema | Ninguno |
| **`dxcam`** | Envoltorio de las dos primeras (`backend="dxgi"` por defecto, `backend="winrt"`) | Windows 8+ (hereda) | `numpy.ndarray` | Hereda |

Fuentes de `mss` y `dxcam`: el backend de Windows de mss se llama literalmente
[`gdi.py`](https://github.com/BoboTiG/python-mss/blob/main/src/mss/windows/gdi.py) y usa
`BitBlt` con `SRCCOPY | CAPTUREBLT`; dxcam se define como "high-performance python
screenshot and capture library for Windows based on the Desktop Duplication API"
([README](https://github.com/ra1nty/DXcam)).

### 1.3 Coste por cuadro: lo que está escrito y lo que estimamos

**Lo que no existe:** Microsoft documenta la API, no su latencia. No hay ninguna cifra
oficial de milisegundos por cuadro para DXGI ni para WGC. Cualquiera que la cite sin medir
la está inventando, nosotros incluidos.

**Lo que sí está escrito**, y es de terceros:

- dxcam reporta **239.19 FPS de media** en su benchmark (5900X + RTX 3090, escena a 240 Hz,
  "240+fps on 1080p" en la introducción) contra 75.87 de python-mss y 118.36 de D3DShot
  ([README](https://github.com/ra1nty/DXcam)). Ojo: mide su bucle de buffer circular, no el
  coste de convertir un cuadro a `numpy` para nuestro uso. **No es nuestra cifra.**
- mss se describe como "ultra fast ... pure python using ctypes"
  ([README](https://github.com/BoboTiG/python-mss)) pero por dentro es GDI: la copia la hace
  la CPU. Con `CAPTUREBLT` activo, además, captura capas extra.

**Lo que estimamos nosotros [E]**, con la aritmética a la vista para que se pueda refutar:

| Resolución | Bytes de un cuadro BGRA8 | Copia GPU→CPU (supuesto ~8 GB/s efectivos) | Total estimado con conversión y recorte |
|---|---|---|---|
| 1920×1080 | 1920·1080·4 = **8.29 MB** | ~1.0 ms | **3–8 ms** |
| 2560×1440 | 2560·1440·4 = **14.75 MB** | ~1.8 ms | **6–14 ms** |

Formato: DXGI entrega **siempre `DXGI_FORMAT_B8G8R8A8_UNORM`**, "no matter what the current
display mode is" [F](https://learn.microsoft.com/en-us/windows/win32/direct3ddxgi/desktop-dup-api).
Eso quiere decir que con HDR activado **no** llega FP16 por esta vía y las plantillas siguen
siendo de 8 bits; el problema de HDR que sí existe en WGC (que avisa que "the content pixel
format might not necessarily be DXGI_FORMAT_B8G8R8A8_UNORM" con color HD activo
[F](https://learn.microsoft.com/en-us/windows/apps/develop/media-authoring-processing/screen-capture))
no nos toca si vamos por DXGI.

Comparación honesta con lo de hoy: 3–14 ms estimados contra 415–514 ms de `spectacle` es
entre **30× y 170×** menos por cuadro [E]; contra los 34–38 ms de KWin, del mismo orden o
mejor [E]. A 2 Hz eso deja el 97 % del presupuesto de 500 ms libre para OCR y motor. **Esto
es una hipótesis, no un resultado**: la fase (a) la mide o la tumba.

### 1.4 Por qué DXGI y no WGC

1. **El borde amarillo es inaceptable en un overlay.** WGC "drawn by the system around the
   actively captured item"
   [F](https://learn.microsoft.com/en-us/windows/apps/develop/media-authoring-processing/screen-capture).
   Quitarlo no es un flag: `IsBorderRequired` existe desde **10.0.20348**, requiere
   `GraphicsCaptureAccess.RequestAccessAsync(Borderless)`, el paquete debe declarar la
   capacidad `graphicsCaptureWithoutBorder`, y si otro proceso pide borde, se dibuja igual
   [F](https://learn.microsoft.com/en-us/uwp/api/windows.graphics.capture.graphicscapturesession.isborderrequired).
   Para una app sin identidad de paquete y sin querer un prompt, es un callejón.
2. **WGC pide consentimiento en UI del sistema.** El flujo documentado es
   `GraphicsCapturePicker` → el usuario elige → recién entonces hay `GraphicsCaptureItem`
   [F](https://learn.microsoft.com/en-us/windows/apps/develop/media-authoring-processing/screen-capture).
   Hay una vía de interoperabilidad para crear el ítem desde un `HWND` sin picker, pero no
   está documentada como flujo soportado y **no la damos por buena [?]**.
3. **DXGI documenta la recuperación.** `AcquireNextFrame` devuelve
   `DXGI_ERROR_ACCESS_LOST` cuando "a different type of image is displayed on the desktop",
   con tres ejemplos textuales: cambio de escritorio, cambio de modo y "switch from DWM on,
   DWM off, or other full-screen application"; la salida es soltar la interfaz y crear otra
   [F](https://learn.microsoft.com/en-us/windows/win32/api/dxgi1_2/nf-dxgi1_2-idxgioutputduplication-acquirenextframe).
   Eso es exactamente el caso "el jugador entra o sale del juego" y nos dice qué hacer.
4. **WGC puede ser más barato en un portátil** (su frame pool evita la copia manual) [E], pero
   no hay cifra publicada y el borde lo descalifica para este producto.

dxcam entra solo en la fase (a) porque expone los dos backends y devuelve `numpy` sin
escribir ctypes; sus wheels cubren CPython **3.10–3.14**
([README](https://github.com/ra1nty/DXcam)), que encaja con el `>= 3.11` del proyecto
([../requirements.txt](../requirements.txt)). Si en la fase (a) dxcam estorba (por ejemplo,
porque necesitamos `DuplicateOutput1` o los rectángulos sucios), se baja a un envoltorio
propio de ctypes sobre las mismas cuatro llamadas. **Decisión de implementación, reversible,
que no cambia el diseño.**

### 1.5 Modos de fallo documentados (esto sí es fuente)

| Situación | Qué devuelve | Qué hay que hacer |
|---|---|---|
| Cambio de escritorio, de modo, o app en pantalla completa | `DXGI_ERROR_ACCESS_LOST` | Soltar `IDXGIOutputDuplication` y crear otra [F](https://learn.microsoft.com/en-us/windows/win32/api/dxgi1_2/nf-dxgi1_2-idxgioutputduplication-acquirenextframe) |
| No hubo cuadro nuevo en el timeout | `DXGI_ERROR_WAIT_TIMEOUT` | No es error: reintentar; el timeout no se puede cancelar, así que nunca `INFINITE` [F](https://learn.microsoft.com/en-us/windows/win32/api/dxgi1_2/nf-dxgi1_2-idxgioutputduplication-acquirenextframe) |
| Se pidió otro cuadro sin soltar el anterior | `DXGI_ERROR_INVALID_CALL` | `ReleaseFrame()` siempre, incluso en el camino de error |
| Ya hay 4 procesos duplicando | `DXGI_ERROR_NOT_CURRENTLY_AVAILABLE` | Degradar a `mss` o avisar; el límite es 4 por sesión [F](https://learn.microsoft.com/en-us/windows/win32/api/dxgi1_2/nf-dxgi1_2-idxgioutput1-duplicateoutput) |
| Escritorio seguro (UAC, bloqueo) | `E_ACCESSDENIED` | Pausar la captura; no hay nada legítimo que leer ahí [F](https://learn.microsoft.com/en-us/windows/win32/api/dxgi1_2/nf-dxgi1_2-idxgioutput1-duplicateoutput) |
| Modo 8bpp o sin DWM | `DXGI_ERROR_UNSUPPORTED` | Esperar `WM_DISPLAYCHANGE` y reintentar [F](https://learn.microsoft.com/en-us/windows/win32/api/dxgi1_2/nf-dxgi1_2-idxgioutput1-duplicateoutput) |
| Sesión RDP desconectada | `DXGI_ERROR_SESSION_DISCONNECTED` | Pausar y reintentar al reconectar [F](https://learn.microsoft.com/en-us/windows/win32/api/dxgi1_2/nf-dxgi1_2-idxgioutput1-duplicateoutput) |
| GPU híbrida: el dispositivo D3D no es el de la salida | `E_INVALIDARG` | El `ID3D11Device` "must be created from the adapter to which the output is connected" [F](https://learn.microsoft.com/en-us/windows/win32/api/dxgi1_2/nf-dxgi1_2-idxgioutput1-duplicateoutput) |

El caso de GPU híbrida (portátiles con iGPU + dGPU) es el que más nos puede morder [?]:
elegir adaptador mal es `E_INVALIDARG`, y elegir bien puede significar copiar el cuadro por
el bus equivocado. Se resuelve enumerando adaptadores y probando `DuplicateOutput` en cada
salida, no adivinando.

### 1.6 Lo que cambia respecto de KWin (y no es solo la llamada)

- **Coordenadas.** Las cajas del HUD están en píxeles del escritorio de **4480×1440** y se
  escalan por el tamaño del cuadro ([../coach/fuentes/hud_rapido.py](../coach/fuentes/hud_rapido.py)).
  En Windows el escritorio puede ser 1920×1080, 2560×1440 o 3840×2160, y el juego puede
  estar en otro monitor. Hay que enumerar salidas y atar las cajas a **la salida del juego**,
  no a "el escritorio".
- **DPI.** La app debe declararse *per-monitor V2* (Windows 10 1703+), que es el modo en el
  que la aplicación "ve los píxeles crudos de cada pantalla"
  [F](https://learn.microsoft.com/en-us/windows/win32/hidpi/high-dpi-desktop-application-development-on-windows).
  Sin eso, Windows bitmap-escala y las cajas quedan corridas. Ojo: desde 1703 no se pueden
  mezclar modos de DPI en un árbol de ventanas
  [F](https://learn.microsoft.com/en-us/windows/win32/hidpi/high-dpi-desktop-application-development-on-windows).
- **`console.log`.** La ruta del repo es la de Linux
  (`~/.local/share/Steam/...`). En Windows vive bajo la carpeta de instalación de Steam
  (típicamente `C:\Program Files (x86)\Steam\steamapps\common\Deadlock\...`) y sigue
  necesitando `-condebug`. **No damos la ruta por buena sin verla en disco [?].**

---

## 2. Overlay

### 2.1 Requisitos, en orden

1. Que se vea **encima del juego** en ventana completa sin bordes.
2. Que **no reciba clics**: el jugador apunta ahí.
3. Que **no robe foco**: ni al mostrarse, ni al refrescarse, ni al ocultarse.
4. Que no estorbe: sin botón en la barra de tareas, sin entrada en Alt+Tab.
5. Que se pueda ocultar y mostrar sin tocar el juego.

En Linux eso lo resolvía una superficie `wlr-layer-shell` en la capa OVERLAY, con
`KeyboardMode.NONE` y `exclusive_zone = -1`
([../herramientas/overlay.py](../herramientas/overlay.py)). **Ese protocolo es de Wayland**
("create surfaces that are layers of the desktop", de `wlr-protocols`
[F](https://wayland.app/protocols/wlr-layer-shell-unstable-v1)); en Windows no existe. Se
reemplaza por cuatro bits de estilo y dos llamadas.

> **Corrección a la consigna.** `WS_EX_TOPMOST` **no** se pone con `SetWindowLongPtr`: la
> documentación dice, en la misma fila de la tabla, "To add or remove this style, use the
> **SetWindowPos** function"
> [F](https://learn.microsoft.com/en-us/windows/win32/winmsg/extended-window-styles). Los
> otros tres sí van por `SetWindowLongPtr(hWnd, GWL_EXSTYLE, ...)`.

### 2.2 El mapa de flags

| Flag / llamada | Efecto documentado | Para qué lo usamos |
|---|---|---|
| `WS_EX_LAYERED` (0x00080000) | Ventana por capas; "cannot be used if the window has a class style of either CS_OWNDC or CS_CLASSDC" [F](https://learn.microsoft.com/en-us/windows/win32/winmsg/extended-window-styles) | Base del alfa por píxel y del hit-test transparente |
| `WS_EX_TRANSPARENT` (0x00000020) | En ventanas por capas: "the shape of the layered window will be ignored and the mouse events will be passed to other windows underneath" [F](https://learn.microsoft.com/en-us/windows/win32/winmsg/window-features) | Clic a través |
| `WS_EX_NOACTIVATE` (0x08000000) | "does not become the foreground window when the user clicks it"; además no aparece en la barra de tareas por defecto [F](https://learn.microsoft.com/en-us/windows/win32/winmsg/extended-window-styles) | No robar foco |
| `WS_EX_TOOLWINDOW` (0x00000080) | "does not appear in the taskbar or in the dialog that appears when the user presses ALT+TAB" [F](https://learn.microsoft.com/en-us/windows/win32/winmsg/extended-window-styles) | Invisible para Alt+Tab |
| `SetWindowPos(HWND_TOPMOST, ..., SWP_NOACTIVATE)` | "Places the window above all non-topmost windows. The window maintains its topmost position even when it is deactivated"; `SWP_NOACTIVATE` = "Does not activate the window" [F](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowpos) | Encima del juego, sin foco |

Dos trampas que cuestan una tarde cada una:

- **`SetWindowLongPtr` no surte efecto hasta que se llama `SetWindowPos`.** "Certain window
  data is cached, so changes you make using SetWindowLongPtr will not take effect until you
  call the SetWindowPos function"
  [F](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowlongptrw),
  y el combo recomendado es `SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED`
  [F](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowpos).
- **No se puede mezclar color-key/alfa global con alfa por píxel.** Si se llama
  `SetLayeredWindowAttributes`, después `UpdateLayeredWindow` **falla** hasta limpiar y
  volver a poner el bit de capas
  [F](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setlayeredwindowattributes).

### 2.3 Transparencia: qué elegimos y por qué

| Vía | Qué da | Coste / límite |
|---|---|---|
| `SetLayeredWindowAttributes(LWA_ALPHA)` | Alfa global de toda la ventana | Ni esquinas redondeadas ni sombra: el rectángulo completo se aclara |
| `SetLayeredWindowAttributes(LWA_COLORKEY)` | Un color = transparente | El texto con antialias deja fleco del color clave; se ve sucio sobre el juego |
| **`UpdateLayeredWindow` con DIB de 32 bits** | **Alfa por píxel** | Hay que componer el mapa de bits uno mismo; es "for faster and more efficient animation or if per-pixel alpha is needed" [F](https://learn.microsoft.com/en-us/windows/win32/winmsg/window-features) |

**Decisión: `UpdateLayeredWindow`.** La tarjeta del overlay es un panel con esquinas
redondeadas y texto claro sobre oscuro; el color-key la deja con flecos y el alfa global la
deja lechosa. El precio es componer el DIB (texto con GDI/DirectWrite, iconos PNG ya
descargados por `/icono/{id}`) y mandarlo entero en cada refresco de 1 Hz. A 440×132 px son
**232 KB** por refresco [E] (440·132·4 = 232,320 B), que a 1 Hz es ruido.

Lo que **se conserva** de `overlay.py` es `resumen()`: esa función solo recorta
`/api/estado` a `{nombre, costo, tiles, rancio, edad}` y **no importa GTK**, así que pasa a
Windows sin tocar una línea
([../herramientas/overlay.py](../herramientas/overlay.py), líneas 128–162).

### 2.4 Cómo se evita robar foco (y cómo se comprueba)

El diseño: crear la ventana con `WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW`, mostrarla con
`SetWindowPos(..., SWP_NOACTIVATE | SWP_SHOWWINDOW)`, nunca llamar `SetForegroundWindow`, y
no crear controles hijos que pidan foco. `WS_EX_NOACTIVATE` documenta justo eso: no se vuelve
ventana de primer plano al clic
[F](https://learn.microsoft.com/en-us/windows/win32/winmsg/extended-window-styles).

**Cómo se prueba, no cómo se supone:** se lee `GetForegroundWindow()` antes y después de
mostrar, refrescar y ocultar la tarjeta 20 veces; el `HWND` no debe cambiar. Un clic de
prueba en el centro de la tarjeta debe llegar a la ventana de abajo. Eso es criterio de
aceptación en la fase (c), no una promesa.

### 2.5 Sobre el juego en pantalla completa

Aquí hay que ser preciso, porque la respuesta cambia según el modo:

- **Ventana sin bordes:** el juego es una ventana más y DWM compone. Una ventana topmost se
  dibuja encima. Es el caso que Microsoft describe como ventaja de la composición: los
  beneficios de *Fullscreen Optimizations* "include faster PC commands such as alt-tab,
  multiple monitor set ups and **overlays**"
  [F](https://devblogs.microsoft.com/directx/demystifying-full-screen-optimizations/).
- **Fullscreen exclusivo real (FSE):** "Fullscreen Exclusive mode gives your game complete
  ownership of the display and allocation of resources of your graphics card", y es en modo
  ventana donde "the Desktop Window Manager (DWM) has control of the display"
  [F](https://devblogs.microsoft.com/directx/demystifying-full-screen-optimizations/). Si el
  juego tiene la pantalla en exclusiva, **no hay garantía documentada** de que una ventana
  topmost se componga encima. No hay fuente que prometa lo contrario.

Lo que no sabemos: **en qué modo corre Deadlock** y si su "pantalla completa" es FSE o
*Fullscreen Optimizations* [?]. Se resuelve en la fase (c) mirando si el overlay aparece y si
`AcquireNextFrame` devuelve `ACCESS_LOST` al alternar; y se documenta el resultado con el
modo de video usado. Si resulta FSE, la salida honesta es pedir "ventana sin bordes" en la
UI, no inventar un hook.

### 2.6 `SetWindowDisplayAffinity`: sí aplica, pero al revés de lo que parece

`WDA_EXCLUDEFROMCAPTURE` (0x11, **Windows 10 2004+**) hace que la ventana "is displayed only
on a monitor. Everywhere else, the window does not appear at all", y su ejemplo de uso
documentado son "windows that show video recording controls, so that the controls are not
included in the capture"; sólo funciona con DWM componiendo
[F](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowdisplayaffinity).

Aplicado a nosotros: sirve para que **nuestra propia captura no lea nuestra tarjeta** y el
OCR no se envenene con nuestro texto. Dos cosas:

1. La documentación no enumera qué APIs respetan la afinidad ("a specific set of public
   operating system features and APIs"). Que DXGI Desktop Duplication la respete es
   **verificable, no asumible** [?].
2. Por diseño, la tarjeta va al **borde medio derecho**, que es el hueco que no pisa
   retratos, minimapa, inventario ni habilidades
   ([../herramientas/overlay.py](../herramientas/overlay.py), `_esquina`). Así que incluso si
   la exclusión no funcionara, no debería tocar las cajas del HUD. La prueba de la fase (c)
   es leer el HUD con la tarjeta encima y comprobar que el acierto no baja.

### 2.7 Lo que se pierde al dejar layer-shell

| En Linux daba | En Windows hay que hacerlo a mano |
|---|---|
| `Layer.OVERLAY` (encima de todo) | `SetWindowPos(HWND_TOPMOST)`; sólo garantizado en ventana/FSO |
| `KeyboardMode.NONE` | `WS_EX_NOACTIVATE` |
| Región de entrada vacía | `WS_EX_LAYERED | WS_EX_TRANSPARENT` |
| `exclusive_zone = -1` | Nada: no hay reserva de espacio; se posiciona a mano |
| Anclas y márgenes | `GetMonitorInfo` + aritmética por esquina |
| Recarga por `SIGUSR1` | Atajo global por definir (candidato: `RegisterHotKey`) [?] |

---

## 3. Qué se reutiliza y qué se rehace

### 3.1 Tal cual, sin cambios

| Pieza | Por qué sobrevive |
|---|---|
| `coach/motor.py`, `coach/decision/` | Python puro; el motor "no sabe de dónde vienen los datos" ([ARQUITECTURA.md](ARQUITECTURA.md)) |
| `coach/estado.py` | Normaliza dicts; no toca red ni disco |
| `coach/servidor.py` (`/api/estado`, SSE, `/icono/{id}`, `/tarjeta`) | HTTP estándar; el panel web y el overlay lo consumen igual |
| `coach/config.py` + `config/coach.yaml` | YAML y validación, sin API del SO |
| `coach/persistencia/` (SQLite + WAL) | SQLite es el mismo archivo y las mismas consultas |
| `data/replay_cache.json`, `herramientas/evaluar_motor.py`, `validar_camino.py` | Es el corpus de 626 partidas; se corre sin juego, también en Windows |
| `coach/iconos.py` + arte de `deadlock-api` | Descarga HTTP a `data/iconos/` |
| `tests/test_motor`, `test_invariantes`, `test_robustez`, `test_servidor`, `test_persistencia`, `test_backend` | No dependen de X11/Wayland/KWin |
| `resumen()` de `overlay.py` | Recorta el estado; cero GTK |

### 3.2 Rehacer

| Pieza | Qué pasa | Por qué |
|---|---|---|
| **Captura** (`coach/fuentes/captura_kwin.py`, rama KWin de `captura.py`) | Se reemplaza por DXGI; se conserva el contrato `CapturaCompartida` | No hay KWin ni D-Bus de KDE en Windows |
| **Overlay** (`herramientas/overlay.py`) | Se reescribe la ventana en Win32; `resumen()` se reutiliza | No hay layer-shell en Windows [F](https://wayland.app/protocols/wlr-layer-shell-unstable-v1) |
| **Panel nativo** (`panel_nativo.py`, `coach/ui/`) | Queda fuera de alcance; la UI portable es el panel web + la tarjeta | Depende de PyGObject/GTK4, que el proyecto instala por gestor de paquetes de la distro ([../requirements.txt](../requirements.txt)) |
| **Cajas del HUD** | Se recalibran por resolución y por escala de HUD | Están en píxeles de 4480×1440 con el juego en DP-2 |
| **`coach/fuentes/log_juego.py`** | Cambia la ruta del `console.log` | Ruta de Linux |
| **Empaquetado** | PyInstaller `--onedir`, tesseract incluido | No hay `pacman`/`apt`; y tesseract es binario externo |
| **Autostart** | Clave `HKCU\...\Run` en vez de ".desktop"/systemd | En Linux el proyecto lo evita a propósito (`arrancar.sh` no registra autostart) |
| **CI** | Job de Windows para lo portable | El job actual corre en Ubuntu |

Sobre tesseract en Windows: los instaladores oficiales recomendados por el proyecto son los
de [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki) (Tesseract 3.05, 4 y 5, 32 y
64 bits) y el binario queda por defecto en `C:\Program Files\Tesseract-OCR`
([docs](https://tesseract-ocr.github.io/tessdoc/Installation.html)). Es **Apache 2.0**
[F](https://tesseract-ocr.github.io/tessdoc/Installation.html), así que se puede redistribuir
dentro del instalador con su aviso; es la diferencia entre "instala Python y además tesseract"
y "un comando".

Sobre el autostart: la clave `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` es la vía
de usuario (sin admin), el valor es una línea de ≤ 260 caracteres, y **Windows no garantiza
cuándo la ejecuta**: "the system may choose to delay the execution of programs in the Run
key" [F](https://learn.microsoft.com/en-us/windows/win32/setupapi/run-and-runonce-registry-keys).
Consecuencia de diseño: la app no puede asumir que arrancó antes que el juego; tiene que
seguir funcionando si arranca después (igual que hoy con `abrams-coach esperar`).

---

## 4. Riesgo: qué dice el acuerdo de Steam y qué no hacemos

### 4.1 Texto vigente (revisión del 10 de septiembre de 2026)

Del [Steam Subscriber Agreement](https://store.steampowered.com/subscriber_agreement/),
§4.B, citado literal:

> "Steam and the Content and Services may include functionality designed to identify software
> or hardware processes or functionality that may give a player an unfair competitive
> advantage ... (**Cheats**). You agree that you will not create Cheats or assist third
> parties in any way to create or use Cheats. You agree that you will not directly or
> indirectly disable, circumvent, or otherwise interfere with the operation of software
> designed to prevent or report the use of Cheats."

> "You agree that you will not tamper with the execution of Steam or Content and Services
> unless otherwise authorized by Valve. You may not use Cheats, mods, hacks, or any other
> unauthorized third-party software, to modify any Subscription Marketplace process, the
> process of Steam account creation or otherwise in interacting with or controlling the
> processes or user interface of Steam Content and Services, except to the degree expressly
> permitted."

Y §4.C prohíbe la automatización, incluido "Earning rewards or progress without genuine user
input" [F](https://store.steampowered.com/subscriber_agreement/).

### 4.2 Lectura, sin adornos

| Cláusula | Qué prohíbe | Cómo queda un coach externo |
|---|---|---|
| 4.B, "Cheats" | Crear o ayudar a crear/usar software que dé ventaja competitiva injusta | **Es el riesgo residual y no lo podemos cerrar.** El término no está definido para overlays ni para lectores de pantalla. Sólo Valve puede resolverlo |
| 4.B, "tamper with the execution" | Tocar la ejecución de Steam o del juego | No lo hacemos: no abrimos el proceso, no escribimos archivos, no inyectamos |
| 4.B, "disable, circumvent, or otherwise interfere" con el anticheat | Interferir con VAC | No lo hacemos: no lo tocamos, no lo consultamos, no lo rodeamos |
| 4.B, "interacting with or controlling the processes or user interface" | Controlar la UI o los procesos | No lo hacemos: cero input, cero handles al juego |
| 4.C, "Automation" | Comprar, mover, pulsar por el usuario | No lo hacemos: el coach **aconseja**, no ejecuta |

Lo que no existe, y hay que decirlo: **no hay política publicada de Valve específica para
Deadlock sobre overlays o lectores de pantalla**, y en la investigación previa del repo
tampoco se encontró respuesta por escrito de soporte
([informes/meta-abrams-2026-11-18.md](../informes/meta-abrams-2026-11-18.md), §4).
Es "riesgo no cuantificado", no "riesgo cero". Nadie fuera de Valve puede prometer que no
hay ban.

Un dato de contexto que conviene tener a mano: la página de la tienda lista Deadlock como
**sólo Windows** y con **"OS: TBD"** en requisitos
([appdetails 1422450](https://store.steampowered.com/api/appdetails?appids=1422450&l=english),
consultado hoy). Es decir: ni la tienda oficial declara un mínimo de Windows todavía. Nuestra
versión de Windows soportada la decidimos nosotros, no la cita el juego.

### 4.3 Lo que NO hacemos (y se puede comprobar en el árbol)

- **Nada de memoria:** ni `ReadProcessMemory`, ni `/proc/*/mem`, ni handles con
  `PROCESS_VM_READ` al juego o a Steam.
- **Nada de inyección:** ni DLL, ni `CreateRemoteThread`, ni hooks, ni overlays dentro del
  swapchain del juego.
- **Nada de input:** ni `SendInput`, ni macros, ni auto-compra. Ni siquiera para "probar" el
  overlay: la prueba de clics se hace sobre una app de prueba, no sobre Deadlock.
- **Nada de archivos del juego:** no se lee ni se modifica nada dentro de
  `steamapps/common/Deadlock` salvo el `console.log` que **el propio juego** escribe y que ya
  se lee hoy en Linux ([../coach/fuentes/log_juego.py](../coach/fuentes/log_juego.py)).
- **Nada de red del juego:** no se intercepta tráfico.

La comprobación que ya existe en [../POLITICA.md](../POLITICA.md) (grep de `ptrace`,
`ReadProcessMemory`, `LD_PRELOAD`, `xdotool`, `uinput`) se extiende en Windows con
`ReadProcessMemory`, `WriteProcessMemory`, `CreateRemoteThread`, `SetWindowsHookEx`,
`SendInput` y `NtReadVirtualMemory`. Si aparece alguno, el build no sale.

**Nota sobre `LD_PRELOAD`.** `overlay.py` usa `LD_PRELOAD` para cargar
`libgtk4-layer-shell` **antes** de Wayland
([../herramientas/overlay.py](../herramientas/overlay.py), líneas 50–56). Eso es un truco de
enlace en el propio proceso, no una inyección en el juego, y en Windows desaparece con el
resto del overlay; conviene no confundirlo al auditar.

---

## 5. Plan por fases

Cada fase tiene **un** criterio que se puede medir y un resultado que la invalida. Nada de
"funciona" sin número.

### (a) Captura a 2 Hz estable

**Entregable:** capturador Windows con el mismo contrato que `CapturaCompartida` (último
cuadro, `ts`, `ms`, `fallos`, `ultimo_error`), sobre DXGI.

| Criterio | Umbral |
|---|---|
| Cuadros publicados en 10 min | ≥ 1 150 (2 Hz menos 4 %) |
| Latencia `grab()` → array listo | p50 ≤ 50 ms, p95 ≤ 120 ms, a 1080p **y** 1440p |
| Excepciones no capturadas | 0 |
| Recuperaciones por `ACCESS_LOST` | ≤ 1 por sesión, recuperada en ≤ 2 s |
| Frescura | ≥ 99 % de cuadros consecutivos distintos (hash del recorte del reloj) |
| CPU del proceso | ≤ 3 % de un núcleo en promedio |

**Cómo se mide:** log JSONL por cuadro (t0, t1, resultado de `AcquireNextFrame`), script de
10 min que imprime p50/p95 y cuenta cuadros repetidos. La prueba de frescura es la que atrapa
el bug clásico de quedarse con un cuadro cacheado y creer que va a 2 Hz.

**Invalida:** p95 > 120 ms, o cuadros repetidos, o una recuperación que no vuelve sola.

### (b) HUD leído ≥ 95 % en 1080p y 1440p

**Entregable:** cajas y preprocesado por resolución, más un conjunto de verdad.

| Criterio | Umbral |
|---|---|
| Acierto exacto del **reloj** | ≥ 95 % en 1920×1080 y ≥ 95 % en 2560×1440 |
| Acierto exacto del **oro** | ≥ 95 % en ambas |
| Error "seguro pero equivocado" (6 400 → 64) | ≤ 1 % de las lecturas |
| Lecturas vacías | permitidas; **no** cuentan como acierto |
| Latencia de una lectura | p95 ≤ 150 ms |

**Cómo se mide:** ≥ 300 cuadros por resolución con reloj y oro anotados a mano (de una
grabación, no de una partida en vivo); se corre el lector sobre el conjunto y se reporta la
matriz de confusión por campo. Se repite con **una** escala de HUD alternativa del juego para
saber si el escalado rompe las cajas.

**Invalida:** < 95 %, o > 1 % de errores seguros, o que sólo pase con la escala por defecto y
sin decirlo.

### (c) Overlay visible y click-through

**Entregable:** tarjeta Win32 con `resumen()` alimentado por `/api/estado`.

| # | Prueba | Umbral |
|---|---|---|
| 1 | Visible sobre el juego en ventana sin bordes (60 capturas a 1 s) | 60/60 |
| 2 | Clics sintéticos sobre la tarjeta que llegan a una app contadora debajo | 100/100 |
| 3 | `GetForegroundWindow()` antes/después de mostrar, refrescar y ocultar | mismo `HWND`, 20/20 |
| 4 | Ausente de la lista de Alt+Tab y de la barra de tareas | 0 apariciones |
| 5 | `GWL_EXSTYLE` conserva `LAYERED \| TRANSPARENT \| NOACTIVATE` tras 50 ciclos | 50/50 |
| 6 | HUD leído con la tarjeta encima vs sin ella | acierto no baja > 1 pp |

**Experimentos que acompañan:** ¿`WDA_EXCLUDEFROMCAPTURE` saca la tarjeta de nuestra propia
captura DXGI? ¿El modo de video del juego es FSE o FSO? Se anotan con el nombre del modo
usado; sin eso, la prueba 1 no significa nada.

**Invalida:** un solo clic perdido o un solo cambio de foco.

### (d) Instalador de una línea

| Criterio | Umbral |
|---|---|
| VM Windows 11 limpia, sin Python: un comando deja `abrams-coach --version` funcionando | ≤ 3 min, medido con `Measure-Command` |
| Pide elevación | 0 veces |
| Reinicio necesario | 0 |
| `abrams-coach demo` abre el panel | sí |
| Desinstalar deja el sistema como estaba (PATH, clave `Run`, `%LOCALAPPDATA%`) | diff vacío contra la lista previa |
| Procesos vivos tras desinstalar | 0 |

**Cómo se mide:** dos VMs (una limpia, una con Steam y Deadlock instalados), lista de rutas y
claves antes/después, y `Get-FileHash` del paquete contra el publicado.

**Invalida:** pedir admin, dejar residuos, o necesitar reinicio.

### (e) CI que corra lo que no depende de Windows

**Entregable:** el job de Ubuntu que ya existe
([../.github/workflows/ci.yml](../.github/workflows/ci.yml)) **sin tocar**, más un job de
Windows para la parte portable.

| Criterio | Umbral |
|---|---|
| Job Ubuntu (suite completa bajo Xvfb, invariantes, A/B del motor, archivado idempotente) | sigue verde |
| Job Windows: `compileall` + `test_motor`, `test_invariantes`, `test_robustez`, `test_servidor`, `test_persistencia`, `test_backend` | verde en `windows-latest` |
| Candado de portabilidad: test que falla si un módulo fuera de la UI importa `gi`/GTK | verde |
| Skips nuevos en Windows | 0 |

Hoy los módulos que importan GTK son `coach/ui/app.py`,
`coach/fuentes/captura_kwin.py`, `herramientas/overlay.py`, `herramientas/capturar_ui.py` y
los tests de UI; el candado es lo que impide que la lista crezca sin que nadie lo note.

**Límite honesto:** un runner de Windows en la nube no tiene GPU ni sesión interactiva, así
que **no puede** probar DXGI ni una ventana topmost [?]. Este job no dice "Windows funciona";
dice "el 80 % que no depende de Windows no se rompió al portarlo". Si hay que poner skips
para que pase, es maquillaje y la fase está mal.

---

## 6. Lo que no se puede prometer sin una máquina Windows

Ninguna de estas frases va a aparecer en el README hasta que exista una medición:

1. **"No baja los FPS."** Nadie lo midió. Ni siquiera sabemos cuánto cuesta `AcquireNextFrame`
   con el juego a 144 Hz en esta máquina.
2. **"Funciona a 2 Hz con 1 % de CPU."** Los 3–14 ms de §1.3 son aritmética, no medición.
3. **"Funciona en cualquier GPU."** Las híbridas (iGPU + dGPU) fallan con `E_INVALIDARG` si el
   dispositivo D3D no es el de la salida [F]; cuántas combinaciones nos tocan es [?].
4. **"Se ve en pantalla completa."** Depende de FSE vs FSO y del modo que elija Deadlock [?].
5. **"No lo detecta VAC."** No hay política publicada ni podemos auditarlo. El diseño evita
   exactamente las tres cosas que 4.B nombra (tamper, interferir con el anticheat, controlar
   la UI), y eso es todo lo que se puede decir.
6. **"El instalador funciona en todas las PCs."** Falta probarlo con antivirus, SmartScreen,
   políticas de PowerShell y sin permisos de admin. Cero mediciones.
7. **"El HUD se lee igual que en Linux."** El 12/12 y el 90–100 % de
   [MEDICIONES.md](MEDICIONES.md) son de KDE con sus capturas. En Windows cambian resolución,
   escalado y fuente de captura.
8. **"Está listo."** No hay código de producción de Windows. Este documento es el plano.

Y lo que sí se puede afirmar hoy, porque está escrito en una fuente: DXGI existe desde
Windows 8 y entrega BGRA8 siempre; WGC desde Windows 10 1803 y dibuja borde; `WS_EX_LAYERED`
+ `WS_EX_TRANSPARENT` da clic a través; `WS_EX_NOACTIVATE` no roba foco; Windows 10 terminó su
soporte el **14 de octubre de 2025**
([ciclo de vida](https://learn.microsoft.com/en-us/lifecycle/products/windows-10-home-and-pro)),
así que **Windows 11 es la base soportada** y Windows 10 queda como "funciona si funciona",
sin promesa.

---

## 7. Primer día en una máquina Windows: orden de trabajo

1. Anotar build de Windows (`winver`), GPU, adaptadores, resolución y escala de cada monitor.
2. Correr el capturador 10 min en el menú y 10 min en partida; guardar el JSONL de la fase (a).
3. Anotar si el modo de video era ventana sin bordes o pantalla completa, y si el juego
   alternó; contar `ACCESS_LOST`.
4. Capturar 300 cuadros por resolución con el HUD visible; anotar reloj y oro a mano.
5. Recalibrar cajas; correr la fase (b) y guardar la matriz de confusión.
6. Abrir la tarjeta; correr las 6 pruebas de la fase (c). Probar también con HDR activado y
   con dos monitores de distinta escala.
7. Recién entonces escribir el README de Windows, citando **estos** números.

Sin los pasos 2, 4 y 6 no hay documento de Windows: hay este.

---

## 8. Fuentes

Consultadas el 2026-11-18.

**Microsoft Learn**

- Desktop Duplication API — https://learn.microsoft.com/en-us/windows/win32/direct3ddxgi/desktop-dup-api
- `IDXGIOutputDuplication::AcquireNextFrame` — https://learn.microsoft.com/en-us/windows/win32/api/dxgi1_2/nf-dxgi1_2-idxgioutputduplication-acquirenextframe
- `IDXGIOutput1::DuplicateOutput` — https://learn.microsoft.com/en-us/windows/win32/api/dxgi1_2/nf-dxgi1_2-idxgioutput1-duplicateoutput
- Captura de pantalla (WGC) — https://learn.microsoft.com/en-us/windows/apps/develop/media-authoring-processing/screen-capture
- `GraphicsCaptureSession` — https://learn.microsoft.com/en-us/uwp/api/windows.graphics.capture.graphicscapturesession
- `GraphicsCaptureSession.IsBorderRequired` — https://learn.microsoft.com/en-us/uwp/api/windows.graphics.capture.graphicscapturesession.isborderrequired
- Extended Window Styles — https://learn.microsoft.com/en-us/windows/win32/winmsg/extended-window-styles
- Window Features (ventanas por capas, hit testing) — https://learn.microsoft.com/en-us/windows/win32/winmsg/window-features
- `SetWindowLongPtrW` — https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowlongptrw
- `SetWindowPos` — https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowpos
- `SetLayeredWindowAttributes` — https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setlayeredwindowattributes
- `SetWindowDisplayAffinity` — https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowdisplayaffinity
- High DPI Desktop Application Development — https://learn.microsoft.com/en-us/windows/win32/hidpi/high-dpi-desktop-application-development-on-windows
- Run and RunOnce Registry Keys — https://learn.microsoft.com/en-us/windows/win32/setupapi/run-and-runonce-registry-keys
- Ciclo de vida de Windows 10 — https://learn.microsoft.com/en-us/lifecycle/products/windows-10-home-and-pro
- DirectX Developer Blog, *Demystifying Fullscreen Optimizations* — https://devblogs.microsoft.com/directx/demystifying-full-screen-optimizations/

**Proyectos y herramientas**

- dxcam — https://github.com/ra1nty/DXcam
- python-mss (backend GDI) — https://github.com/BoboTiG/python-mss/blob/main/src/mss/windows/gdi.py
- PyWinRT, `Windows.Graphics.Capture` — https://pypi.org/project/winrt-Windows.Graphics.Capture/
- PyInstaller, uso — https://pyinstaller.org/en/stable/usage.html
- Tesseract, instalación — https://tesseract-ocr.github.io/tessdoc/Installation.html
- Tesseract para Windows (UB Mannheim) — https://github.com/UB-Mannheim/tesseract/wiki
- wlr-layer-shell (Wayland) — https://wayland.app/protocols/wlr-layer-shell-unstable-v1

**Valve**

- Steam Subscriber Agreement (rev. 10 sep 2026) — https://store.steampowered.com/subscriber_agreement/
- Deadlock en Steam (appdetails) — https://store.steampowered.com/api/appdetails?appids=1422450&l=english
