"""BuildPlan: las dos compras que suelen venir después de la recomendada.

Es el grafo real de compras de 1.9 M de partidas (`item-flow-stats`), no una lista escrita
a mano: cada ítem trae el número de veces que aparece justo después.
"""
from gi.repository import Gtk

from ..iconos import pixbuf
from .base import etiqueta, vaciar


class BuildPlan(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.lbl_vacio = etiqueta("sin plan todavía", "vacio")
        self.append(self.lbl_vacio)
        self._firma = None

    def actualizar(self, d):
        plan = (d or {}).get("plan") or []
        objetivo = (d or {}).get("objetivo")
        firma = (tuple(p.get("id") for p in plan),
                 (objetivo or {}).get("id"), (objetivo or {}).get("faltan"))
        if firma == self._firma:
            return
        self._firma = firma
        vaciar(self)
        if not plan and not objetivo:
            self.append(self.lbl_vacio)
            return
        for i, p in enumerate(plan, 1):
            self.append(self._linea(i, p.get("id"), p.get("nombre") or "—",
                                    f"{p.get('n', 0):,} veces después" if p.get("n") else ""))
        if objetivo:
            self.append(self._linea("$", objetivo.get("id"),
                                    objetivo.get("nombre") or "—",
                                    f"faltan {objetivo.get('faltan', 0):,}",
                                    clase="aviso"))

    def _linea(self, marca, ident, nombre, detalle, clase="t12 tenue"):
        caja = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        num = etiqueta(str(marca), "t11 tenue")
        num.set_size_request(12, -1)
        caja.append(num)
        pb = pixbuf(ident, "items", 22)
        icono = Gtk.Image.new_from_pixbuf(pb) if pb else Gtk.Image.new_from_icon_name("image-missing")
        if not pb:
            icono.set_pixel_size(14)
        caja.append(icono)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        col.set_hexpand(True)
        nombre_lbl = etiqueta(nombre, "t12 fuerte")
        nombre_lbl.set_ellipsize(3)
        col.append(nombre_lbl)
        if detalle:
            col.append(etiqueta(detalle, clase))
        caja.append(col)
        return caja
