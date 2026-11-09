"""Lectura de la partida por pantalla. KDE Wayland: spectacle + tesseract + plantillas."""
import json, os, re, subprocess, tempfile, time

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
CFG = os.path.join(RAIZ, "config", "regiones.json")

# Regiones en fracciones de la pantalla completa: (x, y, ancho, alto)
DEFECTO = {
    "pantalla": {"ancho": None, "alto": None},
    "tiempo":   [0.4688, 0.0028, 0.0859, 0.0292],   # medido sobre captura real 2560x1440
    "almas":    [0.360, 0.930, 0.120, 0.045],      # pendiente de verificar en partida real
    "retrato":  [0.020, 0.905, 0.055, 0.085],
    "scoreboard": [0.140, 0.180, 0.720, 0.560],
    "heroes_col": [0.140, 0.180, 0.052, 0.560],
    "filas_total": 10,
    "mis_items": [0.355, 0.905, 0.290, 0.045],
    "mis_items_nx": 12,
    "mis_items_ny": 1,
    "slots_por_categoria": 4,
    "filas_enemigas": 4,
    "filas_aliadas": 5,
    "iconos_por_fila": 8,
}

def cargar_cfg():
    """Carga la configuración mezclando con los valores por defecto.

    Así un archivo viejo (o editado a mano a medias) nunca rompe la lectura: lo que falta
    se toma del valor por defecto.
    """
    base = dict(DEFECTO)
    if os.path.exists(CFG):
        try:
            guardado = json.load(open(CFG))
            if isinstance(guardado, dict):
                base.update({k: v for k, v in guardado.items() if v is not None})
        except Exception:
            pass
    os.makedirs(os.path.dirname(CFG), exist_ok=True)
    json.dump(base, open(CFG, "w"), indent=1)
    return base


# Opcional: si otro servicio deja un PNG fresco del escritorio, se reutiliza en vez de
# capturar otra vez. No es necesario; `spectacle`/KWin basta. Se puede cambiar con
# ABRAMS_BUFER.
BUFER_IMG = os.path.expanduser(os.environ.get("ABRAMS_BUFER", "~/.dsh/state/ultima.png"))


def capturar(destino=None, fuente="auto", edad_max=5.0, recortar=True):
    """Foto del escritorio.

    fuente="bufer": reutiliza un PNG reciente de ABRAMS_BUFER, si existe.
    fuente="spectacle": captura propia.
    fuente="auto": lo que esté más fresco.
    """
    destino = destino or os.path.join(tempfile.gettempdir(), "dl_frame.png")
    if fuente in ("auto", "bufer") and os.path.exists(BUFER_IMG):
        edad = time.time() - os.path.getmtime(BUFER_IMG)
        if edad <= edad_max:
            if os.path.abspath(destino) != os.path.abspath(BUFER_IMG):
                import shutil
                shutil.copy2(BUFER_IMG, destino)
            if recortar:
                from . import ventana
                juego = destino.replace(".png", "_juego.png")
                try:
                    ventana.recortar_juego(destino, juego)
                    return juego
                except Exception:
                    return destino
            return destino
        if fuente == "bufer":
            fuente = "spectacle"
    subprocess.run(["spectacle", "-b", "-n", "-f", "-o", destino],
                   check=True, capture_output=True, timeout=15)
    if recortar:
        from . import ventana
        juego = destino.replace(".png", "_juego.png")
        try:
            ventana.recortar_juego(destino, juego)
            return juego
        except Exception:
            return destino
    return destino


def leer_heroes(img, cfg=None):
    """Lee la columna de retratos del marcador. Devuelve la lista de 10 nombres."""
    from . import deteccion
    cfg = cfg or cargar_cfg()
    filas = cfg.get("filas_total", 10)
    rejilla = deteccion.leer_rejilla(img, cfg["heroes_col"], 1, filas,
                                     umbral=0.45, tipo="heroes")
    nombres = []
    for fila in rejilla:
        celda = fila[0]
        nombres.append(celda["id"] if celda.get("id") else None)
    return nombres


def _ocr(img, psm=7, whitelist=None):
    cmd = ["tesseract", img, "stdout", "--psm", str(psm)]
    if whitelist:
        cmd += ["-c", f"tessedit_char_whitelist={whitelist}"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    return r.stdout.strip()


def recortar(img, fraccion, destino):
    from PIL import Image
    im = Image.open(img)
    W, H = im.size
    x, y, w, h = fraccion
    caja = (int(x*W), int(y*H), int((x+w)*W), int((y+h)*H))
    im.crop(caja).resize(((caja[2]-caja[0])*3, (caja[3]-caja[1])*3)).save(destino)
    return destino


def leer_numero(img, fraccion, cfg=None):
    tmp = os.path.join(tempfile.gettempdir(), "dl_num.png")
    recortar(img, fraccion, tmp)
    txt = _ocr(tmp, psm=7, whitelist="0123456789:")
    return txt


def leer_tiempo(img, cfg=None):
    cfg = cfg or cargar_cfg()
    txt = leer_numero(img, cfg["tiempo"])
    m = re.search(r"(\d{1,2}):(\d{2})", txt)
    if m:
        return int(m.group(1))*60 + int(m.group(2)), True
    return None, False


def leer_almas(img, cfg=None):
    cfg = cfg or cargar_cfg()
    txt = leer_numero(img, cfg["almas"])
    limpio = re.sub(r"[^\d]", "", txt)
    if not limpio:
        return None, False
    return int(limpio), True


def detectar_heroe(img, cfg=None, plantillas=None):
    """Compara el retrato contra las plantillas de héroes descargadas."""
    if not plantillas:
        return None, 0.0
    from PIL import Image
    import numpy as np
    cfg = cfg or cargar_cfg()
    tmp = os.path.join(tempfile.gettempdir(), "dl_retrato.png")
    recortar(img, cfg["retrato"], tmp)
    obj = np.asarray(Image.open(tmp).convert("L"), dtype=np.float32)
    obj = (obj - obj.mean()) / (obj.std() + 1e-6)
    mejor, punt = None, -1
    for nombre, ruta in plantillas.items():
        try:
            ref = Image.open(ruta).convert("L").resize((obj.shape[1], obj.shape[0]))
        except Exception:
            continue
        r = np.asarray(ref, dtype=np.float32)
        r = (r - r.mean()) / (r.std() + 1e-6)
        punt_actual = float((obj * r).mean())
        if punt_actual > punt:
            mejor, punt = nombre, punt_actual
    return mejor, punt
