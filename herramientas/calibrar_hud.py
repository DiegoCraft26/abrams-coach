#!/usr/bin/env python3
"""Calibración del HUD: saca una captura, dice qué encontró y deja los recortes.

Sin una captura real del juego no se puede calibrar nada. Este comando hace el trabajo
pesado de una vez: captura, mide, propone colores y guarda los recortes para revisarlos.

Uso:
    python3 herramientas/calibrar_hud.py                 # captura el escritorio ahora
    python3 herramientas/calibrar_hud.py --imagen x.png  # usa una captura existente

Deja en `salida/calibracion/`:
    hud-<fecha>.png        la captura completa
    hud-reloj.png          el recorte del reloj
    hud-banda-oro.png      la banda donde se busca el oro
    hud-banda-items.png    la banda de ítems del HUD (abajo)

Y escribe `salida/calibracion/hud-medidas.json` con las medidas y las sugerencias de
configuración.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from PIL import Image  # noqa: E402

from coach.fuentes import hud_rapido  # noqa: E402

SALIDA = os.path.join(RAIZ, "salida", "calibracion")


def capturar(destino):
    subprocess.run(["spectacle", "-b", "-n", "-f", "-o", destino], check=True,
                   timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return destino


def colores_frecuentes(imagen, caja, limite=6):
    """Colores más repetidos dentro de una caja, ignorando el fondo oscuro."""
    zona = imagen.crop(caja).convert("RGB")
    from collections import Counter
    # Pillow >= 12 deprecó getdata(); se usa la vía nueva cuando existe.
    datos = (zona.get_flattened_data() if hasattr(zona, "get_flattened_data")
             else zona.getdata())
    cuenta = Counter(datos)
    utiles = [(c, n) for c, n in cuenta.most_common(400)
              if sum(c) > 120]                      # descarta fondo casi negro
    return [{"color": list(c), "pixeles": n} for c, n in utiles[:limite]]


def detectar_fila_items(imagen, zona):
    """Busca la fila de slots del HUD por columnas de brillo.

    No pretende acertar a la primera: devuelve candidatos para revisarlos a ojo.
    """
    recorte = imagen.crop(zona).convert("L")
    ancho, alto = recorte.size
    pix = recorte.load()
    columnas = []
    for x in range(ancho):
        brillo = sum(pix[x, y] for y in range(0, alto, 2)) / max(1, alto / 2)
        columnas.append(brillo)
    if not columnas:
        return []
    umbral = sum(columnas) / len(columnas) * 1.35
    tramos, inicio = [], None
    for x, b in enumerate(columnas):
        if b >= umbral and inicio is None:
            inicio = x
        elif b < umbral and inicio is not None:
            if x - inicio >= 8:
                tramos.append((zona[0] + inicio, zona[0] + x))
            inicio = None
    if inicio is not None:
        tramos.append((zona[0] + inicio, zona[0] + ancho))
    return tramos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--imagen", default=None)
    a = ap.parse_args()

    os.makedirs(SALIDA, exist_ok=True)
    fecha = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    ruta = a.imagen or os.path.join(SALIDA, f"hud-{fecha}.png")
    if not a.imagen:
        print("capturando el escritorio…")
        capturar(ruta)
    if not os.path.exists(ruta):
        print(f"no existe {ruta}")
        return 1

    imagen = Image.open(ruta).convert("RGB")
    print(f"captura: {ruta} · {imagen.size[0]}x{imagen.size[1]}")

    medidas = {"captura": ruta, "tamano": list(imagen.size), "fecha": fecha}

    # monitor del juego según KDE (para saber en qué mitad mirar)
    try:
        from coach.ventana import geometria_monitores
        monitores = geometria_monitores()
        medidas["monitores"] = [{"nombre": n, "x": x, "y": y, "ancho": w, "alto": h}
                                for n, x, y, w, h in monitores]
        for m in medidas["monitores"]:
            print(f"  monitor {m['nombre']}: {m['ancho']}x{m['alto']} en {m['x']},{m['y']}")
    except Exception as exc:                             # noqa: BLE001
        print(f"  (no se pudo leer la geometría de monitores: {type(exc).__name__})")

    # reloj
    caja_reloj = hud_rapido._escalar(hud_rapido.CAJAS_DEFECTO["reloj"], imagen.size)
    recorte = imagen.crop(caja_reloj)
    recorte.save(os.path.join(SALIDA, "hud-reloj.png"))
    datos = hud_rapido.leer(imagen)
    print(f"reloj en {caja_reloj}: {'leído ' + str(datos['t']) + ' s' if datos['t'] is not None else 'NO leído'}")
    medidas["reloj"] = {"caja": list(caja_reloj), "leido_s": datos["t"],
                        "ms": datos["ms_reloj"]}

    # banda del oro: colores más frecuentes para proponer `color_oro`
    caja_banda = hud_rapido._escalar(hud_rapido.CAJAS_DEFECTO["banda_oro"], imagen.size)
    imagen.crop(caja_banda).save(os.path.join(SALIDA, "hud-banda-oro.png"))
    colores = colores_frecuentes(imagen, caja_banda)
    medidas["banda_oro"] = {"caja": list(caja_banda), "colores": colores}
    print("colores dominantes en la banda del oro:")
    for c in colores[:5]:
        print(f"  {tuple(c['color'])} · {c['pixeles']} px")

    # ítems: la fila más baja del área de juego
    alto = imagen.size[1]
    zona_items = (caja_banda[0], int(alto * 0.72), caja_banda[2], alto)
    tramos = detectar_fila_items(imagen, zona_items)
    imagen.crop(zona_items).save(os.path.join(SALIDA, "hud-banda-items.png"))
    medidas["banda_items"] = {"zona": list(zona_items), "tramos": tramos[:14]}
    print(f"candidatos de slots en {zona_items}: {len(tramos)}")
    for i, (x0, x1) in enumerate(tramos[:14]):
        if i < 6:
            imagen.crop((x0, zona_items[1], x1, zona_items[3])).save(
                os.path.join(SALIDA, f"slot-{i:02d}.png"))
    if not tramos:
        print("  (ninguno: probablemente no hay HUD del juego en la captura)")

    ruta_json = os.path.join(SALIDA, "hud-medidas.json")
    with open(ruta_json, "w", encoding="utf-8") as f:
        json.dump(medidas, f, ensure_ascii=False, indent=1)
    print(f"medidas: {ruta_json}")

    # sugerencia de configuración: el color más claro de la banda suele ser el del número
    if colores:
        claro = max(colores, key=lambda c: sum(c["color"]))
        print("\npara probar la detección por color, en config/coach.yaml:")
        print("  fuentes:")
        print("    hud:")
        print(f"      color_oro: {claro['color']}")
        print("      tolerancia_color: 45")
    return 0


if __name__ == "__main__":
    sys.exit(main())
