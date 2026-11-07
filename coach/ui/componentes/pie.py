"""StatusBar: de dónde vienen los datos, cuánto tardó el motor y si la lectura es fiable.

Nada de números decorativos: si la latencia no se midió, se dice "—".
"""
from gi.repository import Gtk

from .base import etiqueta


class StatusBar(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        self.lbl_motor = etiqueta("motor — ms", "pie")
        self.append(self.lbl_motor)

        self.lbl_confianza = etiqueta("confianza —", "pie")
        self.append(self.lbl_confianza)

        self.lbl_fuente = etiqueta("fuente —", "pie")
        self.append(self.lbl_fuente)

        relleno = Gtk.Box()
        relleno.set_hexpand(True)
        self.append(relleno)

        self.lbl_aviso = etiqueta("", "pie aviso")
        self.lbl_aviso.set_xalign(1)
        self.append(self.lbl_aviso)

    def actualizar(self, d):
        d = d or {}
        ms = d.get("ms")
        self.lbl_motor.set_label(f"motor {ms} ms" if ms is not None else "motor — ms")
        conf = d.get("confianza")
        self.lbl_confianza.set_label(
            f"confianza {conf*100:.0f}%" if conf is not None else "confianza —")
        self.lbl_fuente.set_label(f"fuente {d.get('fuente') or '—'}")
        if d.get("lectura_dudosa"):
            self.lbl_aviso.set_label("lectura dudosa: mantengo la última buena")
        elif d.get("estable") is False:
            self.lbl_aviso.set_label("ajustando")
        else:
            self.lbl_aviso.set_label("")
