"""Overlay de Windows: ventana siempre arriba y clic a través. **No probado en Windows.**

Por qué existe. En KDE el overlay es una superficie `wlr-layer-shell` (`herramientas/
overlay.py`). En Windows no hay layer-shell: se hace con una ventana Win32 sin bordes en
la capa `WS_EX_TOPMOST`, con `WS_EX_LAYERED` para la transparencia, `WS_EX_TRANSPARENT`
para que los clics la atraviesen y `WS_EX_NOACTIVATE` para no robarle el foco al juego.

Lo que este módulo deja verificado desde Linux —y por eso está separado en funciones
puras—: la combinación de estilos, el cálculo de la posición por esquina y el hecho de
que importarlo aquí no estalla. Lo que **no** se puede verificar sin una máquina Windows
es que la ventana se componga encima del juego, que respete `WS_EX_TRANSPARENT` en un
juego en ventana completa sin bordes, ni el coste por cuadro. Eso está en
`docs/WINDOWS.md` como pendiente, no como hecho.

Diseño: el contenido se pinta a un DIB de 32 bits y se entrega con `UpdateLayeredWindow`,
que es la única forma de tener transparencia por píxel sin repintar toda la ventana.

Uso (en Windows):
    v = VentanaOverlay("Abrams Coach", (440, 132), esquina="centro-derecha")
    v.crear()
    v.pintar(imagen_pil)      # PIL en RGBA
    v.mover_a_esquina()
"""
from __future__ import annotations

import sys

__all__ = ["VentanaOverlay", "estilos_ex", "posicion", "disponible",
           "WS_EX_LAYERED", "WS_EX_TRANSPARENT", "WS_EX_NOACTIVATE", "WS_EX_TOOLWINDOW",
           "WS_EX_TOPMOST"]

# Valores de la documentación de Win32 (winuser.h). Se declaran aquí para poder
# comprobar la combinación en Linux, donde `ctypes.windll` no existe.
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_POPUP = 0x80000000


def disponible() -> bool:
    return sys.platform.startswith("win")


def estilos_ex() -> int:
    """La combinación exacta de estilos extendidos del overlay.

    - LAYERED: transparencia por píxel con UpdateLayeredWindow.
    - TRANSPARENT: los clics pasan al juego.
    - NOACTIVATE: no roba el foco al pulsar ni al aparecer.
    - TOOLWINDOW: no sale en la barra de tareas ni en Alt+Tab.
    """
    return (WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)


def posicion(pantalla: tuple[int, int], tamano: tuple[int, int],
             esquina: str = "centro-derecha", margen: int = 28) -> tuple[int, int]:
    """Esquina superior izquierda de la tarjeta, en píxeles.

    Misma semántica que el overlay de Linux: el borde medio derecho es el único hueco
    del HUD de Deadlock (arriba están los retratos, abajo el minimapa o el inventario).
    """
    ancho, alto = pantalla
    cw, ch = tamano
    vertical, _, horizontal = esquina.partition("-")
    x = margen if horizontal == "izquierda" else ancho - cw - margen
    if vertical == "arriba":
        y = margen
    elif vertical == "abajo":
        y = alto - ch - margen
    else:
        y = (alto - ch) // 2
    return max(0, x), max(0, y)


