"""Puerta de calidad de la UI nativa.

No comprueba píxeles: comprueba que la ventana **se construye y se pinta** en los cuatro
tamaños del pedido. Eso ya habría atrapado el fallo del 2026-11-07, cuando el drawer del
copiloto se construía con una variable fuera de ámbito y el panel entero dejaba de abrir.

Si no hay servidor gráfico, la suite se salta la parte de pintado y lo dice (no se inventa
un verde).
"""
import json
import os
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

TAMANOS = ("960x1080", "1280x720", "1920x1080", "800x600")


def main():
    fallos = 0

    print("preferencias de ventana")
    from coach.ui import preferencias

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        ruta = f.name
    try:
        ok = preferencias.guardar(1280, 720, False, None, "auto", ruta)
        datos = preferencias.cargar(ruta)
        if not (ok and datos["ancho"] == 1280 and datos["alto"] == 720):
            print(f"  FALLA guardar/cargar: {datos}")
            fallos += 1
        else:
            print("  ok   guarda y recupera tamaño")
        with open(ruta, "w") as f:
            f.write("{roto")
        datos = preferencias.cargar(ruta)
        if datos["ancho"] != 960 or datos["alto"] != 1080:
            print(f"  FALLA un archivo roto debe caer a los valores por defecto: {datos}")
            fallos += 1
        else:
            print("  ok   archivo roto -> valores por defecto")
        ok = preferencias.guardar(10, 10, False, None, "auto", ruta)
        datos = preferencias.cargar(ruta)
        if not ok or datos["ancho"] < 640 or datos["alto"] < 480:
            print(f"  FALLA tamaños fuera de rango no se acotan: {datos}")
            fallos += 1
        else:
            print("  ok   acota tamaños imposibles")
    finally:
        os.unlink(ruta)

    print("breakpoints")
    # En un runner sin GTK (CI de GitHub) estas dos partes se saltan y se dice. El gate
    # completo solo corre en la máquina de desarrollo, que es donde se usa el panel.
    try:
        import gi  # noqa: F401
        from coach.ui.app import ANCHO_AMPLIO, ANCHO_ANGOSTO, Panel
        casos = [(640, "angosto"), (800, "medio"), (1099, "medio"),
                 (1100, "amplio"), (1920, "amplio")]
        for ancho, esperado in casos:
            obtenido = Panel._modo_por_ancho(None, ancho)
            if obtenido != esperado:
                print(f"  FALLA {ancho}px -> {obtenido}, esperaba {esperado}")
                fallos += 1
        else:
            print(f"  ok   {len(casos)} anchos clasifican bien "
                  f"({ANCHO_ANGOSTO}/{ANCHO_AMPLIO})")
    except ImportError:
        print("  (saltado: PyGObject no está instalado en este entorno)")
        print("\nui: OK parcial (sin GTK)")
        return 0
    except Exception as exc:                                # noqa: BLE001
        print(f"  FALLA no se pudo importar el panel: {exc}")
        fallos += 1

    print("pintado real")
    if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
        print("  (saltado: sin servidor gráfico)")
    else:
        # Si hay coach corriendo se exige una captura con contenido (más pesada); si no,
        # basta con que la ventana se pinte y se avisa de que está vacía.
        try:
            import urllib.request
            with urllib.request.urlopen("http://127.0.0.1:8090/api/estado", timeout=2):
                con_datos = True
        except Exception:                                # noqa: BLE001
            con_datos = False
        minimo_kb = 60 if con_datos else 20
        print(f"  (servidor con datos: {'sí' if con_datos else 'no'}; "
              f"mínimo {minimo_kb} KB por captura)")

        with tempfile.TemporaryDirectory() as tmp:
            cmd = [sys.executable, os.path.join(RAIZ, "herramientas", "capturar_ui.py"),
                   "--salida", tmp, "--tamanos", ",".join(TAMANOS)]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            except subprocess.TimeoutExpired:
                print("  FALLA la captura no terminó en 180 s")
                fallos += 1
                r = None
            if r is not None:
                if r.returncode != 0:
                    print(f"  FALLA capturar_ui salió {r.returncode}: "
                          f"{(r.stderr or '')[-300:]}")
                    fallos += 1
                else:
                    for tam in TAMANOS:
                        ruta_png = os.path.join(tmp, f"ui-{tam}.png")
                        peso = os.path.getsize(ruta_png) if os.path.exists(ruta_png) else 0
                        if peso < minimo_kb * 1024:
                            print(f"  FALLA {tam}: PNG ausente o vacío ({peso} B)")
                            fallos += 1
                        else:
                            print(f"  ok   {tam}: {peso // 1024} KB")

    print()
    if fallos:
        print(f"ui: {fallos} fallos")
        return 1
    print("ui: OK")
    return 0


def test_suite():
    """Entrada para `pytest -q`."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
