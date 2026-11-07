"""PurchaseFeed: quién compró qué, de los 12 jugadores (enemigos incluidos)."""
from gi.repository import Gtk

from ..iconos import pixbuf
from .base import etiqueta, fila, vaciar


class PurchaseFeed(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.lbl_vacio = etiqueta("sin compras nuevas", "vacio")
        self.append(self.lbl_vacio)
        self._firma = None

    def actualizar(self, d):
        compras = (d or {}).get("compras") or []
        firma = tuple(c.get("texto") for c in compras)
        if firma == self._firma:
            return
        self._firma = firma
        vaciar(self)
        if not compras:
            self.append(self.lbl_vacio)
            return
        for c in compras[-6:]:
            caja = fila(6)
            pb = pixbuf(c.get("item"), "items", 18)
            icono = Gtk.Image.new_from_pixbuf(pb) if pb else Gtk.Image.new_from_icon_name("image-missing")
            if not pb:
                icono.set_pixel_size(12)
            caja.append(icono)
            lbl = etiqueta(c.get("texto") or "", "t12 tenue")
            lbl.set_ellipsize(3)
            lbl.set_hexpand(True)
            caja.append(lbl)
            self.append(caja)
