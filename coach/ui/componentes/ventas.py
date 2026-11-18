"""Ventas: cuándo conviene vender para meter algo mejor.

En Deadlock todo se vende por su valor completo, así que la pregunta no es "¿puedo?"
sino "¿mejoro?". El motor solo lo propone con tres condiciones medidas; si no se cumple
ninguna, el componente se queda callado en vez de sugerir ventas a la ligera.
"""
from gi.repository import Gtk

from ..iconos import pixbuf
from .base import envolver, etiqueta, fila, vaciar


class Ventas(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.lbl_vacio = etiqueta("nada que vender", "vacio")
        self.append(self.lbl_vacio)
        self._firma = None

    def actualizar(self, d):
        venta = (d or {}).get("venta")
        prioridad = [v for v in ((d or {}).get("ventas") or [])
                     if v.get("nivel") == "ahora"]
        firma = ((venta or {}).get("comprar"), (venta or {}).get("vender"),
                 tuple(v.get("id") for v in prioridad))
        if firma == self._firma:
            return
        self._firma = firma
        vaciar(self)
        if not venta:
            # Sin compra pendiente pero con slot lleno: al menos decir qué sale primero.
            # Antes esta tarjeta se quedaba en «nada que vender» con el build completo.
            if prioridad:
                self.append(etiqueta("salida prioritaria", "t11 tenue"))
                for v in prioridad:
                    self.append(etiqueta(f"{v.get('nombre')} ({v.get('slot_nombre')})"
                                         f" · {v.get('pp'):+.1f}pp", "t12"))
            else:
                self.append(self.lbl_vacio)
            return
        caja = fila(8)
        for ident, rotulo in ((venta.get("vender"), "vende"), (venta.get("comprar"), "entra")):
            pb = pixbuf(ident, "items", 22)
            icono = Gtk.Image.new_from_pixbuf(pb) if pb else Gtk.Image.new_from_icon_name("image-missing")
            if not pb:
                icono.set_pixel_size(14)
            icono.set_valign(Gtk.Align.START)
            caja.append(icono)
            caja.append(etiqueta(rotulo, "t11 tenue"))
        texto = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        texto.set_hexpand(True)
        # Nombre y slot explícitos: "vende X (arma)" y no solo un icono.
        quien = venta.get("nombre") or venta.get("vender") or "ese ítem"
        slot = venta.get("slot")
        texto.append(etiqueta(f"Vende {quien}" + (f" · {slot}" if slot else ""),
                              "t12 fuerte"))
        motivo = etiqueta(venta.get("motivo") or "", "t12 tenue")
        envolver(motivo, 40)
        texto.append(motivo)
        gp = venta.get("ganancia_pp")
        if gp is not None:
            # El signo lo pone el formato: con el "+" fijo, una ganancia negativa
            # salía como "+-3.2 pp".
            texto.append(etiqueta(f"{gp:+.1f} pp de residual",
                                  "t11 acento" if gp >= 0 else "t11 aviso"))
        caja.append(texto)
        self.append(caja)
