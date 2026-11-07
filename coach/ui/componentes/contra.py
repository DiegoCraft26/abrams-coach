"""Contra la composición: ítems que la amenaza enemiga justifica, con su fuente.

Van **fuera del ranking** a propósito: sus datos de residual son negativos (los compra
quien ya va perdiendo), y este proyecto no recomienda por corazonada. El jugador ve el
consejo, el motivo y la fuente, y decide.
"""
from gi.repository import Gtk

from ..iconos import pixbuf
from .base import envolver, etiqueta, vaciar


class ContraComposicion(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.lbl_vacio = etiqueta("sin amenaza clara en la composición", "vacio")
        self.append(self.lbl_vacio)
        self._firma = None

    def actualizar(self, d):
        items = (d or {}).get("contra_composicion") or []
        firma = tuple(x.get("id") for x in items)
        if firma == self._firma:
            return
        self._firma = firma
        vaciar(self)
        if not items:
            self.append(self.lbl_vacio)
            return
        for x in items:
            caja = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            pb = pixbuf(x.get("id"), "items", 20)
            icono = Gtk.Image.new_from_pixbuf(pb) if pb else Gtk.Image.new_from_icon_name("image-missing")
            if not pb:
                icono.set_pixel_size(12)
            icono.set_valign(Gtk.Align.START)
            caja.append(icono)
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            col.set_hexpand(True)
            titulo = etiqueta(f"{x.get('nombre')} · {x.get('costo', 0):,}", "t12 fuerte")
            titulo.set_ellipsize(3)
            col.append(titulo)
            detalle = etiqueta(f"{x.get('para')} · {x.get('enemigos_que_lo_justifican')} "
                               f"enemigo(s)", "t11 tenue")
            envolver(detalle, 30)
            col.append(detalle)
            fuente = etiqueta(f"fuente: {x.get('fuente')}", "t11 tenue")
            fuente.set_ellipsize(3)
            col.append(fuente)
            caja.append(col)
            self.append(caja)