class VentanaOverlay:
    """Ventana Win32 del overlay. En Linux lanza al construir, con motivo.

    Lo que aprendió Wine (2026-11-18): `ctypes.wintypes` **no** trae `WNDCLASSW`, y sin
    `restype` explícito un `HWND` de 64 bits se trunca a 32. Las dos cosas hacían que
    `crear()` fallara en un Windows real aunque en Linux pareciera correcto por lectura.
    """

    def __init__(self, titulo: str = "Abrams Coach", tamano=(440, 132),
                 esquina: str = "centro-derecha", margen: int = 28):
        if not disponible():
            raise RuntimeError(f"overlay de Windows pedido en {sys.platform}")
        self.titulo = titulo
        self.tamano = tamano
        self.esquina = esquina
        self.margen = margen
        self.hwnd = None
        self._user32 = None
        self._gdi32 = None
        self._proc = None

    # -- declaraciones de tipos
    def _declarar(self):
        import ctypes
        from ctypes import wintypes

        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [("style", wintypes.UINT),
                        ("lpfnWndProc", WNDPROC),
                        ("cbClsExtra", ctypes.c_int),
                        ("cbWndExtra", ctypes.c_int),
                        ("hInstance", wintypes.HINSTANCE),
                        ("hIcon", wintypes.HICON),
                        ("hCursor", wintypes.HANDLE),
                        ("hbrBackground", wintypes.HBRUSH),
                        ("lpszMenuName", wintypes.LPCWSTR),
                        ("lpszClassName", wintypes.LPCWSTR)]

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._WNDPROC = WNDPROC
        self._WNDCLASSW = WNDCLASSW

        u = self._user32
        u.CreateWindowExW.restype = wintypes.HWND
        u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                      wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                      wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        u.DefWindowProcW.restype = ctypes.c_longlong
        u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                     wintypes.LPARAM]
        u.RegisterClassW.restype = wintypes.ATOM
        u.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        u.SetWindowPos.restype = wintypes.BOOL
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.UINT]
        u.ShowWindow.restype = wintypes.BOOL
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u.DestroyWindow.restype = wintypes.BOOL
        u.DestroyWindow.argtypes = [wintypes.HWND]
        u.GetDC.restype = wintypes.HDC
        u.GetDC.argtypes = [wintypes.HWND]
        u.ReleaseDC.restype = ctypes.c_int
        u.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]

    # -- ciclo de vida
    def crear(self):
        import ctypes

        self._user32 = ctypes.windll.user32
        self._gdi32 = ctypes.windll.gdi32
        self._declarar()
        hinst = ctypes.windll.kernel32.GetModuleHandleW(None)

        def _proc(hwnd, msg, wparam, lparam):        # pragma: no cover - solo Windows
            if msg == 0x0002:                        # WM_DESTROY
                self._user32.PostQuitMessage(0)
            return self._user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._proc = self._WNDPROC(_proc)
        clase = self._WNDCLASSW()
        clase.lpfnWndProc = self._proc
        clase.hInstance = hinst
        clase.lpszClassName = "AbramsCoachOverlay"
        if not self._user32.RegisterClassW(ctypes.byref(clase)):
            # ERROR_CLASS_ALREADY_EXISTS (1410) es normal al abrir por segunda vez.
            if ctypes.GetLastError() not in (0, 1410):
                raise RuntimeError(f"RegisterClassW falló ({ctypes.GetLastError()})")

        ancho, alto = self.tamano
        self.hwnd = self._user32.CreateWindowExW(
            estilos_ex(), "AbramsCoachOverlay", self.titulo, WS_POPUP,
            0, 0, ancho, alto, None, None, hinst, None)
        if not self.hwnd:
            raise RuntimeError(f"CreateWindowExW falló ({ctypes.GetLastError()})")
        self.mover_a_esquina()
        return self

    def mover_a_esquina(self):                        # pragma: no cover - solo Windows
        ancho = self._user32.GetSystemMetrics(0)
        alto = self._user32.GetSystemMetrics(1)
        x, y = posicion((ancho, alto), self.tamano, self.esquina, self.margen)
        # HWND_TOPMOST (-1) + SWP_NOACTIVATE: encima sin quitarle el foco al juego.
        self._user32.SetWindowPos(self.hwnd, -1, x, y, self.tamano[0], self.tamano[1],
                                  0x0010 | 0x0004)

    def pintar(self, imagen):                         # pragma: no cover - solo Windows
        """Pinta una imagen PIL RGBA con transparencia por píxel."""
        import ctypes
        from ctypes import wintypes

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                        ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD),
                        ("biXPelsPerMeter", ctypes.c_long),
                        ("biYPelsPerMeter", ctypes.c_long),
                        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

        class BITMAPINFO(ctypes.Structure):
            _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

        ancho, alto = imagen.size
        hdc_pantalla = self._user32.GetDC(None)
        hdc_mem = self._gdi32.CreateCompatibleDC(hdc_pantalla)
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = ancho
        bmi.bmiHeader.biHeight = -alto          # negativo = de arriba abajo
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0         # BI_RGB
        bits = ctypes.c_void_p()
        self._gdi32.CreateDIBSection.restype = wintypes.HBITMAP
        hbmp = self._gdi32.CreateDIBSection(hdc_pantalla, ctypes.byref(bmi), 0,
                                            ctypes.byref(bits), None, 0)
        if not hbmp:
            raise RuntimeError("CreateDIBSection falló")
        self._gdi32.SelectObject(hdc_mem, hbmp)
        crudo = imagen.convert("RGBA").tobytes()
        ctypes.memmove(bits, crudo, len(crudo))
        punto_dst = wintypes.POINT(0, 0)
        tam_dst = wintypes.SIZE(self.tamano[0], self.tamano[1])
        punto_src = wintypes.POINT(0, 0)
        self._user32.UpdateLayeredWindow(self.hwnd, hdc_pantalla, ctypes.byref(punto_dst),
                                         ctypes.byref(tam_dst), hdc_mem,
                                         ctypes.byref(punto_src), 0, None, 2)
        self._gdi32.DeleteObject(hbmp)
        self._gdi32.DeleteDC(hdc_mem)
        self._user32.ReleaseDC(None, hdc_pantalla)

    def mostrar(self, visible: bool = True):          # pragma: no cover - solo Windows
        self._user32.ShowWindow(self.hwnd, 5 if visible else 0)

    def destruir(self):                               # pragma: no cover - solo Windows
        if self.hwnd:
            self._user32.DestroyWindow(self.hwnd)
            self.hwnd = None
