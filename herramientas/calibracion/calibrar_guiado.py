#!/usr/bin/env python3
"""Calibración guiada por pantallas: marcador, tienda y HUD.

Cada paso captura una sola imagen, detecta la cuadrícula, la refina y guarda solo lo que
salió bien. Se puede correr por partes: si un paso falla, los demás siguen.
"""
import json, os, sys, time
sys.path.insert(0, RAIZ)
from coach import lector, deteccion, autocalibrado, refinar as refino

# Este script vive en herramientas/calibracion/: la raíz del repo está 2
# niveles arriba, no en el directorio del archivo.
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SALIDA = os.path.join(RAIZ, "salida", "calibracion")


def capturar_y_detectar(nombre, nx_esperado=None):
    os.makedirs(SALIDA, exist_ok=True)
    ruta = lector.capturar(os.path.join(SALIDA, f"{nombre}.png"))
    auto = autocalibrado.detectar_rejilla(ruta)
    if not auto:
        return None, ruta, "no encontré cuadrícula (¿hay iconos en pantalla?)"
    punt, x0, y0, paso = refino.refinar(ruta, auto)
    celdas = refino._celdas(x0, y0, paso, auto["nx"], auto["ny"],
                            auto["ancho_analisis"], auto["alto_analisis"])
    leido = deteccion.leer_celdas(ruta, celdas, umbral=0.55)
    aciertos = sum(1 for f in leido for c in f if c.get("id"))
    total = auto["nx"]*auto["ny"]
    tasa = aciertos/max(1, total)
    info = {
        "ruta": ruta, "nx": auto["nx"], "ny": auto["ny"], "paso": paso,
        "celdas": celdas, "tasa": tasa, "puntuacion": punt,
        "region": [x0/auto["ancho_analisis"], y0/auto["alto_analisis"],
                   (auto["nx"]*paso)/auto["ancho_analisis"],
                   (auto["ny"]*paso)/auto["alto_analisis"]],
    }
    return info, ruta, None


def paso_marcador(cfg, guardar):
    print("\n── Paso 1: marcador ──")
    print("En el juego pulsa TAB y déjalo abierto.")
    input("ENTER cuando el marcador esté en pantalla… ")
    info, ruta, err = capturar_y_detectar("marcador")
    if err:
        print("  ✗", err)
        return False
    print(f"  rejilla {info['ny']}x{info['nx']} · paso {info['paso']} · "
          f"iconos reconocidos {info['tasa']*100:.0f}%")
    if info["tasa"] < 0.6:
        print("  ⚠ pocos iconos reconocidos: revisa", ruta)
        return False
    x, y, w, h = info["region"]
    cfg["scoreboard"] = info["region"]
    cfg["iconos_por_fila"] = info["nx"]
    cfg["filas_total"] = info["ny"]
    cfg["filas_enemigas"] = max(1, info["ny"]//2)
    col = w/max(1, info["nx"])
    cfg["heroes_col"] = [max(0.0, x-col), y, col, h]
    guardar(cfg)
    print("  ✓ marcador guardado")
    return True


def paso_tienda(cfg, guardar):
    print("\n── Paso 2: tus ítems (tienda) ──")
    print("Abre la tienda (B) con tus ítems visibles.")
    input("ENTER cuando se vean tus ítems… ")
    info, ruta, err = capturar_y_detectar("tienda")
    if err:
        print("  ✗", err)
        return False
    print(f"  rejilla {info['ny']}x{info['nx']} · iconos {info['tasa']*100:.0f}%")
    if info["tasa"] < 0.5:
        print("  ⚠ poca confianza: no lo guardo")
        return False
    cfg["mis_items"] = info["region"]
    cfg["mis_items_nx"] = info["nx"]
    cfg["mis_items_ny"] = info["ny"]
    guardar(cfg)
    print("  ✓ ítems propios guardados")
    return True


def paso_hud(cfg):
    print("\n── Paso 3: HUD (tiempo y almas) ──")
    print("En partida, sin menús abiertos.")
    input("ENTER cuando estés en partida… ")
    ruta = lector.capturar(os.path.join(SALIDA, "hud.png"))
    t, ok_t = lector.leer_tiempo(ruta, cfg)
    a, ok_a = lector.leer_almas(ruta, cfg)
    print(f"  tiempo: {t} (ok={ok_t}) · almas: {a} (ok={ok_a})")
    if not ok_t or not ok_a:
        print("  ⚠ revisa config/regiones.json: 'tiempo' y 'almas' son fracciones de pantalla")
        return False
    print("  ✓ HUD legible")
    return True


def main():
    cfg = lector.cargar_cfg()

    def guardar(c):
        json.dump(c, open(lector.CFG, "w"), indent=1)

    print("Calibración guiada. Puedes saltarte pasos con Ctrl+C y volver después.")
    hechos = []
    for nombre, fn in (("marcador", paso_marcador),
                       ("tienda", paso_tienda)):
        try:
            if fn(cfg, guardar):
                hechos.append(nombre)
        except KeyboardInterrupt:
            print("\nsaltado")
    try:
        if paso_hud(cfg):
            hechos.append("hud")
    except KeyboardInterrupt:
        print("\nsaltado")

    print(f"\nlisto: {', '.join(hechos) if hechos else 'nada calibrado'}")
    print(f"configuración en {lector.CFG}")
    return 0 if hechos else 1


if __name__ == "__main__":
    sys.exit(main())
