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
import time
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

# Cajas por defecto para 4480×1440 con el juego en DP-2 (x=1920..4480), medidas en la
# sesión anterior: (izquierda, arriba, derecha, abajo) en coordenadas del escritorio.
# Recalibradas el 2026-11-09 con una ranked en curso: el contador de almas estaba 500 px
# a la izquierda y 200 px más abajo de donde decía la caja vieja, y el OCR leía basura.
CAJAS_DEFECTO = {
    "reloj": (3150, 8, 3265, 52),
    "banda_oro": (2480, 900, 2780, 1100),
    "oro": (2540, 958, 2720, 1012),
    "match": (4050, 1330, 4480, 1440),
}
REFERENCIA = (4480, 1440)


class MarcoPerezoso:
    """Marco sin píxeles: captura lo justo para servir las cajas que le pidan.

    Dos modos, y la diferencia se midió con el juego abierto en el menú (2026-11-15,
    GPU al 62 %):

    - **una_vez=True** (por defecto): pide el monitor del juego una sola vez (25.7 ms) y
      recorta las demás cajas en memoria (gratis).
    - **una_vez=False**: una petición por caja. Con el compositor ocupado cada una cuesta
      ~33 ms —más que el monitor entero, porque se espera al siguiente cuadro— así que
      leer reloj y oro costaba ~66 ms por ciclo.

    Con el juego cerrado el readback es tan barato (0.9–2.5 ms) que los dos modos daban
    igual y por eso el problema solo apareció al medir con el juego vivo.

    Sustituye al cuadro real sin cambiar a los lectores: solo necesitan `.crop(caja)`.
    """

    def __init__(self, capturador=None, tamano=REFERENCIA, una_vez=None, caja=None):
        self._capturar = capturador or _capturar_caja
        self._cuadro = None
        self._origen = (0, 0)
        # Con un capturador inyectado (pruebas) se respeta caja por caja; el modo de una
        # sola captura solo aplica cuando el marco captura de verdad.
        self._una_vez = (capturador is None) if una_vez is None else bool(una_vez)
        self._caja = caja
        self.size = tamano
        self.capturas = 0
        self.errores = 0

    def crop(self, caja):
        if self._una_vez:
            if self._cuadro is None:
                self._cuadro, self._origen = _capturar_monitor(self._caja)
                if self._cuadro is not None:
                    self.capturas += 1
            if self._cuadro is not None:
                # Las cajas vienen en coordenadas del escritorio; el cuadro es el
                # monitor, así que hay que descontar su origen.
                ox, oy = self._origen
                return self._cuadro.crop((caja[0] - ox, caja[1] - oy,
                                          caja[2] - ox, caja[3] - oy))
            # Si el monitor entero no se pudo, se cae a pedir la caja suelta.
        im = self._capturar(caja)
        if im is None:
            self.errores += 1
            raise OSError("KWin no entregó la caja")
        self.capturas += 1
        return im

    def metricas(self):
        return {"capturas": self.capturas, "errores": self.errores}


def _capturar_caja(caja):
    """PIL de esa caja del escritorio por KWin, o None."""
    try:
        from . import captura_kwin
        x0, y0, x1, y1 = (int(v) for v in caja)
        return captura_kwin.capturar(x0, y0, max(1, x1 - x0), max(1, y1 - y0))
    except Exception:                                     # noqa: BLE001
        return None


def _capturar_monitor(caja=None):
    """(PIL del monitor del juego, (x0, y0)), o (None, (0, 0))."""
    try:
        from . import captura_bajo_demanda as cbd, captura_kwin
        caja = caja or cbd.caja_juego()
        if not caja:
            return None, (0, 0)
        im = captura_kwin.capturar(caja[0], caja[1], caja[2], caja[3])
        return (im, (caja[0], caja[1])) if im is not None else (None, (0, 0))
    except Exception:                                     # noqa: BLE001
        return None, (0, 0)


def _escalar(caja, tamano):
    """Reescala una caja de la referencia al tamaño real del cuadro."""
    fx = tamano[0] / REFERENCIA[0]
    fy = tamano[1] / REFERENCIA[1]
    return (int(caja[0] * fx), int(caja[1] * fy), int(caja[2] * fx), int(caja[3] * fy))


def _otsu(recorte):
    """Umbral que mejor separa tinta de fondo en ESE recorte (Otsu).

    Un umbral fijo no sirve: con el mismo HUD, el contador de almas se lee bien a 110
    en un cuadro y solo a 140 en otro, porque el brillo del borde cambia con la escena.
    Otsu lo calcula por recorte, así la lectura no depende de acertar la constante.
    """
    hist = recorte.histogram()
    total = sum(hist)
    if not total:
        return 140
    suma = sum(i * h for i, h in enumerate(hist))
    peso_fondo = 0
    suma_fondo = 0
    mejor, umbral = -1.0, 140
    for i, h in enumerate(hist):
        peso_fondo += h
        if not peso_fondo:
            continue
        peso_frente = total - peso_fondo
        if not peso_frente:
            break
        suma_fondo += i * h
        media_fondo = suma_fondo / peso_fondo
        media_frente = (suma - suma_fondo) / peso_frente
        varianza = peso_fondo * peso_frente * (media_fondo - media_frente) ** 2
        if varianza > mejor:
            mejor, umbral = varianza, i
    return umbral


def _ocr(imagen, caja, escala=6, whitelist="0123456789:", psm="7", umbral=140):
    """OCR de un recorte con el preprocesado que se midió como mejor (130 ms/12 números).

    Antes era `autocontrast` + `invert`, y contra el HUD real del juego fallaba: el reloj
    salía vacío o como «7 5» (medido el 2026-11-09 con la partida abierta). Con un umbral
    sobre el brillo el mismo recorte lee «9:15» sin error. El texto del HUD es blanco
    sobre fondo oscuro, así que no hay que invertir. Con `umbral=None` se usa Otsu.
    """
    recorte = imagen.crop(caja).convert("L")   # spectacle entrega RGBA
    recorte = recorte.resize((recorte.width * escala, recorte.height * escala),
                             Image.LANCZOS)
    corte = _otsu(recorte) if umbral is None else umbral
    recorte = recorte.point(lambda p: 255 if p > corte else 0)
    # Archivo ÚNICO por llamada: el reloj y el oro se leen en paralelo y, compartiendo
    # nombre, una hebra pisaba la imagen de la otra (leía 3,807 donde decía 9,801).
    fd, ruta = tempfile.mkstemp(prefix="abrams-hud-", suffix=".png")
    os.close(fd)
    try:
        recorte.save(ruta)
        salida = subprocess.run(
            ["tesseract", ruta, "stdout", "--psm", psm,
             "-c", f"tessedit_char_whitelist={whitelist}"],
            capture_output=True, text=True, timeout=10).stdout
    finally:
        try:
            os.unlink(ruta)
        except OSError:
            pass
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
        # La caja recorta solo la línea del número grande (la de «| 1789» queda fuera),
        # así que el último número del recorte es el bueno.
        numeros = re.findall(r"\d[\d,]*", texto)
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
