"""Inventory: tus 12 slots con el residual de cada ítem.

Verde = el ítem rinde más de lo esperado para su minuto de compra; rojo = menos.
"""
from gi.repository import Gtk

from ..iconos import pixbuf
from .base import etiqueta, fila, vaciar

SLOTS = 12


class Inventory(Gtk.Box):
    def __init__(self, lado=44, columnas=12):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.lado = lado
        self.flow = Gtk.FlowBox()
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        # Homogéneo en FALSE y anclado a la izquierda: antes los 12 slots se estiraban
        # hasta 200 px cada uno en pantallas anchas, que parece un error de maquetación.
        self.flow.set_homogeneous(False)
        self.flow.set_valign(Gtk.Align.START)
        self.flow.set_halign(Gtk.Align.START)
        self.flow.set_max_children_per_line(columnas)
        self.flow.set_min_children_per_line(1)
        self.flow.set_column_spacing(4)
        self.flow.set_row_spacing(4)
        self.lbl_slots = etiqueta("", "t11 apagado")
        self.append(self.lbl_slots)
        self.append(self.flow)
        self._firma = None
        self._rellenar([])

    def set_lado(self, lado, columnas=None):
        if lado == self.lado and columnas is None:
            return
        self.lado = lado
        if columnas:
            self.flow.set_max_children_per_line(columnas)
        self._firma = None

    def actualizar(self, d):
        d = d or {}
        inv = d.get("inventario") or []
        slots = d.get("slots") or {}
        firma = (self.lado, tuple((x.get("id"), x.get("valor")) for x in inv),
                 tuple(sorted((k, v.get("usados"), v.get("total"))
                              for k, v in slots.items())))
        if firma == self._firma:
            return
        self._firma = firma
        self._rellenar(inv)
        # Huecos por categoría: "arma 3/4 · vitalidad 4/4 · espíritu 2/4".
        nombres = {"weapon": "arma", "vitality": "vitalidad", "spirit": "espíritu"}
        partes = []
        for clave in ("weapon", "vitality", "spirit"):
            datos = slots.get(clave) or {}
            if datos:
                partes.append(f"{nombres[clave]} {datos.get('usados', 0)}/"
                              f"{datos.get('total', 0)}")
        # Bonus de categoría (4,800): solo se avisa cuando falta poco; perseguirlo
        # siempre convertiría el build en uno genérico.
        for clave in ("weapon", "vitality", "spirit"):
            datos = (d.get("categorias") or {}).get(clave) or {}
            falta = datos.get("falta")
            if falta and 0 < falta <= 1000:
                partes.append(f"bonus {nombres[clave]} −{falta:,}")
        self.lbl_slots.set_label(" · ".join(partes))

    def _rellenar(self, inv):
        vaciar(self.flow)
        for x in inv[:SLOTS]:
            self.flow.append(self._slot(x))
        for _ in range(max(0, SLOTS - len(inv))):
            vacio = Gtk.Box()
            vacio.add_css_class("slot")
            vacio.add_css_class("slot-vacio")
            vacio.set_size_request(self.lado, self.lado)
            self.flow.append(vacio)

    def _slot(self, x):
        caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        caja.add_css_class("slot")
        valor = x.get("valor")
        if valor is None:
            caja.add_css_class("slot-vacio")
        else:
            caja.add_css_class("slot-bien" if valor >= 0 else "slot-mal")
        caja.set_size_request(self.lado, self.lado)
        caja.set_tooltip_text(f"{x.get('nombre', '')}"
                              + (f" · {valor:+.1f} pp" if valor is not None else ""))
        pb = pixbuf(x.get("id"), "items", self.lado - 6)
        icono = Gtk.Image.new_from_pixbuf(pb) if pb else Gtk.Image.new_from_icon_name("image-missing")
        if not pb:
            icono.set_pixel_size(12)
        icono.set_halign(Gtk.Align.CENTER)
        caja.append(icono)
        if valor is not None and self.lado >= 36:
            v = etiqueta(f"{valor:+.0f}", "slot-valor " + ("acento" if valor >= 0 else "error"))
            v.set_xalign(0.5)
            caja.append(v)
        return caja
