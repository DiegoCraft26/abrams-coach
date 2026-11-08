"""Header: estado de la conexión, reloj, oro y fase. Es lo primero que se mira."""
from gi.repository import Gtk

from .base import clase_unica, etiqueta, fila, fmt_num, reloj

INSIGNIAS = ("insignia-vivo", "insignia-rancio", "insignia-offline")
CHIPS = ("chip-farm", "chip-pelear", "chip-equilibrio", "chip-inicio")


class Header(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.set_size_request(-1, 34)

        self.lbl_conexion = etiqueta("● conectando", "insignia insignia-rancio")
        self.append(self.lbl_conexion)

        self.lbl_reloj = etiqueta("--:--", "t24 num fuerte")
        self.append(self.lbl_reloj)

        self.lbl_oro = etiqueta("— sin gastar", "t13 tenue num")
        self.append(self.lbl_oro)

        self.lbl_patrimonio = etiqueta("", "t13 tenue num")
        self.append(self.lbl_patrimonio)

        self.lbl_delta = etiqueta("", "t13 tenue num")
        self.append(self.lbl_delta)

        relleno = Gtk.Box()
        relleno.set_hexpand(True)
        self.append(relleno)

        self.lbl_chiip = etiqueta("—", "chip chip-inicio")
        self.lbl_chiip.set_xalign(1)
        # Nace oculto: sin partida no hay fase, y "INICIO" al lado de "sin partida"
        # se leía como un estado contradictorio.
        self.lbl_chiip.set_visible(False)
        self.append(self.lbl_chiip)

    def actualizar(self, d):
        if not d:
            self.lbl_conexion.set_label("● sin conexión")
            clase_unica(self.lbl_conexion, INSIGNIAS, "insignia-offline")
            self.lbl_chiip.set_visible(False)
            return
        fuente = str(d.get("fuente") or "")
        if d.get("listo") is False:
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
        else:
            # La latencia del broadcast se muestra, no se esconde: es un dato del panel.
            edad = d.get("edad_s")
            etiqueta_lat = f" · datos de hace {round(edad)} s" if edad not in (None, 0) else ""
            self.lbl_conexion.set_label(f"● en vivo{etiqueta_lat}")
            clase_unica(self.lbl_conexion, INSIGNIAS, "insignia-vivo")

        self.lbl_reloj.set_label(reloj(d.get("t")))
        oro = d.get("oro")
        almas = d.get("almas")
        self.lbl_oro.set_label(f"{fmt_num(oro)} sin gastar" if oro is not None
                               else (f"{fmt_num(almas)} almas" if almas is not None else "— almas"))
        self.lbl_patrimonio.set_label(f"· {fmt_num(almas)} patrimonio"
                                      if oro is not None and almas is not None else "")
        dp = (d.get("economia") or {}).get("delta_pct")
        self.lbl_delta.set_label(f"· {dp*100:+.0f}% vs enemigos" if dp is not None else "")

        est = (d.get("estado") or {}).get("estado")
        self.lbl_chiip.set_visible(bool(est) and d.get("listo") is not False)
        if est:
            self.lbl_chiip.set_label(est)
            clase_unica(self.lbl_chiip, CHIPS, "chip-" + est.lower())
