"""Tu equipo: los aliados con sus almas y KDA.

Los enemigos ya tienen su propia sección arriba, así que aquí solo van los compañeros.
Antes se armaba partiendo `almas_12` en dos bloques de seis, y con equipos incompletos
mezclaba rivales con aliados; ahora usa las listas de jugadores, que traen nombre.
"""
from gi.repository import Gtk

from ..iconos import pixbuf
from .base import etiqueta, fila, fmt_num, vaciar


def _clave(heroe):
    return str(heroe or "").lower().replace(" ", "_").replace("-", "_")


class Equipo(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._firma = None
        self.lbl_vacio = etiqueta("sin datos del equipo", "vacio")
        self.append(self.lbl_vacio)

    def actualizar(self, d):
        aliados = [a for a in ((d or {}).get("aliados") or []) if a.get("heroe") or a.get("almas")]
        firma = tuple((a.get("heroe"), a.get("almas"), a.get("bajas")) for a in aliados)
        if firma == self._firma:
            return
        self._firma = firma
        vaciar(self)
        if not aliados:
            self.append(self.lbl_vacio)
            return
        for a in aliados:
            caja = fila(6)
            pb = pixbuf(_clave(a.get("heroe")), "heroes", 22)
            icono = Gtk.Image.new_from_pixbuf(pb) if pb else Gtk.Image.new_from_icon_name("avatar-default")
            if not pb:
                icono.set_pixel_size(14)
            caja.append(icono)
            nombre = etiqueta(str(a.get("heroe") or "?").capitalize(), "t12 fuerte")
            nombre.set_size_request(70, -1)
            nombre.set_ellipsize(3)
            caja.append(nombre)
            caja.append(etiqueta(fmt_num(a.get("almas")), "t12 num tenue"))
            if a.get("bajas") is not None:
                caja.append(etiqueta(f"· {a['bajas']}/{a.get('muertes', 0)}/"
                                     f"{a.get('asistencias', 0)}", "t11 tenue"))
            self.append(caja)
