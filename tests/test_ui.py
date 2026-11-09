"""Puerta de calidad de la UI nativa.

No comprueba píxeles: comprueba que la ventana **se construye y se pinta** en los cuatro
tamaños del pedido. Eso ya habría atrapado el fallo del 2026-11-07, cuando el drawer del
el panel entero dejaba de abrir por una variable fuera de ámbito en un componente.

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
        # La captura se mide por contenido, no por peso: un PNG puede pesar poco y
        # estar bien, o pesar mucho y ser un rectángulo vacío. Se exige el tamaño exacto
        # y que la imagen tenga contraste (stddev de los píxeles), que es lo que
        # distingue "se pintó" de "salió en blanco".
        try:
            import urllib.request
            with urllib.request.urlopen("http://127.0.0.1:8090/api/estado", timeout=2):
                con_datos = True
        except Exception:                                # noqa: BLE001
            con_datos = False
        print(f"  (servidor con datos: {'sí' if con_datos else 'no'}; "
              f"se mide tamaño exacto y contraste)")

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
                    from PIL import Image, ImageStat
                    for tam in TAMANOS:
                        ruta_png = os.path.join(tmp, f"ui-{tam}.png")
                        ancho, alto = (int(x) for x in tam.split("x"))
                        if not os.path.exists(ruta_png):
                            print(f"  FALLA {tam}: no se generó el PNG")
                            fallos += 1
                            continue
                        try:
                            im = Image.open(ruta_png).convert("RGB")
                            desvio = sum(ImageStat.Stat(im).stddev) / 3.0
                        except Exception as exc:            # noqa: BLE001
                            print(f"  FALLA {tam}: PNG ilegible ({exc})")
                            fallos += 1
                            continue
                        if im.size != (ancho, alto):
                            print(f"  FALLA {tam}: el PNG mide {im.size}")
                            fallos += 1
                        elif desvio < 3.0:
                            print(f"  FALLA {tam}: se pintó casi vacío (contraste "
                                  f"{desvio:.1f})")
                            fallos += 1
                        else:
                            print(f"  ok   {tam}: {im.size[0]}x{im.size[1]}, "
                                  f"contraste {desvio:.1f}")

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
