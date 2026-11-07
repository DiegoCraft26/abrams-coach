#!/usr/bin/env python3
"""Diagnóstico de lectura de pantalla. Guarda la foto y un recorte con rejilla."""
import json, os, sys
sys.path.insert(0, RAIZ)
from PIL import Image, ImageDraw
from coach import lector, deteccion, autocalibrado, refinar as refino

# Este script vive en herramientas/calibracion/: la raíz del repo está 2
# niveles arriba, no en el directorio del archivo.
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SALIDA = os.path.join(RAIZ, "salida")
os.makedirs(SALIDA, exist_ok=True)

def main():
    cfg = lector.cargar_cfg()
    img = lector.capturar(os.path.join(SALIDA, "captura.png"))
    im = Image.open(img)
    print(f"captura: {im.size[0]}x{im.size[1]} -> {img}")

    print("detectando rejilla automáticamente…")
    auto = autocalibrado.detectar_rejilla(img)
    if auto:
        print(f"  rejilla {auto['ny']}x{auto['nx']} · fuerza {auto['fuerza']} · paso {auto['paso']}")
        punt, x0, y0, paso = refino.refinar(img, auto)
        celdas = refino._celdas(x0, y0, paso, auto["nx"], auto["ny"],
                                auto["ancho_analisis"], auto["alto_analisis"])
        leer = deteccion.leer_celdas(img, celdas)
        aciertos = sum(1 for f in leer for c in f if c.get("id"))
        total = auto["nx"]*auto["ny"]
        print(f"  refinado: paso {paso} · acierto {aciertos}/{total} ({aciertos/total*100:.0f}%)")
        auto["celdas"] = celdas
        auto["region"] = [x0/auto["ancho_analisis"], y0/auto["alto_analisis"],
                          (auto["nx"]*paso)/auto["ancho_analisis"],
                          (auto["ny"]*paso)/auto["alto_analisis"]]
        cfg["scoreboard"] = auto["region"]
        cfg["iconos_por_fila"] = auto["nx"]
        cfg["filas_total"] = auto["ny"]
        # la columna de retratos va justo a la izquierda de la rejilla
        x, y, w, h = auto["region"]
        ancho_col = w / max(1, auto["nx"])
        cfg["heroes_col"] = [max(0.0, x - ancho_col), y, ancho_col, h]
        cfg["filas_enemigas"] = auto["ny"] // 2
        import json as _j
        _j.dump(cfg, open(lector.CFG, "w"), indent=1)
        print(f"  guardado en {lector.CFG}")
    else:
        print("  no encontré la cuadrícula: abre el marcador con Tab y repite")

    t, ok_t = lector.leer_tiempo(img, cfg)
    a, ok_a = lector.leer_almas(img, cfg)
    print(f"tiempo: {t} (ok={ok_t}) · almas: {a} (ok={ok_a})")

    sb = cfg["scoreboard"]
    W, H = im.size
    caja = (int(sb[0]*W), int(sb[1]*H), int((sb[0]+sb[2])*W), int((sb[1]+sb[3])*H))
    recorte = im.crop(caja).copy()
    d = ImageDraw.Draw(recorte)
    nx, ny = cfg["iconos_por_fila"], cfg["filas_enemigas"]+cfg["filas_aliadas"]
    for i in range(nx+1):
        x = i*recorte.size[0]/nx
        d.line([(x,0),(x,recorte.size[1])], fill=(255,0,0), width=2)
    for j in range(ny+1):
        y = j*recorte.size[1]/ny
        d.line([(0,y),(recorte.size[0],y)], fill=(255,0,0), width=2)
    ruta = os.path.join(SALIDA, "rejilla-scoreboard.png")
    recorte.save(ruta)
    print(f"rejilla guardada en {ruta}")

    print("\nlectura de la rejilla (scoreboard):")
    rejilla = deteccion.leer_rejilla(img, sb, nx, ny)
    cat = json.load(open(os.path.join(RAIZ, "data", "catalogo.json")))
    for fila in rejilla:
        print("  " + " ".join(
            (cat.get(c["id"], {}).get("nombre", "?")[:10] if c["id"] else f"—{c['confianza']:.2f}")
            for c in fila))

if __name__ == "__main__":
    main()
