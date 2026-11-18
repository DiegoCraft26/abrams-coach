"""Header: estado de la conexión, reloj, oro y fase. Es lo primero que se mira.

48 px de alto, reloj y oro a 20 px, el resto a 12. Dos tamaños nada más: la cabecera
se lee de un vistazo y no compite con la tarjeta de acción.
"""
from gi.repository import Gtk, Pango

from .base import clase_unica, etiqueta, fmt_num, reloj

INSIGNIAS = ("insignia-vivo", "insignia-rancio", "insignia-offline")
CHIPS = ("chip-farm", "chip-pelear", "chip-equilibrio", "chip-inicio")


class Header(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.add_css_class("cabecera")
        self.set_size_request(-1, 48)

        self.lbl_conexion = etiqueta("● conectando", "insignia insignia-rancio")
        self.lbl_conexion.set_valign(Gtk.Align.CENTER)
        self.append(self.lbl_conexion)

        self.lbl_reloj = etiqueta("--:--", "reloj num fuerte")
        self.lbl_reloj.set_valign(Gtk.Align.CENTER)
        self.append(self.lbl_reloj)

        caja_oro = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        caja_oro.set_valign(Gtk.Align.CENTER)
        self.lbl_oro = etiqueta("—", "oro num fuerte")
        caja_oro.append(self.lbl_oro)
        self.lbl_oro_sub = etiqueta("almas", "t12 tenue")
        self.lbl_oro_sub.set_valign(Gtk.Align.END)
        caja_oro.append(self.lbl_oro_sub)
        self.append(caja_oro)

        self.lbl_patrimonio = etiqueta("", "t12 meta")
        self.lbl_patrimonio.set_ellipsize(Pango.EllipsizeMode.END)
        self.lbl_patrimonio.set_valign(Gtk.Align.CENTER)
        self.append(self.lbl_patrimonio)

        self.lbl_delta = etiqueta("", "t12 meta")
        self.lbl_delta.set_ellipsize(Pango.EllipsizeMode.END)
        self.lbl_delta.set_valign(Gtk.Align.CENTER)
        self.append(self.lbl_delta)

        # Amenaza: el rival que no se busca solo. Va en la cabecera porque es lo único
        # que hay que ver sin abrir ninguna sección.
        self.lbl_amenaza = etiqueta("", "chip chip-evitar")
        self.lbl_amenaza.set_valign(Gtk.Align.CENTER)
        self.lbl_amenaza.set_visible(False)
        self.append(self.lbl_amenaza)

        relleno = Gtk.Box()
        relleno.set_hexpand(True)
        self.append(relleno)

        self.lbl_chiip = etiqueta("—", "chip chip-inicio")
        self.lbl_chiip.set_xalign(1)
        self.lbl_chiip.set_valign(Gtk.Align.CENTER)
        # Nace oculto: sin partida no hay fase, y "INICIO" al lado de "sin partida"
        # se leía como un estado contradictorio.
        self.lbl_chiip.set_visible(False)
        self.append(self.lbl_chiip)
        # Aviso de héroe: el motor solo tiene la ruta de Abrams. Si estás jugando otro,
        # el panel lo dice en vez de darte ítems de Abrams como si fueran tuyos.
        self.lbl_aviso = etiqueta("", "chip")
        self.lbl_aviso.set_valign(Gtk.Align.CENTER)
        self.lbl_aviso.set_visible(False)
        self.append(self.lbl_aviso)

    def actualizar(self, d):
        if not d:
            self.lbl_conexion.set_label("● sin conexión")
            clase_unica(self.lbl_conexion, INSIGNIAS, "insignia-offline")
            self.lbl_chiip.set_visible(False)
            self.lbl_amenaza.set_visible(False)
            return
        aviso = str(d.get("aviso_heroe") or "")
        self.lbl_aviso.set_label(aviso)
        self.lbl_aviso.set_visible(bool(aviso))
        fuente = str(d.get("fuente") or "")
        fase_juego = str(d.get("fase_juego") or "")
        if d.get("listo") is False:
            # El menú, la cola y el fin de partida no son fallos: el console.log del
            # juego lo dice gratis. Antes todo caía en «sin partida», que se lee como
            # avería (visto 2026-11-15 al abrir la app antes de entrar a la partida).
            if fase_juego == "menu":
                self.lbl_conexion.set_label("● en el menú")
            elif fase_juego == "partida":
                self.lbl_conexion.set_label("● en partida · abre Tab")
            else:
                self.lbl_conexion.set_label("● sin partida")
            clase_unica(self.lbl_conexion, INSIGNIAS, "insignia-offline")
        elif d.get("rancio"):
            edad = d.get("edad_s")
            self.lbl_conexion.set_label(
                "● datos congelados" + (f" · hace {round(edad)} s" if edad is not None else ""))
            clase_unica(self.lbl_conexion, INSIGNIAS, "insignia-rancio")
        elif fuente == "simulado":
            self.lbl_conexion.set_label("● demo")
            clase_unica(self.lbl_conexion, INSIGNIAS, "insignia-vivo")
        elif fuente == "pantalla":
            edad = d.get("edad_s")
            etiqueta_lat = f" · hace {round(edad)} s" if edad not in (None, 0) else ""
            self.lbl_conexion.set_label(f"● pantalla{etiqueta_lat}")
            clase_unica(self.lbl_conexion, INSIGNIAS, "insignia-vivo")
        else:
            # La latencia del broadcast se muestra, no se esconde: es un dato del panel.
            edad = d.get("edad_s")
            etiqueta_lat = f" · datos de hace {round(edad)} s" if edad not in (None, 0) else ""
            self.lbl_conexion.set_label(f"● en vivo{etiqueta_lat}")
            clase_unica(self.lbl_conexion, INSIGNIAS, "insignia-vivo")

        self.lbl_reloj.set_label(reloj(d.get("t")))
        oro = d.get("oro")
        almas = d.get("almas")
        valor = oro if oro is not None else almas
        self.lbl_oro.set_label(fmt_num(valor))
        self.lbl_oro_sub.set_label("sin gastar" if oro is not None else "almas")
        self.lbl_patrimonio.set_label(f"· {fmt_num(almas)} patrimonio"
                                      if oro is not None and almas is not None else "")
        dp = (d.get("economia") or {}).get("delta_pct")
        self.lbl_delta.set_label(f"· {dp*100:+.0f}% vs enemigos" if dp is not None else "")

        amen = (d.get("amenazas") or {}).get("peor") or {}
        if amen.get("evitar_solo") and amen.get("heroe"):
            self.lbl_amenaza.set_label(f"EVITAR {str(amen['heroe']).upper()}")
            self.lbl_amenaza.set_tooltip_text(amen.get("motivo") or "")
            self.lbl_amenaza.set_visible(True)
        else:
            self.lbl_amenaza.set_visible(False)

        est = (d.get("estado") or {}).get("estado")
        self.lbl_chiip.set_visible(bool(est) and d.get("listo") is not False)
        if est:
            self.lbl_chiip.set_label(est)
            clase_unica(self.lbl_chiip, CHIPS, "chip-" + est.lower())
