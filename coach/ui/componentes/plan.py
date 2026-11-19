"""BuildPlan: el camino de build como tira de 5 tiles.

Cada tile es un paso real del camino que arma `coach.decision.camino` (apertura → core →
spike): icono, nombre, precio y etapa. El estado pinta el borde: `tienes`, `ahora` o
`después`. Si el motor no manda camino (versión vieja o sin datos), cae al plan de dos
compras del grafo.

Encima de la tira va el **perfil** vigente ("build corto", "counter de Haze"...). No es
decoración: es la razón por la que el camino de esta partida no es el de la anterior.
"""
from gi.repository import Gtk, Pango

from ..iconos import pixbuf
from .base import elipse, etiqueta, vaciar


class BuildPlan(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.lbl_perfil = etiqueta("", "perfil-camino")
        # Sin tope de ancho, el motivo del perfil estiraba la columna y aplastaba la de
        # al lado en 1280x720. Se corta con elipsis y el motivo completo va en el tooltip.
        elipse(self.lbl_perfil, 70)
        self.lbl_perfil.set_visible(False)
        self.append(self.lbl_perfil)
        # La tira sigue siendo horizontal; el perfil va encima.
        self.tira = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.tira.add_css_class("camino")
        self.append(self.tira)
        self.lbl_vacio = etiqueta("sin camino todavía", "vacio")
        self.tira.append(self.lbl_vacio)
        self._firma = None
        self._ahora = (None, None)

    def actualizar(self, d):
        d = d or {}
        camino = d.get("camino") or []
        plan = d.get("plan") or []
        objetivo = d.get("objetivo")
        perfil = d.get("perfil") or {}
        firma = (tuple((c.get("id"), c.get("estado"), c.get("contra"))
                       for c in camino),
                 tuple(p.get("id") for p in plan),
                 (objetivo or {}).get("id"), (objetivo or {}).get("faltan"),
                 perfil.get("etiqueta"), perfil.get("motivo"))
        if firma == self._firma:
            return
        self._firma = firma
        vaciar(self.tira)
        self._pintar_perfil(perfil)
        # El paso de ahora se pinta con el precio efectivo de la decisión: la tarjeta ya
        # dice «1 600 con lo que llevas» y el tile decía 3 200 (precio de lista). Dos
        # precios del mismo ítem en la misma pantalla es la clase de ruido que sobra.
        decision = d.get("decision") or {}
        item_dec = decision.get("item") or {}
        self._ahora = (str(item_dec.get("id")) if item_dec.get("id") else None,
                       item_dec.get("costo"))

        if camino:
            for i, paso in enumerate(camino[:5]):
                if i:
                    flecha = etiqueta("›", "camino-flecha")
                    flecha.set_valign(Gtk.Align.CENTER)
                    self.tira.append(flecha)
                self.tira.append(self._tile(paso))
            return

        # Respaldo: el plan de dos compras de siempre.
        if not plan and not objetivo:
            self.tira.append(self.lbl_vacio)
            return
        for i, p in enumerate(plan[:2], 1):
            detalle = (f"{p.get('n', 0):,} veces después" if p.get("n")
                       else f"{p.get('costo', 0):,} almas")
            self.tira.append(self._tile({"nombre": p.get("nombre") or "—",
                                         "id": p.get("id"), "costo": p.get("costo"),
                                         "etapa": detalle, "estado": "despues"}))
        if objetivo:
            self.tira.append(self._tile({"nombre": objetivo.get("nombre") or "—",
                                         "id": objetivo.get("id"),
                                         "costo": objetivo.get("costo"),
                                         "etapa": f"faltan {objetivo.get('faltan', 0):,}",
                                         "estado": "ahora"}))

    def _pintar_perfil(self, perfil):
        """Una línea que explica por qué este camino no es el del build fijo."""
        modo = perfil.get("modo")
        if not modo or modo == "base" or not perfil.get("etiqueta"):
            self.lbl_perfil.set_visible(False)
            return
        motivo = perfil.get("motivo") or ""
        self.lbl_perfil.set_label(
            perfil.get("etiqueta") + (f" · {motivo}" if motivo else ""))
        self.lbl_perfil.set_tooltip_text(motivo or None)
        clase = {"atras": "perfil-camino-atras",
                 "contra": "perfil-camino-contra"}.get(modo, "perfil-camino")
        from .base import clase_unica
        clase_unica(self.lbl_perfil,
                    ("perfil-camino", "perfil-camino-atras", "perfil-camino-contra"),
                    clase)
        self.lbl_perfil.set_visible(True)

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

        costo = paso.get("costo") or 0
        ahora_id, ahora_costo = getattr(self, "_ahora", (None, None))
        if paso.get("estado") == "ahora" and ahora_costo is not None \
                and str(paso.get("id")) == str(ahora_id):
            costo = ahora_costo
        caja.append(etiqueta(f"{costo:,}", "camino-precio", 0.5))
        etiqueta_estado = {"tienes": "tienes", "ahora": "ahora", "despues": ""}.get(
            estado, "")
        etapa = str(paso.get("etapa") or "")
        # El counter de composición ya no vive en su propia caja: entra en la tira como
        # un paso más y aquí solo se marca para saber por qué está (2026-11-18).
        contra = str(paso.get("contra") or "")
        pie = " · ".join(x for x in (etapa, "counter" if contra else "", etiqueta_estado)
                         if x)
        if contra:
            caja.set_tooltip_text(contra)
        if pie:
            caja.append(etiqueta(pie, "camino-etapa", 0.5))
        return caja
