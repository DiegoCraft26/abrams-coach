"""BuildPlan: el camino de build como tira de 5 tiles.

Cada tile es un paso real del camino que arma `coach.decision.camino` (apertura → core →
spike): icono, nombre, precio y etapa. El estado pinta el borde: `tienes`, `ahora` o
`después`. Si el motor no manda camino (versión vieja o sin datos), cae al plan de dos
compras del grafo.
"""
from gi.repository import Gtk, Pango

from ..iconos import pixbuf
from .base import etiqueta, vaciar


class BuildPlan(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.add_css_class("camino")
        self.lbl_vacio = etiqueta("sin camino todavía", "vacio")
        self.append(self.lbl_vacio)
        self._firma = None

    def actualizar(self, d):
        d = d or {}
        camino = d.get("camino") or []
        plan = d.get("plan") or []
        objetivo = d.get("objetivo")
        firma = (tuple((c.get("id"), c.get("estado")) for c in camino),
                 tuple(p.get("id") for p in plan),
                 (objetivo or {}).get("id"), (objetivo or {}).get("faltan"))
        if firma == self._firma:
            return
        self._firma = firma
        vaciar(self)

        if camino:
            for i, paso in enumerate(camino[:5]):
                if i:
                    flecha = etiqueta("›", "camino-flecha")
                    flecha.set_valign(Gtk.Align.CENTER)
                    self.append(flecha)
                self.append(self._tile(paso))
            return

        # Respaldo: el plan de dos compras de siempre.
        if not plan and not objetivo:
            self.append(self.lbl_vacio)
            return
        for i, p in enumerate(plan[:2], 1):
            detalle = (f"{p.get('n', 0):,} veces después" if p.get("n")
                       else f"{p.get('costo', 0):,} almas")
            self.append(self._tile({"nombre": p.get("nombre") or "—",
                                    "id": p.get("id"), "costo": p.get("costo"),
                                    "etapa": detalle, "estado": "despues"}))
        if objetivo:
            self.append(self._tile({"nombre": objetivo.get("nombre") or "—",
                                    "id": objetivo.get("id"),
                                    "costo": objetivo.get("costo"),
                                    "etapa": f"faltan {objetivo.get('faltan', 0):,}",
                                    "estado": "ahora"}))

    def _tile(self, paso):
        estado = paso.get("estado") or "despues"
        caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        caja.add_css_class("camino-tile")
        caja.add_css_class(f"camino-tile-{estado}")
        caja.set_size_request(104, -1)

        pb = pixbuf(paso.get("id"), "items", 32)
        icono = Gtk.Image.new_from_pixbuf(pb) if pb else Gtk.Image.new_from_icon_name("image-missing")
        if not pb:
            icono.set_pixel_size(20)
        icono.set_halign(Gtk.Align.CENTER)
        caja.append(icono)

        nombre = etiqueta(paso.get("nombre") or "—", "camino-nombre")
        nombre.set_wrap(True)
        nombre.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        nombre.set_lines(2)
        nombre.set_ellipsize(Pango.EllipsizeMode.END)
        nombre.set_xalign(0.5)
        nombre.set_justify(Gtk.Justification.CENTER)
        caja.append(nombre)

        caja.append(etiqueta(f"{paso.get('costo') or 0:,}", "camino-precio", 0.5))
        etiqueta_estado = {"tienes": "tienes", "ahora": "ahora", "despues": ""}.get(
            estado, "")
        etapa = str(paso.get("etapa") or "")
        pie = " · ".join(x for x in (etapa, etiqueta_estado) if x)
        if pie:
            caja.append(etiqueta(pie, "camino-etapa", 0.5))
        return caja
