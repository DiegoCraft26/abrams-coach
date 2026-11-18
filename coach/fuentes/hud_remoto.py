"""HUD leído en otra máquina: se mandan los recortes, no la pantalla.

Por qué existe: el OCR de tesseract es lo único que de verdad pide CPU en el ciclo del
HUD (~90-250 ms por lectura). La captura por región de KWin, en cambio, cuesta 1-3 ms.
Repartir así deja lo barato en la PC que juega y lo caro en la PC que no juega:

    [PC de Diego]  captura por caja (1-3 ms) + PNG de 2-15 kB  ->  LAN (~5 ms)
    [<pc-auxiliar>] tesseract + parseo (300-500 ms)             ->  JSON

Lo que viaja son los tres recortes del HUD (reloj, banda de oro, oro), no el cuadro de
2560x1440: mandar la pantalla entera costaría ~2 MB por lectura y no hace falta.

Si el servidor no contesta, `leer()` devuelve None y el llamador sigue con el OCR local:
el panel nunca depende de la red para pintar el reloj.
"""
from __future__ import annotations
from .. import identidad

import base64
import io
import json
import urllib.error
import urllib.request

# Cajas que hay que mandar para que el servidor pueda hacer el mismo trabajo que el
# lector local. `oro` va de reserva: si el detector por color no encuentra el bloque,
# el lector cae a la caja fija y la necesita.
CAJAS_NECESARIAS = ("reloj", "banda_oro", "oro")


def _b64(im) -> str:
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=False, compress_level=1)   # velocidad, no tamaño
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _pedir(servidor: str, cuerpo: dict, timeout_s: float) -> dict:
    datos = json.dumps(cuerpo).encode("utf-8")
    pet = urllib.request.Request(
        servidor.rstrip("/") + "/leer", data=datos, method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": identidad.AGENTE})
    with urllib.request.urlopen(pet, timeout=timeout_s) as r:
        return json.loads(r.read().decode("utf-8"))


def leer(servidor: str, marco, cajas=None, color_oro=None, timeout_s: float = 3.0,
         metricas: dict | None = None):
    """Pide el HUD al servidor. Devuelve el mismo dict que `hud_rapido.leer` o None.

    `marco` solo necesita `.size` y `.crop(caja)` — sirve `hud_rapido.MarcoPerezoso`,
    así que la captura sigue ocurriendo en esta máquina, caja por caja.
    """
    from . import hud_rapido

    if not servidor:
        return None
    cfg = {**hud_rapido.CAJAS_DEFECTO, **(cajas or {})}
    tamano = tuple(marco.size)
    enviadas = {}
    try:
        for nombre in CAJAS_NECESARIAS:
            caja = hud_rapido._escalar(cfg[nombre], tamano)
            enviadas[",".join(str(int(v)) for v in caja)] = _b64(marco.crop(caja))
    except Exception:                                          # noqa: BLE001
        return None

    cuerpo = {"tamano": list(tamano), "cajas": enviadas}
    if cajas:
        cuerpo["cajas_cfg"] = cajas
    if color_oro:
        cuerpo["color"] = list(color_oro)
    try:
        salida = _pedir(servidor, cuerpo, timeout_s)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        if metricas is not None:
            metricas["fallos"] = metricas.get("fallos", 0) + 1
        return None
    if not isinstance(salida, dict):
        return None
    if metricas is not None:
        metricas["lecturas"] = metricas.get("lecturas", 0) + 1
        metricas["ms_total_remoto"] = salida.get("ms_total")
        metricas["kb_enviados"] = round(sum(len(v) for v in enviadas.values()) / 1024, 1)
    salida["fuente_ocr"] = "remoto"
    return salida
