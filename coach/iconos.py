"""Descarga y normaliza iconos para reconocimiento por plantilla."""
import json, os, sys, time, urllib.request

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(DIR, "data")
SALIDA = os.path.join(DATA, "iconos")
TAM = 48  # lado de la plantilla normalizada


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
        except Exception:
            time.sleep(1 + i)
    return False


def normalizar(ruta):
    from PIL import Image
    try:
        im = Image.open(ruta).convert("RGBA")
        fondo = Image.new("RGBA", im.size, (0, 0, 0, 255))
        im = Image.alpha_composite(fondo, im).convert("RGB").resize((TAM, TAM))
        im.save(ruta.rsplit(".", 1)[0] + "_n.png")
        return True
    except Exception:
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
    os.makedirs(os.path.join(SALIDA, "heroes"), exist_ok=True)
    import urllib.parse
    url = "https://api.deadlock-api.com/v1/assets/heroes"
    req = urllib.request.Request(url, headers={"User-Agent": "abrams-coach/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        hs = json.load(r)
    ok = 0
    for h in hs:
        u = h.get("images", {}).get("icon_hero_card_webp") or h.get("images", {}).get("icon_image_small_webp")
        nombre = (h.get("name") or "").lower().replace(" ", "_")
        if not u or not nombre:
            continue
        destino = os.path.join(SALIDA, "heroes", f"{nombre}.webp")
        if _bajar(u, destino) and normalizar(destino):
            ok += 1
    return ok


if __name__ == "__main__":
    print("items:", items())
    print("héroes:", heroes())
