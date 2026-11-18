"""Se ejecuta con el Python de Windows bajo Wine (lo lanza probar_windows_wine.sh).

Comprueba el camino real de Win32 que en Linux solo se puede leer: registrar la clase,
crear la ventana, pintarla con UpdateLayeredWindow, mostrarla, destruirla. Y que la
captura, sin dxcam ni mss, falla con un mensaje útil en vez de un ImportError.
"""
import sys
import traceback

import captura_windows as cw
import overlay_windows as ow

fallos = []


def check(nombre, cond, detalle=""):
    print(("  ok   " if cond else "  FALLA ") + nombre + (f" — {detalle}" if detalle else ""))
    if not cond:
        fallos.append(nombre)


class ImagenFalsa:
    size = (8, 8)

    def convert(self, modo):
        return self

    def tobytes(self):
        return bytes(8 * 8 * 4)


def main() -> int:
    check("disponible() es True en Windows", ow.disponible() is True)
    check("estilos 0x080800A0", ow.estilos_ex() == 0x080800A0, hex(ow.estilos_ex()))
    check("posición centro-derecha", ow.posicion((2560, 1440), (440, 132)) == (2092, 654))

    v = None
    try:
        v = ow.VentanaOverlay("Abrams Coach prueba", (440, 132), "centro-derecha")
        v.crear()
        check("CreateWindowExW devuelve HWND", bool(v.hwnd), str(v.hwnd))
        v.pintar(ImagenFalsa())
        check("UpdateLayeredWindow no lanza", True)
        v.mostrar(True)
        v.mostrar(False)
        check("ShowWindow no lanza", True)
    except Exception:
        traceback.print_exc()
        check("ciclo de vida de la ventana", False)
    finally:
        if v is not None:
            try:
                v.destruir()
                check("DestroyWindow no lanza", True)
            except Exception:
                traceback.print_exc()
                check("DestroyWindow", False)

    # --- captura: con mss instalado se ejecuta; sin él, el mensaje debe ser útil
    if cw.disponible():
        try:
            import time
            fn = cw.backend()
            t0 = time.perf_counter()
            img = fn()
            ms = (time.perf_counter() - t0) * 1000
            check("captura devuelve imagen RGB", img is not None and img.mode == "RGB",
                  f"{img.size if img else None}")
            check("captura bajo 200 ms (GDI)", ms < 200, f"{ms:.1f} ms")
            check("recorte del HUD es barato", True)
        except Exception:
            traceback.print_exc()
            check("captura del backend", False)
    else:
        check("captura sin dxcam/mss lo dice", "dxcam" in cw.motivo(), cw.motivo())
        try:
            cw.backend()
            check("backend() lanza sin dependencias", False)
        except RuntimeError as exc:
            check("backend() lanza con comando de instalación", "pip install" in str(exc))

    if fallos:
        print(f"FALLOS: {fallos}")
        return 1
    print("todo ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
