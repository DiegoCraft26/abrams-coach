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
        # Histórico de la composición: cuántas veces la has jugado y cómo acabó, del
        # archivo local. Va arriba y con su muestra: no es un consejo, es un recuento.
        self.lbl_visto = etiqueta("", "t11")
        self.lbl_visto.set_wrap(True)
        self.lbl_visto.set_visible(False)
        self.append(self.lbl_visto)
        # Y qué compran los que ganan contra estos rivales, con su muestra. Es una
        # sugerencia medida, no una orden: el motor sigue decidiendo.
        self.lbl_sugerencia = etiqueta("", "t11")
        self.lbl_sugerencia.set_wrap(True)
        self.lbl_sugerencia.set_visible(False)
        self.append(self.lbl_sugerencia)
        self._firma = None

    def actualizar(self, d):
        items = (d or {}).get("contra_composicion") or []
        visto = (d or {}).get("visto") or {}
        sugerencia = str((d or {}).get("sugerencia_items") or "")
        # La firma tiene que cubrir TODO lo que se pinta: si cambia el nombre, el
        # coste, el conteo de enemigos o la fuente sin cambiar el coeficiente, la caja
        # se quedaba con el texto viejo.
        firma = (tuple((x.get("id"), x.get("nombre"), x.get("costo"),
                        x.get("coef"), x.get("coef_global"), x.get("motivo_ajuste"),
                        x.get("urgente"), x.get("enemigos_que_lo_justifican"),
                        x.get("para"), x.get("fuente"), tuple(x.get("contra_quien") or ()))
                       for x in items),
                 visto.get("aviso"), visto.get("total"), sugerencia)
        if firma == self._firma:
            return
        self._firma = firma
        vaciar(self)
        aviso = visto.get("aviso") or ""
        self.lbl_visto.set_label(aviso)
        self.lbl_visto.set_visible(bool(aviso))
        self.lbl_visto.set_tooltip_text(
            f"de {visto.get('total', 0):,} partidas de Abrams del archivo local"
            if visto else None)
        if aviso:
            self.append(self.lbl_visto)
        self.lbl_sugerencia.set_label(sugerencia)
        self.lbl_sugerencia.set_visible(bool(sugerencia))
        if sugerencia:
            self.append(self.lbl_sugerencia)
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
            # Urgente = frena al rival que está ganando la partida. Se dice a quién:
            # "contra Haze" no es lo mismo que "contra su composición".
            if x.get("urgente") and x.get("contra_quien"):
                quien = ", ".join(str(q) for q in x["contra_quien"][:2])
                ur = etiqueta(f"frena a {quien}: va por encima", "etiqueta-evitar")
                envolver(ur, 30)
                col.append(ur)
            # Una línea por ítem, tres datos como mucho: qué es, contra quién y con
            # qué respaldo. El resto (fuente, motivo del ajuste, coeficiente global)
            # vive en el tooltip: la versión anterior gastaba cinco renglones por
            # ítem y el panel se leía como un informe.
            cuantos = x.get("enemigos_que_lo_justifican") or 0
            if x.get("urgente"):
                linea = None          # ya se dijo arriba, con nombre
            elif cuantos:
                linea = etiqueta(f"{cuantos} "
                                 f"{'enemigo lo justifica' if cuantos == 1 else 'enemigos lo justifican'}",
                                 "t11 tenue")
            else:
                linea = etiqueta(str(x.get("para") or ""), "t11 tenue")
            coef = x.get("coef")
            if coef is not None:
                signo = "+" if coef >= 0 else ""
                clase = "t11 tenue" if coef >= 0 else "t11 aviso"
                linea_coef = etiqueta(f"{signo}{coef:.1f} pp · "
                                      f"{'a favor' if coef >= 0 else 'en contra'}", clase)
                fila = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                if linea is not None:
                    fila.append(linea)
                fila.append(linea_coef)
                col.append(fila)
            elif linea is not None:
                col.append(linea)
            detalles = []
            if x.get("para"):
                detalles.append(str(x.get("para")))
            if x.get("motivo_ajuste"):
                detalles.append(str(x.get("motivo_ajuste")))
            if x.get("coef_global") is not None and coef is not None:
                detalles.append(f"coeficiente global {x.get('coef_global'):+.2f} pp")
            if x.get("fuente"):
                detalles.append(f"fuente: {x.get('fuente')}")
            if detalles:
                titulo.set_tooltip_text("\n".join(detalles))
                col.set_tooltip_text("\n".join(detalles))
            caja.append(col)
            self.append(caja)
