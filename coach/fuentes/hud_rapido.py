"""Lectura del HUD a alta frecuencia: reloj y oro desde el cuadro compartido.

Diferencia con `coach/hud.py`: aquel capturaba por su cuenta en cada lectura (415 ms de
`spectacle` por ciclo) y recortaba con cajas fijas. Aquí se usa el cuadro que ya capturó
`coach/fuentes/captura.py` y, para el oro, se busca el bloque por **color** dentro de una
banda antes de recortar, así el desplazamiento del HUD no rompe la lectura.

Las cajas viven en `config/coach.yaml` (sección `hud`) en coordenadas del escritorio y se
escalan según el tamaño real del cuadro. Nada de magia: si el HUD cambia, se recalibra.
"""
import os
import re
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageOps

# Cajas por defecto para 4480×1440 con el juego en DP-2 (x=1920..4480), medidas en la
# sesión anterior: (izquierda, arriba, derecha, abajo) en coordenadas del escritorio.
CAJAS_DEFECTO = {
    "reloj": (3150, 8, 3265, 52),
    "banda_oro": (1950, 1080, 2450, 1440),
    "oro": (2050, 1190, 2210, 1260),
    "match": (4050, 1330, 4480, 1440),
}
REFERENCIA = (4480, 1440)


def _escalar(caja, tamano):
    """Reescala una caja de la referencia al tamaño real del cuadro."""
    fx = tamano[0] / REFERENCIA[0]
    fy = tamano[1] / REFERENCIA[1]
    return (int(caja[0] * fx), int(caja[1] * fy), int(caja[2] * fx), int(caja[3] * fy))


def _ocr(imagen, caja, escala=6, whitelist="0123456789:", psm="7"):
    """OCR de un recorte con el preprocesado que se midió como mejor (130 ms/12 números)."""
    recorte = imagen.crop(caja).convert("L")   # spectacle entrega RGBA
    recorte = recorte.resize((recorte.width * escala, recorte.height * escala),
                             Image.LANCZOS)
    recorte = ImageOps.autocontrast(recorte)
    recorte = ImageOps.invert(recorte)
    ruta = os.path.join(tempfile.gettempdir(), "abrams-hud-ocr.png")
    recorte.save(ruta)
    salida = subprocess.run(
        ["tesseract", ruta, "stdout", "--psm", psm,
         "-c", f"tessedit_char_whitelist={whitelist}"],
        capture_output=True, text=True, timeout=10).stdout
    return salida.strip()


def _parecido(pixel, color, tolerancia):
    return all(abs(p - c) <= tolerancia for p, c in zip(pixel, color))


def detectar_bloque_oro(cuadro, banda, color=None, tolerancia=40, minimo=8):
    """Caja del número de oro dentro de la banda, buscando por color.

    Sin color configurado devuelve None y el llamador usa la caja fija: no se inventa una
    detección que no se pueda sostener.
    """
    if not color:
        return None
    zona = cuadro.crop(banda).convert("RGB")
    ancho, alto = zona.size
    pixeles = zona.load()
    xs, ys = [], []
    paso = 2                       # muestreo: 4× más rápido y sobra para un bloque grande
    for y in range(0, alto, paso):
        for x in range(0, ancho, paso):
            if _parecido(pixeles[x, y], color, tolerancia):
                xs.append(x)
                ys.append(y)
    if len(xs) < minimo:
        return None
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    if (x1 - x0) < 6 or (y1 - y0) < 6:
        return None
    margen = 6
    return (banda[0] + max(0, x0 - margen), banda[1] + max(0, y0 - margen),
            banda[0] + min(ancho, x1 + margen), banda[1] + min(alto, y1 + margen))


def leer(cuadro, cajas=None, color_oro=None, tolerancia=40):
    """Devuelve {'t', 'oro', 'ms_reloj', 'ms_oro', 'caja_oro'} y los tiempos reales."""
    cajas = {**CAJAS_DEFECTO, **(cajas or {})}
    tamano = cuadro.size
    salida = {"t": None, "oro": None, "caja_oro": "fija",
              "ms_reloj": None, "ms_oro": None}

    # Reloj y oro son dos recortes independientes: se leen en paralelo. Tesseract tarda
    # ~90 ms solo en arrancar, así que en serie el ciclo era 269 ms y en paralelo baja a
    # lo que tarda el más lento.
    def _reloj():
        t0 = time.perf_counter()
        texto = _ocr(cuadro, _escalar(cajas["reloj"], tamano), 6, "0123456789:", "7")
        m = re.search(r"(\d{1,2}):(\d{2})", texto)
        return (int(m.group(1)) * 60 + int(m.group(2)) if m else None,
                round((time.perf_counter() - t0) * 1000, 1))

    def _oro():
        t0 = time.perf_counter()
        caja = detectar_bloque_oro(cuadro, _escalar(cajas["banda_oro"], tamano),
                                   color_oro, tolerancia)
        origen = "color" if caja else "fija"
        if not caja:
            caja = _escalar(cajas["oro"], tamano)
        texto = _ocr(cuadro, caja, 4, "0123456789,", "7")
        numeros = [n for n in re.findall(r"\d[\d,]*", texto)
                   if len(n.replace(",", "")) >= 1]
        valor = None
        if numeros:
            try:
                valor = int(numeros[-1].replace(",", ""))
            except ValueError:
                valor = None
        return valor, origen, round((time.perf_counter() - t0) * 1000, 1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_reloj = pool.submit(_reloj)
        f_oro = pool.submit(_oro)
        t, ms_reloj = f_reloj.result()
        oro, origen, ms_oro = f_oro.result()

    salida.update({"t": t, "oro": oro, "caja_oro": origen,
                   "ms_reloj": ms_reloj, "ms_oro": ms_oro})
    return salida


def leer_actual(max_edad_s=2.0, cajas=None, color_oro=None):
    """Lee el último cuadro de la captura compartida, con su edad."""
    from . import captura
    cuadro, edad = captura.global_().ultimo(max_edad_s)
    if cuadro is None:
        return None
    datos = leer(cuadro, cajas, color_oro)
    datos["edad_captura_s"] = round(edad, 3) if edad is not None else None
    return datos
