"""RecommendationCard: la única acción principal del panel (qué comprar).

Jerarquía: etiqueta de acción, nombre del ítem, precio, dos razones y el contexto táctico.
Si no alcanza el oro, la acción pasa a «AHORRA PARA» y aparece una barra con lo que falta.
"""
from gi.repository import Gtk

from ..iconos import pixbuf as _pixbuf
from .base import clase_unica, envolver, etiqueta, fmt_num

CLASES_ACCION = ("accion", "accion-espera", "accion-nada")


class RecommendationCard(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        for c in ("tarjeta-alta",):
            self.add_css_class(c)

        caja_icono = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        caja_icono.set_valign(Gtk.Align.CENTER)
        self.img = Gtk.Image()
        self.img.set_pixel_size(96)
        caja_icono.append(self.img)
        self.append(caja_icono)

        self.detalle = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.detalle.set_valign(Gtk.Align.CENTER)
        self.detalle.set_hexpand(True)

        self.lbl_accion = etiqueta("SIN PARTIDA", "accion")
        self.detalle.append(self.lbl_accion)

        self.lbl_nombre = etiqueta("Esperando partida", "nombre-item")
        # El nombre no puede definir el ancho mínimo de la ventana: "Bullet Resist
        # Shredder" a 32 px estiraba la columna principal y aplastaba la de al lado.
        envolver(self.lbl_nombre, 18)
        self.detalle.append(self.lbl_nombre)

        self.lbl_precio = etiqueta("", "precio-item num")
        self.detalle.append(self.lbl_precio)

        self.barra = Gtk.ProgressBar()
        self.barra.add_css_class("ahorro")
        self.barra.set_visible(False)
        self.detalle.append(self.barra)

        self.lbl_razon = etiqueta("", "razon")
        envolver(self.lbl_razon, 46)
        self.detalle.append(self.lbl_razon)

        self.lbl_contexto = etiqueta("", "contexto")
        envolver(self.lbl_contexto, 52)
        self.detalle.append(self.lbl_contexto)

        self.append(self.detalle)

        # alternativas: dos segundas opciones, apagadas, para no competir con la principal
        self.lbl_alternativas = etiqueta("", "t12 tenue")
        envolver(self.lbl_alternativas, 46)
        self.detalle.append(self.lbl_alternativas)

    # ------------------------------------------------------------------
    def actualizar(self, d):
        d = d or {}
        recos = d.get("recomendaciones") or []
        if d.get("listo") is False or not recos:
            self._sin_compra(d)
            return

        r = recos[0]
        self.img.set_visible(True)
        desde_disco = _pixbuf(r.get("id"), "items", 96)
        if not desde_disco:
            self.img.set_from_icon_name("image-missing")
        else:
            self.img.set_from_pixbuf(desde_disco)

        alcanza = r.get("alcanza")
        if alcanza is False:
            self.lbl_accion.set_label("AHORRA PARA")
            clase_unica(self.lbl_accion, CLASES_ACCION, "accion-espera")
            faltan = r.get("faltan") or 0
            costo = r.get("costo") or 0
            self.lbl_precio.set_label(f"{fmt_num(costo)} almas · faltan {fmt_num(faltan)}")
            self.barra.set_visible(True)
            self.barra.set_fraction(0.0 if not costo else max(0.0, min(1.0, 1 - faltan / costo)))
        elif r.get("requiere_venta"):
            self.lbl_accion.set_label("COMPRA CON CAMBIO")
            clase_unica(self.lbl_accion, CLASES_ACCION, "accion")
            self.lbl_precio.set_label(f"{fmt_num(r.get('costo'))} almas · vende para hacer sitio")
            self.barra.set_visible(False)
        else:
            self.lbl_accion.set_label("COMPRA AHORA")
            clase_unica(self.lbl_accion, CLASES_ACCION, "accion")
            self.lbl_precio.set_label(f"{fmt_num(r.get('costo'))} almas")
            self.barra.set_visible(False)

        self.lbl_nombre.set_label(r.get("nombre") or "—")
        self.lbl_razon.set_label(" · ".join((r.get("razones") or [])[:2]) or "sin razones medidas")
        st = d.get("estado") or {}
        self.lbl_contexto.set_label(" · ".join(
            x for x in (st.get("motivo"), st.get("objetivo")) if x) or " ")

        otras = [x.get("nombre") for x in recos[1:3] if x.get("nombre")]
        self.lbl_alternativas.set_label("luego: " + " · ".join(otras) if otras else "")

    def _sin_compra(self, d):
        # Sin ítem no hay icono que enseñar: el hueco con el icono roto de GTK parecía
        # un fallo del panel en vez de un estado vacío.
        self.img.set_visible(False)
        self.barra.set_visible(False)
        self.lbl_alternativas.set_label("")
        self.lbl_precio.set_label("")
        if d.get("listo") is False:
            self.lbl_accion.set_label("SIN PARTIDA")
            clase_unica(self.lbl_accion, CLASES_ACCION, "accion-nada")
            self.lbl_nombre.set_label("Esperando partida")
            self.lbl_razon.set_label(d.get("mensaje") or "")
            self.lbl_contexto.set_label(" ")
            return
        est = (d.get("estado") or {}).get("estado") or "INICIO"
        self.lbl_accion.set_label("SIN COMPRA")
        clase_unica(self.lbl_accion, CLASES_ACCION, "accion-nada")
        if d.get("lectura_dudosa"):
            self.lbl_nombre.set_label("No puedo leer bien")
        else:
            self.lbl_nombre.set_label("Fase inicial" if est == "INICIO" else "Sin compra todavía")
        self.lbl_razon.set_label(" · ".join(d.get("notas") or []) or "ningún ítem pasa el filtro")
        st = d.get("estado") or {}
        self.lbl_contexto.set_label(" · ".join(
            x for x in (st.get("motivo"), st.get("objetivo")) if x) or " ")
