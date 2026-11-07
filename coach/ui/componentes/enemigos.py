"""EnemyGrid: los 5 enemigos con almas y KDA. La amenaza se lee de un vistazo."""
from gi.repository import Gtk

from ..iconos import pixbuf
from .base import etiqueta, fila, fmt_num, vaciar


def _clave(heroe):
    return str(heroe or "").lower().replace(" ", "_").replace("-", "_")


class EnemyGrid(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._filas = {}
        self.lbl_vacio = etiqueta("sin enemigos todavía", "vacio")
        self.append(self.lbl_vacio)
        self._firma = None

    def actualizar(self, d):
        enemigos = (d or {}).get("enemigos") or []
        firma = tuple((e.get("heroe"), e.get("almas"), e.get("bajas"),
                       e.get("muertes"), e.get("asistencias")) for e in enemigos)
        if firma == self._firma:
            return
        self._firma = firma
        vaciar(self)
        if not enemigos:
            self.append(self.lbl_vacio)
            return
        maximo = max((e.get("almas") or 0) for e in enemigos) or 1
        for e in enemigos:
            self.append(self._fila_enemigo(e, maximo))

    def _fila_enemigo(self, e, maximo):
        nombre = str(e.get("heroe") or "?").capitalize()
        caja = fila(8)
        caja.add_css_class("fila-enemigo")

        pb = pixbuf(_clave(e.get("heroe")), "heroes", 26)
        icono = Gtk.Image.new_from_pixbuf(pb) if pb else Gtk.Image.new_from_icon_name("avatar-default")
        if not pb:
            icono.set_pixel_size(18)
        icono.set_valign(Gtk.Align.CENTER)
        caja.append(icono)

        nom = etiqueta(nombre, "t13 fuerte")
        nom.set_size_request(74, -1)
        nom.set_ellipsize(3)          # Pango.EllipsizeMode.END
        caja.append(nom)

        almas = etiqueta(fmt_num(e.get("almas")), "almas num")
        almas.set_size_request(56, -1)
        almas.set_xalign(1)
        caja.append(almas)

        kda = e.get("bajas")
        txt = (f"{kda}/{e.get('muertes', 0)}/{e.get('asistencias', 0)}"
               if kda is not None else "")
        caja.append(etiqueta(txt, "kda"))

        # barra relativa al que más almas tiene: mide la amenaza, no el valor absoluto
        barra = Gtk.LevelBar()
        barra.set_min_value(0)
        barra.set_max_value(maximo)
        barra.set_value(min(maximo, e.get("almas") or 0))
        barra.set_size_request(48, 6)
        barra.set_valign(Gtk.Align.CENTER)
        barra.set_hexpand(True)
        caja.append(barra)
        return caja
