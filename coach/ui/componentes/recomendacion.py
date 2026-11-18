"""RecommendationCard: la única acción principal del panel.

Una tarjeta, una idea: **el ítem**. Icono grande, nombre, cuánto cuesta y cuánto falta.
El texto quedó en una línea de razón (el resto, al tooltip): la versión anterior juntaba
precio + dos razones + contexto táctico + otras dos alternativas y en 1280x720 parecía
un párrafo. Las alternativas ahora son iconos, no frases.

Cuando toca vender, la tarjeta lo dice con nombre y slot: «VENDER · vende Bullet
Lifesteal (arma) · entra Bullet Armor».
"""
from gi.repository import Gtk

from ..iconos import pixbuf as _pixbuf
from .base import elipse, etiqueta, fmt_num, vaciar

CLASES_ACCION = ("accion", "accion-espera", "accion-nada")
ACCIONES = {
    "COMPRAR": ("COMPRAR", ""),
    "AHORRAR": ("AHORRAR", "accion-espera"),
    "VENDER": ("VENDER", "accion-espera"),
}


def _clase_accion(widget, variante):
    """Base «accion» más UNA variante. Antes se pasaba "accion accion-espera" como una
    sola clase: GTK la guardaba entera y `.accion` desaparecía, así que AHORRAR y
    VENDER —el estado más común— perdían el tamaño y el color del rótulo."""
    for c in CLASES_ACCION:
        widget.remove_css_class(c)
    widget.add_css_class("accion")
    if variante:
        widget.add_css_class(variante)
RAZON_CHARS = 58


