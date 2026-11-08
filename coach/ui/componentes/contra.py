"""Contra la composición: ítems que la amenaza enemiga justifica, con su fuente.

Van **fuera del ranking** a propósito: sus datos de residual son negativos (los compra
quien ya va perdiendo), y este proyecto no recomienda por corazonada. El jugador ve el
consejo, el motivo y la fuente, y decide.

El coeficiente que se muestra es el CONTEXTUAL (residual × ganancia del estado), el mismo
con el que el motor puntúa el ítem; antes era siempre el número global y no se movía en
toda la partida. Por eso la firma de repintado incluye el coeficiente: si cambia el
contexto cambia el número aunque los ítems sean los mismos.
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
        firma = tuple((x.get("id"), x.get("coef"), x.get("motivo_ajuste")) for x in items)
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
            # El coeficiente va SIEMPRE visible: si es negativo, el ítem lo compra quien
            # ya va perdiendo y el panel no debe parecer que lo recomienda.
            coef = x.get("coef")
            if coef is not None:
                signo = "+" if coef >= 0 else ""
                clase = "t11 tenue" if coef >= 0 else "t11 aviso"
                global_ = x.get("coef_global")
                compara = ""
                if global_ is not None and abs(global_ - coef) >= 0.05:
                    compara = f" (global {global_:+.2f})"
                col.append(etiqueta(f"coef {signo}{coef:.2f} pp{compara} · "
                                    f"{'a favor' if coef >= 0 else 'en contra'}", clase))
            # Por qué el coeficiente no es el global: fase y almas, en una línea.
            if x.get("motivo_ajuste"):
                ajuste = etiqueta(x.get("motivo_ajuste"), "t11 tenue")
                envolver(ajuste, 34)
                col.append(ajuste)
            cuantos = x.get("enemigos_que_lo_justifican")
            detalle = etiqueta(f"{x.get('para')} · {cuantos} "
                               f"{'enemigo' if cuantos == 1 else 'enemigos'}", "t11 tenue")
            envolver(detalle, 30)
            col.append(detalle)
            fuente = etiqueta(f"fuente: {x.get('fuente')}", "t11 tenue")
            fuente.set_ellipsize(3)
            col.append(fuente)
            caja.append(col)
            self.append(caja)
