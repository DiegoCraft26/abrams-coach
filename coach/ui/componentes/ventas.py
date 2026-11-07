"""Ventas: cuándo conviene vender para meter algo mejor.

En Deadlock todo se vende por su valor completo, así que la pregunta no es "¿puedo?"
sino "¿mejoro?". El motor solo lo propone con tres condiciones medidas; si no se cumple
ninguna, el componente se queda callado en vez de sugerir ventas a la ligera.
"""
from gi.repository import Gtk

from ..iconos import pixbuf
from .base import envolver, etiqueta, fila, fmt_num, vaciar


class Ventas(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.lbl_vacio = etiqueta("nada que vender", "vacio")
        self.append(self.lbl_vacio)
        self._firma = None

    def actualizar(self, d):
        venta = (d or {}).get("venta")
        firma = (venta or {}).get("comprar"), (venta or {}).get("vender")
        if firma == self._firma:
            return
        self._firma = firma
        vaciar(self)
        if not venta:
            self.append(self.lbl_vacio)
            return
        caja = fila(8)
        for tipo, ident, rotulo in (("sale", venta.get("vender"), "vende"),
                                    ("entra", venta.get("comprar"), "entra")):
            sub = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            pb = pixbuf(ident, "items", 26)
            icono = Gtk.Image.new_from_pixbuf(pb) if pb else Gtk.Image.new_from_icon_name("image-missing")
            if not pb:
                icono.set_pixel_size(16)
            sub.append(icono)
            sub.append(etiqueta(rotulo, "t11 tenue"))
            caja.append(sub)
        texto = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        texto.set_hexpand(True)
        motivo = etiqueta(venta.get("motivo") or "", "t12 tenue")
        envolver(motivo, 40)
        texto.append(motivo)
        gp = venta.get("ganancia_pp")
        if gp is not None:
            texto.append(etiqueta(f"+{gp:.1f} pp de residual", "t11 acento"))
        caja.append(texto)
        self.append(caja)
