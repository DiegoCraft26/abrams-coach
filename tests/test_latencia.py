"""Pruebas de la cadena rápida: captura compartida, HUD y FPS.

Se generan HUD sintéticos con la fuente que trae el sistema y se comprueba que el lector
saca el reloj y el oro. No es lo mismo que una captura real del juego (el HUD cambia con
cada parche), pero atrapa las roturas de código: recortes movidos, escalado mal aplicado,
umbral de color, tiempos.
"""
import os
import statistics
import sys
import tempfile
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from coach.fuentes import captura, fps, hud_rapido  # noqa: E402

FUENTE = "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"
VERDE_ORO = (86, 232, 189)


def _fuente(tam):
    try:
        return ImageFont.truetype(FUENTE, tam)
    except OSError:
        return ImageFont.load_default()


def hud_sintetico(reloj="12:34", oro="1,234"):
    """Escritorio 4480×1440 con el reloj arriba y el oro abajo a la izquierda."""
    im = Image.new("RGB", (4480, 1440), (11, 14, 25))
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = hud_rapido.CAJAS_DEFECTO["reloj"]
    d.text((x0 + 4, y0 + 2), reloj, font=_fuente(34), fill=(240, 245, 255))
    bx0, by0, bx1, by1 = hud_rapido.CAJAS_DEFECTO["oro"]
    d.text((bx0, by0), "$" + oro, font=_fuente(30), fill=VERDE_ORO)
    return im


def main():
    fallos = 0

    def check(nombre, condicion, detalle=""):
        nonlocal fallos
        if condicion:
            print(f"  ok   {nombre}")
        else:
            print(f"  FALLA {nombre} {detalle}")
            fallos += 1

    print("hud rapido")
    im = hud_sintetico("12:34", "1,234")
    r = hud_rapido.leer(im)
    check("lee el reloj", r["t"] == 12 * 60 + 34, f"t={r['t']}")
    check("lee el oro con caja fija", r["oro"] == 1234, f"oro={r['oro']}")

    im2 = hud_sintetico("38:07", "9,801")
    r2 = hud_rapido.leer(im2)
    check("otro reloj", r2["t"] == 38 * 60 + 7, f"t={r2['t']}")
    check("otro oro", r2["oro"] == 9801, f"oro={r2['oro']}")

    # El oro se mueve 40 px a la derecha: con color configurado debe encontrarlo.
    # La banda se toma de CAJAS_DEFECTO, no escrita a mano: cuando el 2026-11-09 se
    # recalibró el HUD contra una partida real, las coordenadas fijas de aquí dejaban
    # el número viejo a la vista y el OCR leía los dos superpuestos (353000).
    im3 = hud_sintetico("21:40", "3,200")
    d = ImageDraw.Draw(im3)
    d.rectangle(list(hud_rapido.CAJAS_DEFECTO["banda_oro"]), fill=(11, 14, 25))
    d.text((hud_rapido.CAJAS_DEFECTO["oro"][0] + 40, hud_rapido.CAJAS_DEFECTO["oro"][1]),
           "$3,200", font=_fuente(30), fill=VERDE_ORO)
    r3 = hud_rapido.leer(im3, color_oro=VERDE_ORO, tolerancia=60)
    check("detecta el oro movido por color", r3["oro"] == 3200,
          f"oro={r3['oro']} caja={r3['caja_oro']}")
    check("marca que usó el color", r3["caja_oro"] == "color", r3["caja_oro"])

    # Otra resolución: las cajas se escalan.
    chico = im.resize((2240, 720), Image.LANCZOS)
    r4 = hud_rapido.leer(chico)
    check("se escala a otra resolución", r4["t"] in (12 * 60 + 34, None),
          f"t={r4['t']}")

    print("captura compartida")
    cap = captura.CapturaCompartida(ruta=os.path.join(tempfile.gettempdir(), "prueba-cap.png"))
    m = cap.metricas()
    check("métricas vacías no rompen", m["capturas"] == 0 and m["ms_mediana"] is None)
    cuadro, edad = cap.ultimo()
    check("sin capturas devuelve None", cuadro is None and edad is None)

    # Con un comando falso que copia un archivo, el hilo debe publicar cuadros.
    with tempfile.TemporaryDirectory() as tmp:
        origen = os.path.join(tmp, "origen.png")
        Image.new("RGB", (64, 48), (20, 30, 40)).save(origen)
        destino = os.path.join(tmp, "cuadro.png")
        falso = ["cp", origen]
        cap2 = captura.CapturaCompartida(ruta=destino, intervalo=0.05, comando=falso)
        cap2.arrancar()
        time.sleep(0.6)
        c, e = cap2.ultimo()
        check("el hilo publica un cuadro", c is not None and e is not None,
              f"{c is not None} {e}")
        check("cuenta capturas", cap2.metricas()["capturas"] >= 1,
              str(cap2.metricas()))
        cap2.parar()

    print("fps opcional")
    check("sin fuente devuelve None", fps.leer() is None)
    with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as f:
        f.write("basura\nrender: 141.7 fps\n")
        ruta = f.name
    try:
        fps.configurar(ruta)
        d = fps.leer()
        check("lee el último fps del log", d is not None and abs(d["fps"] - 141.7) < 0.1,
              str(d))
        fps.configurar(None)
        check("al apagar la fuente devuelve None", fps.leer() is None)
    finally:
        os.unlink(ruta)

    print()
    if fallos:
        print(f"latencia: {fallos} fallos")
        return 1
    print("latencia: OK")
    return 0


def test_suite():
    """Entrada para `pytest -q`."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
