"""Descarga y normaliza los iconos que el panel y el reconocimiento necesitan.

El arte de Deadlock es de Valve: no se distribuye con el repo. Este módulo lo baja del
bucket público de `deadlock-api` en el primer arranque (unos 9 MB, una sola vez) y lo
deja en `data/iconos/`, que está en `.gitignore`.

Uso manual:
    python3 coach/iconos.py
"""
import json
import os
import threading
import time
import urllib.request

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(DIR, "data")
SALIDA = os.path.join(DATA, "iconos")
TAM = 48  # lado de la plantilla normalizada

_hilo = None


def _bajar(url, destino, intentos=3):
    if os.path.exists(destino):
        return True
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "abrams-coach/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                crudo = r.read()
            temporal = destino + ".tmp"
            open(temporal, "wb").write(crudo)
            os.replace(temporal, destino)
            return True
        except Exception:                                        # noqa: BLE001
            time.sleep(1 + i)
    return False


def normalizar(ruta):
    """Deja junto al original un PNG de 48×48 con fondo negro (plantilla de lectura)."""
    destino = ruta.rsplit(".", 1)[0] + "_n.png"
    if os.path.exists(destino):
        return True
    from PIL import Image
    try:
        im = Image.open(ruta).convert("RGBA")
        fondo = Image.new("RGBA", im.size, (0, 0, 0, 255))
        im = Image.alpha_composite(fondo, im).convert("RGB").resize((TAM, TAM))
        im.save(destino)
        return True
    except Exception:                                            # noqa: BLE001
        return False


def items():
    cat = json.load(open(os.path.join(DATA, "catalogo.json")))
    os.makedirs(os.path.join(SALIDA, "items"), exist_ok=True)
    ok = 0
    for iid, d in cat.items():
        url = d.get("icono")
        if not url:
            continue
        ext = ".webp" if url.endswith(".webp") else ".png"
        destino = os.path.join(SALIDA, "items", f"{iid}{ext}")
        if _bajar(url, destino) and normalizar(destino):
            ok += 1
    return ok


def heroes():
    carpeta = os.path.join(SALIDA, "heroes")
    os.makedirs(carpeta, exist_ok=True)
    # Si ya hay retratos normalizados no se vuelve a pedir el catálogo en cada arranque.
    if any(f.endswith("_n.png") for f in os.listdir(carpeta)):
        return len([f for f in os.listdir(carpeta) if f.endswith("_n.png")])
    url = "https://api.deadlock-api.com/v1/assets/heroes"
    req = urllib.request.Request(url, headers={"User-Agent": "abrams-coach/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        hs = json.load(r)
    ok = 0
    for h in hs:
        u = (h.get("images", {}).get("icon_hero_card_webp")
             or h.get("images", {}).get("icon_image_small_webp"))
        nombre = (h.get("name") or "").lower().replace(" ", "_")
        if not u or not nombre:
            continue
        destino = os.path.join(carpeta, f"{nombre}.webp")
        if _bajar(u, destino) and normalizar(destino):
            ok += 1
    return ok


def asegurar():
    """Baja lo que falte. Devuelve (ítems, héroes) o (-1, -1) si no hubo red."""
    try:
        return items(), heroes()
    except Exception as exc:                                     # noqa: BLE001
        print(f"  iconos: no se pudieron bajar ({exc}); el panel usa marcadores")
        return -1, -1


def _completo():
    """¿Ya está el arte en disco? Evita el aviso en cada arranque."""
    items_dir = os.path.join(SALIDA, "items")
    heroes_dir = os.path.join(SALIDA, "heroes")
    if not (os.path.isdir(items_dir) and os.path.isdir(heroes_dir)):
        return False
    return (sum(1 for f in os.listdir(items_dir) if f.endswith("_n.png"))
            >= 100 and any(f.endswith("_n.png") for f in os.listdir(heroes_dir)))


def _tarea():
    if _completo():
        return
    print("  iconos: preparando arte local (una sola vez)…")
    n_items, n_heroes = asegurar()
    if n_items >= 0:
        print(f"  iconos: {n_items} ítems, {n_heroes} héroes")


def en_segundo_plano():
    """Lanza la descarga sin bloquear el arranque del panel."""
    global _hilo
    if _hilo is not None and _hilo.is_alive():
        return _hilo
    _hilo = threading.Thread(target=_tarea, name="iconos", daemon=True)
    _hilo.start()
    return _hilo


if __name__ == "__main__":
    print("items:", items())
    print("héroes:", heroes())
