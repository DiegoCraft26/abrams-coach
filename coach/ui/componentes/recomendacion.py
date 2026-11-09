"""RecommendationCard: la única acción principal del panel.

Jerarquía: estado (COMPRAR/AHORRAR/VENDER), nombre del ítem, precio con ETA, dos
razones y el contexto táctico. Ancho máximo 640 px: en un monitor de 1440p la tarjeta
no se estira hasta parecer un párrafo.
"""
from gi.repository import Gtk

from ..iconos import pixbuf as _pixbuf
from .base import clase_unica, envolver, etiqueta, fmt_num

CLASES_ACCION = ("accion", "accion-espera", "accion-nada")
ACCIONES = {
    "COMPRAR": ("COMPRAR", "accion"),
    "AHORRAR": ("AHORRAR", "accion accion-espera"),
    "VENDER": ("VENDER", "accion accion-espera"),
}


class RecommendationCard(Gtk.Box):
    ANCHO_MAX = 640

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.add_css_class("tarjeta-alta")
        self.add_css_class("accion-card")
        self.set_hexpand(False)
        # Sin halign START la tarjeta se estiraba a todo el ancho de la columna
        # (1,280 px en un monitor 1440p) aunque pidiera 640.
        self.set_halign(Gtk.Align.START)
        self.set_size_request(self.ANCHO_MAX, -1)

        caja_icono = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        caja_icono.set_valign(Gtk.Align.CENTER)
        self.img = Gtk.Image()
        self.img.set_pixel_size(88)
        caja_icono.append(self.img)
        self.append(caja_icono)

        self.detalle = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.detalle.set_valign(Gtk.Align.CENTER)
        self.detalle.set_hexpand(True)

        self.lbl_accion = etiqueta("SIN PARTIDA", "accion")
        self.detalle.append(self.lbl_accion)

        self.lbl_nombre = etiqueta("Esperando partida", "nombre-item")
        # El nombre no puede definir el ancho mínimo de la ventana: "Bullet Resist
        # Shredder" a 28 px estiraba la columna principal y aplastaba la de al lado.
        envolver(self.lbl_nombre, 18)
        self.detalle.append(self.lbl_nombre)

        self.lbl_precio = etiqueta("", "precio-item num")
        self.detalle.append(self.lbl_precio)

        self.barra = Gtk.ProgressBar()
        self.barra.add_css_class("ahorro")
        self.barra.set_visible(False)
        self.detalle.append(self.barra)

        self.lbl_razon = etiqueta("", "razon")
        envolver(self.lbl_razon, 52)
        self.detalle.append(self.lbl_razon)

        self.lbl_contexto = etiqueta("", "contexto")
        envolver(self.lbl_contexto, 58)
        self.detalle.append(self.lbl_contexto)

        # Alternativas: nombre, delta de coste y su razón. No compiten con la principal.
        self.lbl_alternativas = etiqueta("", "alternativa")
        envolver(self.lbl_alternativas, 58)
        self.detalle.append(self.lbl_alternativas)

        self.append(self.detalle)

    def limitar(self, ancho):
        """640 en columnas anchas; sin tope cuando la ventana es angosta."""
        self.set_size_request(int(ancho) if ancho else -1, -1)

    # ------------------------------------------------------------------
    def actualizar(self, d):
        d = d or {}
        recos = d.get("recomendaciones") or []
        if d.get("listo") is False or not recos:
            self._sin_compra(d)
            return
        self.remove_css_class("accion-vacia")
        self.lbl_accion.set_visible(True)
        self.lbl_precio.set_visible(True)
        self.lbl_contexto.set_visible(True)
        self.lbl_alternativas.set_visible(True)
        self.detalle.set_spacing(8)

        r = recos[0]
        self.img.set_visible(True)
        desde_disco = _pixbuf(r.get("id"), "items", 88)
        if not desde_disco:
            self.img.set_from_icon_name("image-missing")
        else:
            self.img.set_from_pixbuf(desde_disco)

        dec = d.get("decision") or {}
        accion = dec.get("accion") or ("COMPRAR" if r.get("alcanza") else "AHORRAR")
        titulo, clase = ACCIONES.get(accion, ("COMPRAR", "accion"))
        self.lbl_accion.set_label(titulo)
        clase_unica(self.lbl_accion, CLASES_ACCION, clase)

        costo = r.get("costo") or 0
        faltan = dec.get("faltan") if dec.get("faltan") is not None else r.get("faltan")
        eta = dec.get("eta_s")
        if accion == "AHORRAR" and faltan:
            detalle = f"{fmt_num(costo)} almas · faltan {fmt_num(faltan)}"
            if eta:
                detalle += f" · ETA {int(eta)} s"
            self.barra.set_visible(True)
            self.barra.set_fraction(
                0.0 if not costo else max(0.0, min(1.0, 1 - faltan / costo)))
        elif accion == "VENDER":
            detalle = f"{fmt_num(costo)} almas · vende para hacer sitio"
            self.barra.set_visible(False)
        else:
            detalle = f"{fmt_num(costo)} almas"
            self.barra.set_visible(False)
        self.lbl_precio.set_label(detalle)

        self.lbl_nombre.set_label(r.get("nombre") or "—")
        razones = list(r.get("razones") or [])
        if dec.get("motivo") and dec["motivo"] not in razones:
            razones.insert(0, dec["motivo"])
        self.lbl_razon.set_label(" · ".join(razones[:2]) or "sin razones medidas")
        st = d.get("estado") or {}
        self.lbl_contexto.set_label(" · ".join(
            x for x in (st.get("motivo"), st.get("objetivo")) if x) or " ")

        # Alternativas con su delta de coste y su primera razón.
        lineas = []
        for x in recos[1:4]:
            nombre = x.get("nombre")
            if not nombre:
                continue
            delta = (x.get("costo") or 0) - costo
            signo = (f"{delta:+,}" if delta else "mismo coste")
            razon = (x.get("razones") or [""])[0]
            lineas.append(f"{nombre} ({signo}) · {razon}" if razon
                          else f"{nombre} ({signo})")
        self.lbl_alternativas.set_label("\n".join(lineas[:2]))

    def _sin_compra(self, d):
        # Sin ítem no hay icono que enseñar: el hueco con el icono roto de GTK parecía
        # un fallo del panel en vez de un estado vacío.
        # Estado vacío compacto: una frase, no una tarjeta de 190 px. Se esconden
        # etiqueta, precio, contexto y alternativas; quedan nombre y motivo.
        self.add_css_class("accion-vacia")
        self.img.set_visible(False)
        self.barra.set_visible(False)
        self.lbl_accion.set_visible(False)
        self.lbl_precio.set_visible(False)
        self.lbl_contexto.set_visible(False)
        self.lbl_alternativas.set_visible(False)
        self.detalle.set_spacing(4)
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