class RecommendationCard(Gtk.Box):
    ANCHO_MAX = 640

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.add_css_class("tarjeta-alta")
        self.add_css_class("accion-card")
        self.set_hexpand(False)
        # Sin halign START la tarjeta se estiraba a todo el ancho de la columna.
        self.set_halign(Gtk.Align.START)
        self.set_size_request(self.ANCHO_MAX, -1)

        caja_icono = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        caja_icono.set_valign(Gtk.Align.CENTER)
        self.img = Gtk.Image()
        self.img.set_pixel_size(88)
        caja_icono.append(self.img)
        self.append(caja_icono)

        self.detalle = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.detalle.set_valign(Gtk.Align.CENTER)
        self.detalle.set_hexpand(True)

        self.lbl_accion = etiqueta("SIN PARTIDA", "accion")
        self.detalle.append(self.lbl_accion)

        self.lbl_nombre = etiqueta("Esperando partida", "nombre-item")
        # El nombre no puede definir el ancho mínimo: «Bullet Resist Shredder» a 28 px
        # estiraba la columna y aplastaba la de al lado.
        elipse(self.lbl_nombre, 22)
        self.detalle.append(self.lbl_nombre)

        # Precio / faltan / ETA / qué vender, en una sola línea.
        self.lbl_precio = etiqueta("", "precio-item num")
        self.detalle.append(self.lbl_precio)

        self.barra = Gtk.ProgressBar()
        self.barra.add_css_class("ahorro")
        self.barra.set_visible(False)
        self.detalle.append(self.barra)

        # Una razón. El resto y el contexto táctico viven en el tooltip.
        self.lbl_razon = etiqueta("", "razon")
        elipse(self.lbl_razon, RAZON_CHARS)
        self.detalle.append(self.lbl_razon)

        # Evidencia medida del motor v2: efecto, intervalo y muestra. Es una línea de
        # 12 px que solo aparece cuando el laboratorio tiene el dato; sin intervalo no
        # se pinta (un punto sin intervalo es una afirmación que no se sostiene).
        self.lbl_evidencia = etiqueta("", "t11 tenue")
        self.lbl_evidencia.set_visible(False)
        self.detalle.append(self.lbl_evidencia)

        # Alternativas: iconos con tooltip, no frases.
        self.fila_alt = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.fila_alt.set_visible(False)
        self.detalle.append(self.fila_alt)

        # Objetivos: una sola línea cuando el ritmo de almas va corto. Si no, invisible.
        self.lbl_objetivo = etiqueta("", "chip chip-evitar")
        self.lbl_objetivo.set_halign(Gtk.Align.START)
        self.lbl_objetivo.set_visible(False)
        self.detalle.append(self.lbl_objetivo)

        self.append(self.detalle)

    def limitar(self, ancho):
        """640 en columnas anchas; sin tope cuando la ventana es angosta."""
        self.set_size_request(int(ancho) if ancho else -1, -1)

    # ------------------------------------------------------------------
    def actualizar(self, d):
        d = d or {}
        recos = d.get("recomendaciones") or []
        # La apertura se mira ANTES de `listo`: ahora publica listo=false (para que la
        # cabecera no diga «en vivo»), pero su tarjeta tiene texto propio y no el
        # genérico «sin partida».
        if d.get("fuente") == "apertura" and not recos:
            self._apertura(d)
            return
        if d.get("listo") is False or not recos:
            self._sin_compra(d)
            return
        self.remove_css_class("accion-vacia")
        self.lbl_accion.set_visible(True)
        self.lbl_precio.set_visible(True)
        self.detalle.set_spacing(6)

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
        _clase_accion(self.lbl_accion, clase)

        costo = r.get("costo") or 0
        faltan = dec.get("faltan") if dec.get("faltan") is not None else r.get("faltan")
        eta = dec.get("eta_s")
        venta = d.get("venta") or {}
        if accion == "VENDER" and venta.get("nombre"):
            # Ya no es «juntar almas»: es hacer sitio.
            detalle = f"vende {venta.get('nombre')}"
            if venta.get("slot"):
                detalle += f" ({venta['slot']})"
            detalle += f" · entra {r.get('nombre') or '—'}"
            self.barra.set_visible(False)
        elif accion == "AHORRAR" and faltan:
            detalle = f"{fmt_num(costo)} almas · faltan {fmt_num(faltan)}"
            if eta:
                detalle += f" · {int(eta)} s"
            self.barra.set_visible(True)
            self.barra.set_fraction(
                0.0 if not costo else max(0.0, min(1.0, 1 - faltan / costo)))
        else:
            detalle = f"{fmt_num(costo)} almas"
            self.barra.set_visible(False)
        self.lbl_precio.set_label(detalle)

        self.lbl_nombre.set_label(r.get("nombre") or "—")

        razones = list(r.get("razones") or [])
        if accion == "VENDER" and venta.get("se_vende"):
            # El precio ya dice «vende X · entra Y»; repetirlo como razón gastaba la
            # única línea de texto. Aquí va el dato que justifica vender.
            razones.insert(0, f"{venta['nombre']} se vende en "
                              f"{venta['se_vende']} reales")
        elif dec.get("motivo") and dec["motivo"] not in razones:
            razones.insert(0, dec["motivo"])
        self.lbl_razon.set_label(razones[0] if razones else "sin razones medidas")
        self.lbl_razon.set_tooltip_text("\n".join(razones[:4]) or None)

        # Contexto táctico al tooltip de la tarjeta: sigue disponible sin gastar renglón.
        st = d.get("estado") or {}
        contexto = " · ".join(x for x in (st.get("motivo"), st.get("objetivo")) if x)
        self.set_tooltip_text(contexto or None)

        self._evidencia(r.get("evidencia") or d.get("evidencia"),
                        d.get("desempate"))
        self._alternativas(recos[1:4], costo)
        self._objetivos(d.get("objetivos"))

    def _evidencia(self, ev, desempate=None):
        """Evidencia medida; si el ítem no tiene, el desempate medido del laboratorio."""
        if not isinstance(ev, dict):
            self._desempate(desempate)
            return
        ic = ev.get("ic90") or []
        efecto = ev.get("efecto_pp")
        n = ev.get("n_partidas")
        if efecto is None or len(ic) != 2 or not n:
            self.lbl_evidencia.set_visible(False)
            return
        etiqueta_ev = ev.get("etiqueta") or "debil"
        # El veredicto importa más que el número: si el intervalo queda entero por
        # debajo de cero, el laboratorio NO respalda esta compra y hay que decirlo.
        if ic[1] < 0:
            juicio, clase = "⚠ no respalda · ", "aviso"
        elif ic[0] > 0:
            juicio, clase = "respalda · ", ""
        else:
            juicio, clase = "", ""
        # `clase_unica` recibe UNA clase: pasarle "t11 aviso" la guardaba como una
        # sola clase inexistente y se perdían t11 y tenue. Se toca solo la variante.
        for c in ("tenue", "aviso"):
            self.lbl_evidencia.remove_css_class(c)
        self.lbl_evidencia.add_css_class("aviso" if clase else "tenue")
        texto = (f"{juicio}{etiqueta_ev} · {efecto:+.1f} pp [{ic[0]:.1f}, {ic[1]:.1f}]"
                 f" · {int(n):,} partidas")
        evalue = ev.get("evalue")
        if evalue:
            texto += f" · E {evalue:.2f}"
        self.lbl_evidencia.set_label(texto)
        self.lbl_evidencia.set_visible(True)
        self.lbl_evidencia.set_tooltip_text(
            "Asociación condicional, no causalidad. Si hay un confusor de fuerza "
            f"{float(evalue):.2f} o más (por ejemplo la habilidad del jugador, que no "
            "está en la base), explica el efecto entero." if evalue else
            "Asociación condicional medida sobre partidas reales; no implica causalidad.")

    def _desempate(self, d):
        """Una línea cuando el laboratorio prefiere otra compra empatada.

        Va en el mismo renglón que la evidencia: dos avisos distintos ocupando dos
        líneas en una tarjeta de partida es ruido.
        """
        if not isinstance(d, dict) or not d.get("nombre"):
            self.lbl_evidencia.set_visible(False)
            return
        efecto = d.get("efecto_pp")
        texto = f"el laboratorio prefiere {d['nombre']}"
        if isinstance(efecto, (int, float)):
            texto += f" ({efecto:+.1f} pp)"
        self.lbl_evidencia.set_label(texto)
        for c in ("tenue", "aviso"):
            self.lbl_evidencia.remove_css_class(c)
        self.lbl_evidencia.add_css_class("tenue")
        self.lbl_evidencia.set_visible(True)
        self.lbl_evidencia.set_tooltip_text(
            "Efecto medido en partidas reales, replicado en partidas que el modelo no "
            "vio. El motor considera empatadas ambas compras; esta es la que el "
            "laboratorio respalda.")

    def _alternativas(self, otras, costo):
        vaciar(self.fila_alt)
        puestas = 0
        for x in otras:
            if not x.get("nombre") or puestas >= 3:
                continue
            pb = _pixbuf(x.get("id"), "items", 22)
            if not pb:
                # Sin icono, la alternativa no se enseña: un hueco roto parece un fallo
                # del panel, no un dato que falte.
                continue
            icono = Gtk.Image.new_from_pixbuf(pb)
            delta = (x.get("costo") or 0) - (costo or 0)
            signo = f"{delta:+,}" if delta else "mismo coste"
            razon = (x.get("razones") or [""])[0]
            texto = f"{x['nombre']} ({signo})"
            icono.set_tooltip_text(f"{texto} · {razon}" if razon else texto)
            self.fila_alt.append(icono)
            puestas += 1
        self.fila_alt.set_visible(bool(puestas))

    def _objetivos(self, obj):
        """Una línea de objetivos cuando el ritmo va corto; invisible si no aplica."""
        obj = obj or {}
        if not obj.get("prioridad"):
            self.lbl_objetivo.set_visible(False)
            self.lbl_objetivo.set_label("")
            self.lbl_objetivo.set_tooltip_text(None)
            return
        delta = obj.get("delta_pct")
        texto = "sin walkers"
        if isinstance(delta, (int, float)):
            texto += f" {delta * 100:+.0f}% almas"
        self.lbl_objetivo.set_label(texto)
        self.lbl_objetivo.set_tooltip_text(obj.get("nota") or None)
        self.lbl_objetivo.set_visible(True)

    def _apertura(self, d):
        """Menú o partida empezando: hay build de apertura, pero no una compra aún."""
        self._sin_compra({"listo": True, "mensaje": ""})
        self.lbl_accion.set_label("ESPERANDO PARTIDA")
        _clase_accion(self.lbl_accion, "accion-nada")
        self.lbl_nombre.set_label("Sin partida activa")
        motivo = ((d.get("estado") or {}).get("motivo") or "").strip()
        self.lbl_razon.set_label(motivo or "Abre Deadlock y entra a una partida.")
        self.lbl_razon.set_tooltip_text(
            "Si ya estás jugando, la app todavía no reconoció la partida.")

    def _sin_compra(self, d):
        self.lbl_evidencia.set_visible(False)
        # Estado vacío compacto: una frase, no una tarjeta de 190 px.
        self.add_css_class("accion-vacia")
        self.img.set_visible(False)
        self.barra.set_visible(False)
        self.lbl_accion.set_visible(False)
        self.lbl_precio.set_visible(False)
        self.fila_alt.set_visible(False)
        self.detalle.set_spacing(4)
        self.lbl_razon.set_tooltip_text(None)
        self.set_tooltip_text(None)
        self.lbl_objetivo.set_visible(False)
        self.lbl_precio.set_label("")
        if d.get("listo") is False:
            self.lbl_accion.set_label("SIN PARTIDA")
            _clase_accion(self.lbl_accion, "accion-nada")
            self.lbl_nombre.set_label("Esperando partida")
            self.lbl_razon.set_label(d.get("mensaje") or "")
            return
        if d.get("fuente") == "apertura":      # sin recomendaciones: ver rama de arriba
            self.lbl_accion.set_label("ESPERANDO PARTIDA")
            _clase_accion(self.lbl_accion, "accion-nada")
            self.lbl_nombre.set_label("Sin partida activa")
            self.lbl_razon.set_label("Abre Deadlock y entra a una partida.")
            self.lbl_razon.set_tooltip_text(
                "Si ya estás jugando, la app todavía no reconoció la partida.")
            return
        if d.get("solo_reloj"):
            self.lbl_accion.set_label("MODO PANTALLA")
            _clase_accion(self.lbl_accion, "accion-nada")
            self.lbl_nombre.set_label("Solo reloj")
            self.lbl_razon.set_label("Sin broadcast no veo inventario ni rivales.")
            self.lbl_razon.set_tooltip_text(
                "Abre Tab para el marcador o juega una partida con retransmisión.")
            return
        est = (d.get("estado") or {}).get("estado") or "INICIO"
        self.lbl_accion.set_label("SIN COMPRA")
        _clase_accion(self.lbl_accion, "accion-nada")
        if d.get("lectura_dudosa"):
            self.lbl_nombre.set_label("No puedo leer bien")
        else:
            self.lbl_nombre.set_label("Fase inicial" if est == "INICIO"
                                      else "Sin compra todavía")
        notas = d.get("notas") or []
        self.lbl_razon.set_label(notas[0] if notas else "ningún ítem pasa el filtro")
        self.lbl_razon.set_tooltip_text("\n".join(notas) or None)
