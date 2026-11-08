"""Botón "Revisar": pide /api/revisar y muestra el diagnóstico en texto plano.

Un botón y un área de texto, nada más: la lógica vive en el servidor. Si el coach no
responde, se dice; si el modelo no está configurado, el servidor lo explica y aquí se
ve tal cual (no se rellena con suposiciones).
"""
import json
import threading
import urllib.request

from gi.repository import GLib, Gtk

from .base import etiqueta

ESPERA_S = 60.0          # el diagnóstico toca la API (puerta de 3 s) y puede llamar al modelo


class Revisar(Gtk.Box):
    def __init__(self, puerto=8090, con_modelo=True):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.puerto = int(puerto)
        self.con_modelo = bool(con_modelo)

        self.boton = Gtk.Button(label="Revisar")
        self.boton.add_css_class("boton")
        self.boton.set_halign(Gtk.Align.START)
        self.boton.set_tooltip_text("Diagnóstico de la conexión y veredicto del modelo")
        self.boton.connect("clicked", self.revisar)
        self.append(self.boton)

        self.texto = etiqueta("", "pie")
        self.texto.set_wrap(True)
        self.texto.set_xalign(0.0)
        self.texto.set_selectable(True)
        self.append(self.texto)

    # ------------------------------------------------------------------ interno
    def _url(self):
        modelo = "1" if self.con_modelo else "0"
        return f"http://127.0.0.1:{self.puerto}/api/revisar?modelo={modelo}"

    def _pedir(self):
        try:
            with urllib.request.urlopen(self._url(), timeout=ESPERA_S) as r:
                datos = json.loads(r.read().decode("utf-8"))
            texto = self._formatear(datos)
        except Exception as exc:                               # noqa: BLE001
            texto = f"sin respuesta del coach en :{self.puerto} ({type(exc).__name__}: {exc})"
        GLib.idle_add(self._pintar, texto)

    def _pintar(self, texto):
        self.texto.set_label(texto)
        self.boton.set_sensitive(True)
        return False

    @staticmethod
    def _formatear(datos):
        """Resumen legible del JSON de /api/revisar. Los None se dicen, no se maquillan."""
        d = (datos or {}).get("diagnostico") or {}
        edad = d.get("edad_datos_s")
        lineas = [
            f"fuente {d.get('fuente') or 'sin medir'} · "
            f"datos de hace {round(edad, 1) if edad is not None else 'sin medir'} s"
            f"{' · RANCIOS' if d.get('rancio') else ''}",
            f"último t {d.get('ultimo_t') if d.get('ultimo_t') is not None else 'sin medir'} · "
            f"tick {((d.get('red') or {}).get('tick')) if (d.get('red') or {}).get('tick') is not None else 'sin medir'}",
        ]
        m = d.get("match")
        if m:
            lineas.append(f"match {m.get('match')} · en listado "
                          f"{_si_no(m.get('en_listado'))} · broadcast {_si_no(m.get('con_broadcast'))}")
        else:
            lineas.append("match sin identificar")
        if d.get("mensaje"):
            lineas.append(str(d["mensaje"]))
        avisos = d.get("avisos") or []
        if avisos:
            lineas.append("último aviso: " + str(avisos[-1].get("mensaje") or "")[:120])
        if (d.get("cuota_pausa_s") or 0) > 0:
            lineas.append(f"cuota: la API pide esperar {d['cuota_pausa_s']:.0f} s")
        texto = (datos or {}).get("texto")
        if texto:
            lineas.append("")
            lineas.append(str(texto))
        else:
            motivo = (datos or {}).get("motivo")
            if motivo:
                lineas.append(f"veredicto no disponible: {motivo}")
        return "\n".join(lineas)

    # ------------------------------------------------------------------ público
    def revisar(self, _boton=None):
        self.boton.set_sensitive(False)
        self.texto.set_label("revisando…")
        threading.Thread(target=self._pedir, name="revisar", daemon=True).start()


def _si_no(valor):
    if valor is None:
        return "sin medir"
    return "sí" if valor else "no"
