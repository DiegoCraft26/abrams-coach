#!/usr/bin/env python3
"""Puerta de calidad de la interfaz. Falla si algo se ve mal, se sale o no carga.

Uso:  python3 verificar_ui.py [url]

Playwright no está en el python del sistema sino en el pylib de DSH; el script agrega
esa ruta solo, así que ya no hace falta exportar PYTHONPATH a mano.
"""
import os, sys, json

# Este script vive en herramientas/calibracion/: la raíz del repo está 2
# niveles arriba, no en el directorio del archivo.
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:                                    # ¿está Playwright en este intérprete?
    import playwright                   # noqa: F401
except ImportError:
    _extra = os.path.expanduser("~/.dsh/bin/pylib")
    if os.path.isdir(_extra) and _extra not in sys.path:
        sys.path.insert(0, _extra)

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8090"
SALIDA = os.path.join(RAIZ, "salida")
TAMANOS = [(960, 1080, "objetivo"), (1280, 720, "hd"), (600, 900, "angosto")]

fallos, avisos = [], []


def contraste(rgb1, rgb2):
    def lin(c):
        c = c / 255
        return c/12.92 if c <= 0.03928 else ((c+0.055)/1.055) ** 2.4
    def lum(c):
        r, g, b = c
        return 0.2126*lin(r) + 0.7152*lin(g) + 0.0722*lin(b)
    a, b = lum(rgb1), lum(rgb2)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def parse_rgb(txt):
    nums = [int(x) for x in txt.replace("rgba(", "").replace("rgb(", "").replace(")", "").split(",")[:3]]
    return tuple(nums)


def main():
    from playwright.sync_api import sync_playwright
    os.makedirs(SALIDA, exist_ok=True)
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        for ancho, alto, etiqueta in TAMANOS:
            pg = nav.new_page(viewport={"width": ancho, "height": alto}, device_scale_factor=1)
            errores = []
            pg.on("console", lambda m: errores.append(m.text) if m.type == "error" else None)
            pg.on("pageerror", lambda e: errores.append(str(e)))
            pg.goto(URL, wait_until="load")
            pg.wait_for_timeout(3500)

            datos = pg.evaluate("""() => {
                const q = s => document.querySelector(s);
                const cs = e => e ? getComputedStyle(e) : null;
                const imgs = [...document.images];
                const hero = q('.hero'), icon = q('.portrait img'), title = q('.title');
                return {
                  scrollW: document.documentElement.scrollWidth,
                  clientW: document.documentElement.clientWidth,
                  scrollH: document.documentElement.scrollHeight,
                  clientH: document.documentElement.clientHeight,
                  imgs: imgs.length,
                  imgsRotas: imgs.filter(i => i.complete && i.naturalWidth === 0).length,
                  titulo: (q('.title')||{}).textContent || '',
                  chip: (q('.chip')||{}).textContent || '',
                  slots: document.querySelectorAll('.inv .slot').length,
                  iconoAncho: icon ? icon.getBoundingClientRect().width : 0,
                  heroH: hero ? hero.getBoundingClientRect().height : 0,
                  colorTexto: cs(title) ? cs(title).color : 'rgb(0,0,0)',
                  colorChip: cs(q('.chip')) ? cs(q('.chip')).color : 'rgb(0,0,0)',
                  colorFondo: cs(document.body).backgroundColor,
                  vive: (q('.live')||{}).className || ''
                };
            }""")

            if datos["scrollW"] > datos["clientW"] + 1:
                fallos.append(f"{etiqueta}: desborda a lo ancho ({datos['scrollW']} > {datos['clientW']})")
            if datos["scrollH"] > datos["clientH"] + 1:
                fallos.append(f"{etiqueta}: desborda a lo alto ({datos['scrollH']} > {datos['clientH']})")
            if datos["imgsRotas"]:
                fallos.append(f"{etiqueta}: {datos['imgsRotas']} imágenes rotas")
            if datos["slots"] != 12:
                fallos.append(f"{etiqueta}: {datos['slots']} slots, se esperaban 12")
            if etiqueta == "objetivo" and datos["iconoAncho"] < 180:
                fallos.append(f"{etiqueta}: el icono mide {datos['iconoAncho']:.0f}px, se esperaban ≥180")
            if not datos["titulo"].strip():
                fallos.append(f"{etiqueta}: título vacío")
            if "on" not in datos["vive"] and "off" not in datos["vive"]:
                fallos.append(f"{etiqueta}: el indicador de vivo no tiene estado")

            for nombre, c in (("título", datos["colorTexto"]), ("chip", datos["colorChip"])):
                try:
                    ratio = contraste(parse_rgb(c), parse_rgb(datos["colorFondo"]))
                    if ratio < 4.5:
                        fallos.append(f"{etiqueta}: contraste de {nombre} {ratio:.2f} < 4.5")
                except Exception:
                    avisos.append(f"{etiqueta}: no pude calcular contraste de {nombre}")

            if errores:
                fallos.append(f"{etiqueta}: errores de consola: {errores[:2]}")

            ruta = os.path.join(SALIDA, f"ui-{etiqueta}-{ancho}x{alto}.png")
            pg.screenshot(path=ruta)
            print(f"  {etiqueta:9} {ancho}x{alto} · icono {datos['iconoAncho']:.0f}px · "
                  f"slots {datos['slots']} · «{datos['titulo'][:24]}» · {ruta.split('/')[-1]}")
            pg.close()
        nav.close()

    print()
    for a in avisos:
        print("  aviso:", a)
    if fallos:
        print(f"{len(fallos)} FALLOS:")
        for f in fallos:
            print("   -", f)
        return 1
    print("interfaz: OK en los 3 tamaños")
    return 0


if __name__ == "__main__":
    sys.exit(main())
