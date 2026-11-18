#!/usr/bin/env python3
"""Overlay mínimo del Abrams Coach: dos cosas y nada más.

Qué dibuja, de arriba abajo:

    [icono]  Weighted Shots            6,400
             vende Close Quarters
    [tile][tile][tile][tile][tile][tile]      <- el camino, el de ahora resaltado

Lo único que aparece es lo que se sabe con certeza en este instante: el ítem, su precio
de lista y el camino. No hay «te alcanza» ni «faltan N»: eso depende de las almas del
momento, que llegan del broadcast con 20–25 s de retraso (o de una lectura OCR que
falla). Enseñarlas era prometer una precisión que no tenemos; si el dato está viejo, se
dice cuánto, y si no hay dato, no se pinta número (Diego, 2026-11-18).

Por qué así: el jugador lo mira dos segundos entre peleas. El juego ya enseña el reloj,
el oro y el inventario; repetirlos aquí gasta la mirada. Lo único que el juego no dice es
**qué comprar ahora** y **qué viene después**, y eso es todo lo que hay en pantalla.

Cómo se dibuja sobre el juego sin tocarlo: es una superficie `wlr-layer-shell` en la capa
OVERLAY. No es inyección, no lee memoria, no engancha el proceso del juego: es una ventana
del compositor, como un panel del escritorio. KWin la pone encima de las ventanas
—incluida una partida en ventana completa sin bordes— y el juego no la ve.

Un detalle que cuesta encontrar: para que PyGObject pueda crear la superficie hay que
cargar `libgtk4-layer-shell` **antes** que `libwayland-client`; si no, GTK avisa
«GTK4 Layer Shell may have been linked after libwayland» y la ventana sale como ventana
normal. Por eso el proceso se relanza solo con `LD_PRELOAD` (abajo, antes de importar GTK).

Uso:
    herramientas/overlay.py                      # contra http://127.0.0.1:8090
    herramientas/overlay.py --url ... --esquina abajo-derecha
    herramientas/overlay.py --oculto             # empieza escondido
    pkill -USR1 -f overlay.py                    # mostrar / esconder (para un atajo)

Si el compositor no soporta layer-shell, la ventana se abre igual como ventana sin
bordes: se degrada, no se rompe.
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time

# --- LD_PRELOAD antes de que exista GTK ------------------------------------------------
_LIB = "/usr/lib/libgtk4-layer-shell.so"
# El relanzamiento solo cuando se ejecuta como programa. Si se importa (pruebas, otro
# módulo), relanzar el proceso desde un import es un efecto colateral inaceptable.
if (__name__ == "__main__" and os.path.exists(_LIB)
        and "gtk4-layer-shell" not in os.environ.get("LD_PRELOAD", "")):
    _env = dict(os.environ)
    _prev = _env.get("LD_PRELOAD", "")
    _env["LD_PRELOAD"] = _LIB + (" " + _prev if _prev else "")
    os.execve(sys.executable, [sys.executable] + sys.argv, _env)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, GLib, Gtk, Gtk4LayerShell as L  # noqa: E402

try:                                                  # clic a través: opcional
    import cairo
except Exception:                                     # noqa: BLE001
    cairo = None

ANCHO, ALTO = 440, 132
MARGEN = 28
INTERVALO = 1.0

CSS = """
window.overlay, .tarjeta { background: transparent; }
.tarjeta {
  background: rgba(10, 12, 16, 0.94);
  border: 1px solid #232936;
  border-radius: 14px;
  padding: 14px 16px;
}
.nombre  { font-size: 19px; font-weight: 800; color: #E8ECF3; }
.precio  { font-size: 17px; font-weight: 800; color: #E9C46A; }
.falta   { font-size: 12px; color: #8B95A5; }
.vende   { font-size: 12px; color: #EF6B6B; }
.chip    { font-size: 11px; color: #8B95A5; }
.chip.vivo { color: #5FD08A; }
.chip.viejo { color: #F2B544; }
.chip.nada { color: #8B95A5; }
.vacio   { font-size: 14px; color: #8B95A5; }
.tile    { border-radius: 7px; border: 2px solid #232936; background: #0b0d11; }
.tile.hecho { border-color: #2f6b4c; }
.tile.ahora { border-color: #E9C46A; }
.tile.despues { border-color: #232936; }
"""


"""Sin GTK aquí a propósito; ver overlay_datos.py."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from overlay_datos import _get, _miles, _num, estado, resumen  # noqa: E402,F401

# --- ventana ---------------------------------------------------------------------------
class Overlay(Gtk.Application):
    def __init__(self, args):
        super().__init__(application_id="org.diegocraft.abramscoach.overlay")
        self.args = args
        self._texturas: dict[str, object] = {}
        self._ultimo = None
        self._oculto = bool(args.oculto)

    # -- construcción
    def do_activate(self):
        self.w = Gtk.ApplicationWindow(application=self)
        self.w.add_css_class("overlay")
        self.w.set_decorated(False)

        proveedor = Gtk.CssProvider()
        proveedor.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), proveedor, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        capa_ok = self._poner_capa()

        caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        caja.add_css_class("tarjeta")
        caja.set_size_request(ANCHO - 2 * MARGEN + MARGEN, ALTO - 2 * MARGEN + MARGEN)

        fila = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.icono = Gtk.Picture()
        self.icono.set_size_request(60, 60)
        self.icono.set_content_fit(Gtk.ContentFit.CONTAIN)
        fila.append(self.icono)

        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        col.set_hexpand(True)
        self.l_nombre = Gtk.Label(label="esperando partida", xalign=0)
        self.l_nombre.add_css_class("vacio")
        self.l_nombre.set_ellipsize(3)          # PANGO_ELLIPSIZE_END
        col.append(self.l_nombre)

        linea = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.l_precio = Gtk.Label(label="", xalign=0)
        self.l_precio.add_css_class("precio")
        self.l_falta = Gtk.Label(label="", xalign=0)
        self.l_falta.add_css_class("falta")
        linea.append(self.l_precio)
        linea.append(self.l_falta)
        col.append(linea)

        self.l_vende = Gtk.Label(label="", xalign=0)
        self.l_vende.add_css_class("vende")
        self.l_vende.set_visible(False)
        col.append(self.l_vende)
        fila.append(col)
        caja.append(fila)

        self.fila_tiles = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        caja.append(self.fila_tiles)

        self.w.set_child(caja)
        self.w.present()

        if not capa_ok:
            self.w.set_default_size(ANCHO, ALTO)   # degradado: ventana flotante normal
        if self._oculto:
            self.w.set_visible(False)

        if cairo is not None:                      # no robar clics al juego
            try:
                self.w.get_surface().set_input_region(cairo.Region())
            except Exception:                  # noqa: BLE001
                pass

        signal.signal(signal.SIGUSR1, lambda *_: GLib.idle_add(self._alternar))
        signal.signal(signal.SIGUSR2, lambda *_: GLib.idle_add(self._refrescar_ya))

        hilo = threading.Thread(target=self._bucle, daemon=True)
        hilo.start()
        return False

    def _poner_capa(self) -> bool:
        try:
            L.init_for_window(self.w)
            if not L.is_layer_window(self.w):
                return False
            L.set_layer(self.w, L.Layer.OVERLAY)
            L.set_namespace(self.w, "abrams-coach")
            # Sin monitor explícito, KWin puede colocar la superficie en el output que
            # le apetezca (se vio arriba a la derecha de uno y "centrada" en otro). Se
            # elige el más grande, que es donde va la partida, o el que pida --monitor.
            monitores = Gdk.Display.get_default().get_monitors()
            n = monitores.get_n_items()
            if n:
                indice = self.args.monitor
                if not 0 <= indice < n:
                    areas = []
                    for i in range(n):
                        g = monitores.get_item(i).get_geometry()
                        areas.append(g.width * g.height)
                    indice = areas.index(max(areas))
                L.set_monitor(self.w, monitores.get_item(indice))
            L.set_keyboard_mode(self.w, L.KeyboardMode.NONE)
            L.set_exclusive_zone(self.w, -1)
            vertical, izq = self.args.esquina
            # Centrado vertical = no anclar arriba ni abajo. En el HUD de Deadlock las
            # esquinas de arriba son los retratos (y la de abajo el minimapa o el
            # inventario), así que el borde medio es el único hueco limpio.
            L.set_anchor(self.w, L.Edge.TOP, vertical == "arriba")
            L.set_anchor(self.w, L.Edge.BOTTOM, vertical == "abajo")
            L.set_anchor(self.w, L.Edge.LEFT, izq)
            L.set_anchor(self.w, L.Edge.RIGHT, not izq)
            if vertical == "arriba":
                L.set_margin(self.w, L.Edge.TOP, MARGEN)
            elif vertical == "abajo":
                L.set_margin(self.w, L.Edge.BOTTOM, MARGEN)
            L.set_margin(self.w, L.Edge.LEFT if izq else L.Edge.RIGHT, MARGEN)
            return True
        except Exception:                      # noqa: BLE001
            return False

    # -- hilo de datos
    def _bucle(self):
        while True:
            d = estado(self.args.url)
            if d is not None:
                GLib.idle_add(self._pintar, resumen(d))
            else:
                GLib.idle_add(self._sin_datos)
            time.sleep(INTERVALO)

    # -- pintado
    def _alternar(self):
        self._oculto = not self._oculto
        self.w.set_visible(not self._oculto)
        return False

    def _refrescar_ya(self):
        d = estado(self.args.url)
        if d is not None:
            self._pintar(resumen(d))
        return False

    def _sin_datos(self):
        if self._ultimo is None:
            self.l_nombre.set_text("sin coach")
            self.l_nombre.remove_css_class("nombre")
            self.l_nombre.add_css_class("vacio")
        else:
            self.l_falta.set_text("datos congelados")
        return False

    def _textura(self, item_id: str):
        if item_id in self._texturas:
            return self._texturas[item_id]
        if not item_id:
            return None
        b = _get(f"{self.args.url.rstrip('/')}/icono/{item_id}")
        tex = None
        if b:
            try:
                tex = Gdk.Texture.new_from_bytes(GLib.Bytes.new(b))
            except Exception:                  # noqa: BLE001
                tex = None
        self._texturas[item_id] = tex
        return tex

    def _pintar(self, r: dict):
        self._ultimo = r
        cambió = (self.l_nombre.get_text() != r["nombre"]) if r["nombre"] else True

        if not r["nombre"]:
            # Sin partida, antes de la primera ranked: el objetivo de la sesión. Es lo
            # único útil que puede decir la tarjeta cuando no hay nada que comprar.
            self.l_nombre.set_text(r.get("objetivo") or "esperando partida")
            self.l_nombre.remove_css_class("nombre")
            self.l_nombre.add_css_class("vacio")
            self.l_precio.set_text("")
            self.l_falta.set_text("")
            self.l_vende.set_visible(False)
            self.icono.set_paintable(None)
            self._pintar_tiles([])
            return

        self.l_nombre.remove_css_class("vacio")
        self.l_nombre.add_css_class("nombre")
        self.l_nombre.set_text(r["nombre"])
        self.l_precio.set_text(_miles(r["costo"]) if r["costo"] else "")

        # Solo certeza: precio de lista. La edad del dato se dice cuando importa.
        if r["rancio"]:
            self.l_falta.set_text(f"datos de hace {r['edad']} s")
        else:
            self.l_falta.set_text("")

        if r["vende"]:
            self.l_vende.set_text(f"vende {r['vende']}")
            self.l_vende.set_visible(True)
        else:
            self.l_vende.set_visible(False)

        if cambió or self.icono.get_paintable() is None:
            tex = self._textura(r["id"])
            if tex is not None:
                self.icono.set_paintable(tex)
        self._pintar_tiles(r["tiles"])
        return False

    def _pintar_tiles(self, tiles):
        hijo = self.fila_tiles.get_first_child()
        while hijo is not None:
            sig = hijo.get_next_sibling()
            self.fila_tiles.remove(hijo)
            hijo = sig
        for t in tiles:
            pic = Gtk.Picture()
            pic.set_size_request(28, 28)
            pic.set_content_fit(Gtk.ContentFit.CONTAIN)
            pic.add_css_class("tile")
            pic.add_css_class(t["clase"])
            tex = self._textura(t["id"])
            if tex is not None:
                pic.set_paintable(tex)
            self.fila_tiles.append(pic)


def _esquina(v: str) -> tuple[str, bool]:
    """(vertical, izquierda). «centro» no ancla arriba ni abajo.

    El defecto es centro-derecha: en el HUD de Deadlock el borde derecho, a media
    altura, es el único hueco que no pisa retratos, minimapa, inventario ni habilidades.
    """
    return {
        "arriba-izquierda": ("arriba", True),
        "arriba-derecha": ("arriba", False),
        "centro-izquierda": ("centro", True),
        "centro-derecha": ("centro", False),
        "abajo-izquierda": ("abajo", True),
        "abajo-derecha": ("abajo", False),
    }.get(v, ("centro", False))


def main() -> int:
    ap = argparse.ArgumentParser(description="Overlay mínimo: siguiente compra y camino.")
    ap.add_argument("--url", default="http://127.0.0.1:8090")
    ap.add_argument("--esquina", default="centro-derecha",
                    choices=["arriba-izquierda", "arriba-derecha",
                             "centro-izquierda", "centro-derecha",
                             "abajo-izquierda", "abajo-derecha"])
    ap.add_argument("--oculto", action="store_true", help="empieza escondido (SIGUSR1 alterna)")
    ap.add_argument("--monitor", type=int, default=-1,
                    help="índice del monitor; -1 = el más grande (donde suele estar el juego)")
    a = ap.parse_args()
    a.esquina = _esquina(a.esquina)
    return Overlay(a).run([])


if __name__ == "__main__":
    sys.exit(main())
