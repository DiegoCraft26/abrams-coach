#!/usr/bin/env python3
"""Capturas de la UI a tamaños exactos, sin depender del compositor.

Toma el panel real (`coach.ui.Panel`), lo deja pintar y renderiza el árbol de widgets a
PNG con `Gsk.Renderer`. Así la captura es exactamente el tamaño pedido aunque el monitor
sea otro, y sirve como puerta de calidad reproducible.

Uso:
    python3 herramientas/capturar_ui.py --url http://127.0.0.1:8090 \
        --salida capturas --tamanos 960x1080,1280x720,1920x1080,800x600
"""
import argparse
import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach.ui import app as ui_app  # noqa: E402


def _render(win, ancho, alto, ruta):
    """Renderiza el contenido de la ventana al tamaño pedido."""
    paintable = Gtk.WidgetPaintable.new(win)
    snapshot = Gtk.Snapshot.new()
    paintable.snapshot(snapshot, float(ancho), float(alto))
    nodo = snapshot.to_node()
    if nodo is None:
        return False
    renderer = win.get_renderer() or Gdk.Display.get_default().get_renderer()
    textura = renderer.render_texture(nodo, None)
    textura.save_to_png(ruta)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8090")
    ap.add_argument("--salida", default=os.path.join(RAIZ, "capturas"))
    ap.add_argument("--tamanos", default="960x1080,1280x720,1920x1080,800x600")
    ap.add_argument("--breakpoint", default="auto")
    ap.add_argument("--preguntar", default=None,
                    help="abre el copiloto y le hace esta pregunta antes de capturar")
    a = ap.parse_args()

    # Aviso honesto: sin servidor el panel pinta su estado vacío y la captura no vale
    # como prueba de contenido (sí como prueba de que la ventana se construye).
    import json as _json
    import urllib.request as _url
    try:
        with _url.urlopen(a.url.rstrip("/") + "/api/estado", timeout=3) as r:
            _json.load(r)
        print(f"servidor con datos: {a.url}")
    except Exception:                                    # noqa: BLE001
        print(f"AVISO: no hay servidor con datos en {a.url}: "
              f"las capturas saldrán con el panel vacío")

    os.makedirs(a.salida, exist_ok=True)
    tamanos = []
    for trozo in a.tamanos.split(","):
        ancho, alto = trozo.lower().split("x")
        tamanos.append((int(ancho), int(alto)))

    resultados = []

    def siguiente(app, i=0):
        if i >= len(tamanos):
            app.release()
            app.quit()
            return False
        ancho, alto = tamanos[i]
        win = ui_app.Panel(app, a.url, a.breakpoint, 0.4, (ancho, alto))
        win.present()
        if a.preguntar:
            win.copiloto.set_reveal_child(True)
            win.copiloto.preguntar(a.preguntar)

        def capturar():
            # dos vueltas al bucle: la primera asigna tamaño, la segunda pinta datos
            def hacer():
                ruta = os.path.join(a.salida, f"ui-{ancho}x{alto}.png")
                ok = False
                try:
                    ok = _render(win, ancho, alto, ruta)
                except Exception as exc:                   # noqa: BLE001
                    print(f"  error renderizando {ancho}x{alto}: {exc}")
                resultados.append((ancho, alto, ok, ruta))
                print(f"  {ancho}x{alto} -> {'ok' if ok else 'FALLO'} {ruta}")
                win.destroy()
                GLib.idle_add(siguiente, app, i + 1)
                return False
            GLib.timeout_add(9000 if a.preguntar else 900, hacer)
            return False

        GLib.timeout_add(400, capturar)
        return False

    class App(Gtk.Application):
        def do_startup(self):
            Gtk.Application.do_startup(self)
            prov = Gtk.CssProvider()
            prov.load_from_data(ui_app._leer_css())
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        def do_activate(self):
            self.hold()          # sin esto la app se cierra al destruir la primera ventana
            siguiente(self)

    App(application_id="gg.diego.abramscoach.capturas").run(None)
    fallos = [r for r in resultados if not r[2]]
    print(f"capturas: {len(resultados) - len(fallos)}/{len(tamanos)}")
    return 1 if fallos or len(resultados) != len(tamanos) else 0


if __name__ == "__main__":
    sys.exit(main())
