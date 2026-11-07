"""Equipo: las almas de los 12 jugadores, en dos bloques claros.

Usa `almas_12` (el mismo campo que ya llenan los modos OCR y vivo) y, si el payload trae
`aliados`, sus nombres y KDA. Nunca inventa: si solo hay 12 números, se muestran números.
"""
from gi.repository import Gtk

from ..iconos import pixbuf
from .base import etiqueta, fila, fmt_num, vaciar


class Equipo(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._firma = None
        self.lbl_vacio = etiqueta("sin marcador", "vacio")
        self.append(self.lbl_vacio)

    def actualizar(self, d):
        doce = (d or {}).get("almas_12") or []
        aliados = (d or {}).get("aliados") or []
        firma = (tuple(doce), tuple(a.get("heroe") for a in aliados))
        if firma == self._firma:
            return
        self._firma = firma
        vaciar(self)
        if not any(x is not None for x in doce):
            self.append(self.lbl_vacio)
            return
        mios = [x for x in doce[1:6] if x is not None]
        suyos = [x for x in doce[6:12] if x is not None]
        self.append(self._bloque("ALIADOS", mios, "acento"))
        self.append(self._bloque("ENEMIGOS", suyos, "error"))

    def _bloque(self, rotulo, valores, clase):
        caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        caja.append(etiqueta(rotulo, "t11 tenue"))
        linea = fila(6)
        if not valores:
            linea.append(etiqueta("—", "vacio"))
        for v in valores:
            linea.append(etiqueta(fmt_num(v), f"t12 num {clase}"))
        caja.append(linea)
        return caja
