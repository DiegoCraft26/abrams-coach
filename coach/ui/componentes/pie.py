"""StatusBar: de dónde vienen los datos, cuánto tardó el motor y si la lectura es fiable.

Nada de números decorativos: si la latencia no se midió, se dice "—".
"""
import re

from gi.repository import Gtk

from .base import etiqueta

# El console.log del juego dice en qué pantalla está (menú, cola, partida). Saberlo sin
# adivinar es lo que permite decir «en partida» aunque no haya broadcast ni HUD legible.
FASES_LEGIBLES = {
    "GameInProgress": "en partida",
    "MainMenu": "menú",
    "Hideout": "hideout",
    "HeroSelection": "eligiendo héroe",
    "PostGame": "fin de partida",
    "Lobby": "lobby",
}


def texto_fuente(d) -> str:
    """«fuente pantalla · fase en partida» o lo que de verdad se sepa."""
    d = d or {}
    fuente = str(d.get("fuente") or "—").replace("_", " ")
    partes = [f"fuente {fuente}"]
    fase = d.get("fase_juego")
    if fase:
        # Una fase desconocida se separa por mayúsculas: «AlgoRaro» → «algo raro».
        legible = FASES_LEGIBLES.get(str(fase))
        if legible is None:
            legible = re.sub(r"(?<!^)(?=[A-Z])", " ", str(fase)).lower()
        partes.append(f"fase {legible}")
    return " · ".join(partes)


class StatusBar(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        self.lbl_motor = etiqueta("motor — ms", "pie")
        self.append(self.lbl_motor)

        self.lbl_confianza = etiqueta("confianza —", "pie")
        self.append(self.lbl_confianza)

        self.lbl_fuente = etiqueta("fuente —", "pie")
        self.append(self.lbl_fuente)

        # Latencia por eslabón: cuánto tarda la captura, cuánto la lectura de pantalla y
        # cuánto va el TV de Valve por detrás. Sin esto no se puede saber qué está lento.
        self.lbl_latencia = etiqueta("", "pie")
        self.append(self.lbl_latencia)

        relleno = Gtk.Box()
        relleno.set_hexpand(True)
        self.append(relleno)

        self.lbl_aviso = etiqueta("", "pie aviso")
        self.lbl_aviso.set_xalign(1)
        self.append(self.lbl_aviso)

    def actualizar(self, d):
        d = d or {}
        ms = d.get("ms")
        self.lbl_motor.set_label(f"motor {ms} ms" if ms is not None else "motor — ms")
        conf = d.get("confianza")
        self.lbl_confianza.set_label(
            f"confianza {conf*100:.0f}%" if conf is not None else "confianza —")
        # "en_vivo" es el identificador interno del servidor; aquí se lee como texto.
        self.lbl_fuente.set_label(texto_fuente(d))
        la = d.get("latencia") or {}
        piezas = []
        if la.get("captura_ms") is not None:
            piezas.append(f"captura {la['captura_ms']:.0f} ms")
        if la.get("lectura_ms"):
            piezas.append(f"lectura {la['lectura_ms']:.0f} ms")
        if la.get("broadcast_s") is not None:
            # Esto NO es la latencia del TV: es la diferencia entre el reloj del HUD y
            # el del broadcast, y el demo del broadcast incluye la pre-partida (~1 min).
            # Decir "TV 76 s atrás" era una cifra que no se podía sostener.
            piezas.append(f"desfase reloj TV {la['broadcast_s']:+.0f} s")
        self.lbl_latencia.set_label(" · ".join(piezas))
        if d.get("lectura_dudosa"):
            self.lbl_aviso.set_label("lectura dudosa: mantengo la última buena")
        elif d.get("estable") is False:
            self.lbl_aviso.set_label("ajustando")
        else:
            self.lbl_aviso.set_label("")
