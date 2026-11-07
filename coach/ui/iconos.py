"""Iconos desde disco, con caché en memoria.

El panel viejo llamaba a `GdkPixbuf.new_from_file_at_scale` en cada refresco (1 Hz por
ítem y por slot): 12 slots + enemigos + plan = decenas de lecturas de disco por segundo.
Medido en la versión anterior: 4-6% de un núcleo en reposo. Aquí cada (tipo, id, lado)
se carga una vez.
"""
import os

from gi.repository import GdkPixbuf

DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "data", "iconos")

_cache = {}
_MAX = 160


def ruta_icono(ident, tipo="items"):
    for ext in (".webp", ".png"):
        ruta = os.path.join(DIR, tipo, f"{ident}{ext}")
        if os.path.exists(ruta):
            return ruta
    return None


def pixbuf(ident, tipo="items", lado=48):
    """Pixbuf escalado, o None si el icono no existe."""
    if ident is None:
        return None
    clave = (tipo, str(ident), int(lado))
    if clave in _cache:
        return _cache[clave]
    ruta = ruta_icono(ident, tipo)
    pb = None
    if ruta:
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(ruta, lado, lado, True)
        except Exception:                                   # noqa: BLE001
            pb = None
    if len(_cache) > _MAX:                                  # presupuesto de RAM
        for k in list(_cache)[:40]:
            _cache.pop(k, None)
    _cache[clave] = pb
    return pb
