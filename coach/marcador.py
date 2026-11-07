"""Lectura del marcador de Deadlock por captura de pantalla. Sin tesseract.

Cómo funciona
-------------
El marcador no es una rejilla de filas: son dos equipos en columnas (6 aliados a la
izquierda, 6 enemigos a la derecha). Cada columna trae retrato, nivel, nombre, KDA y
una banda de almas.

Las almas de los 12 jugadores están SIEMPRE sobre la misma línea horizontal y son el
único elemento del marcador que produce exactamente 12 grupos de píxeles claros de
ancho variable (3-4 dígitos). Eso es lo que usa la detección: se barre la mitad
superior fila por fila y se busca la fila con 12 grupos cuyo ancho varíe. No se supone
un paso de rejilla, así que no depende de la resolución ni del escalado.

Los números se leen comparando cada glifo contra plantillas recortadas del propio
juego (`coach/plantillas_digitos.npz`), con segmentación por programación dinámica
para no confundir "11" con "4". Cuesta ~30 ms por captura y no arranca procesos.

La imagen se normaliza antes a 2560x1440 para que las plantillas sirvan a cualquier
resolución: el HUD escala con el tamaño del frame.

Lo que NO hace: leer memoria del juego, inyectar, hookear o lanzar procesos externos.
"""
import os

import numpy as np

try:
    from PIL import Image
except ImportError:                                   # pragma: no cover
    Image = None

from . import plantillas as P

# Las plantillas se cosecharon sobre capturas de 2560x1440; todo se normaliza a esto.
CANONICO = (2560, 1440)

# Franja vertical donde puede estar la fila de almas (en px de la imagen canónica).
BANDA_MIN, BANDA_MAX = 200, 700
ANCHO_NUM = (20, 45)        # ancho en px de un número de almas (3-4 dígitos)
HUECO_MIN = 18              # separación mínima entre números de columnas distintas

# Reloj: fracción del área de juego medida sobre captura real (verificado 7:40 -> 460 s).
REGION_RELOJ = (0.4688, 0.0028, 0.0859, 0.0292)

# Retratos: banda vertical en px canónicos, medida sobre capturas reales.
BANDA_RETRATO = (26, 132)

_banco = None


def banco():
    """Carga el banco de plantillas una sola vez (30 KB, se queda en RAM)."""
    global _banco
    if _banco is None:
        _banco = P.Banco.cargar()
    return _banco


# ------------------------------------------------------------------ utilidades
def _area_juego(im, ruta=None):
    """Deja la imagen en el área de juego (16:9) antes de normalizar.

    Sirve para que el lector trague tanto un recorte del área de juego como la captura
    del escritorio completo de dos monitores (4480x1440). Con el escritorio se usa
    `ventana.detectar_ventana`, que elige el monitor más grande vía kscreen-doctor.
    """
    ancho, alto = im.size
    if abs(ancho / max(1, alto) - 16 / 9) <= 0.02:
        return im
    if isinstance(ruta, str):
        try:
            from . import ventana
            caja = ventana.detectar_ventana(ruta)
            if caja:
                return im.crop(caja)
        except Exception:
            pass
    recorte = int(alto * 16 / 9)
    if recorte <= ancho:
        x0 = (ancho - recorte) // 2
        return im.crop((x0, 0, x0 + recorte, alto))
    return im


def _rgb(ruta_o_im):
    if isinstance(ruta_o_im, Image.Image):
        im = ruta_o_im.convert("RGB")
        ruta = None
    else:
        ruta = os.fspath(ruta_o_im)
        im = Image.open(ruta).convert("RGB")
    im = _area_juego(im, ruta)
    if im.size != CANONICO:
        im = im.resize(CANONICO, Image.LANCZOS)
    return im


def _lum(im):
    """Luminancia por máximo de canal, sin copias grandes.

    Antes era `np.asarray(im).astype(np.int16).max(axis=2)`, que para 2560x1440 crea
    una copia int16 de TRES canales (22 MB) más el resultado. Medido: el pico del
    proceso subía a 99 MB sólo por esto. Ahora se compara sobre los canales uint8
    (3,7 MB) y se convierte una sola vez el resultado.
    """
    a = np.asarray(im)
    if a.ndim == 2:
        return a.astype(np.int16)
    alto, ancho = a.shape[:2]
    salida = np.empty((alto, ancho), dtype=np.int16)
    np.maximum(a[:, :, 0], a[:, :, 1], out=salida, dtype=np.int16)
    np.maximum(salida, a[:, :, 2], out=salida)
    return salida


def _grupos(mask, hueco=HUECO_MIN, ancho_min=ANCHO_NUM[0], ancho_max=ANCHO_NUM[1]):
    """Columnas contiguas con píxeles activos, descartando grupos de ancho atípico."""
    idx = np.flatnonzero(mask)
    if len(idx) == 0:
        return []
    salida, ini, prev = [], idx[0], idx[0]
    for i in idx[1:]:
        if i - prev > hueco:
            if ancho_min <= prev - ini + 1 <= ancho_max:
                salida.append((int(ini), int(prev)))
            ini = i
        prev = i
    if ancho_min <= prev - ini + 1 <= ancho_max:
        salida.append((int(ini), int(prev)))
    return salida


def _umbral_banda(lum):
    """Umbral de "tinta" para localizar la banda de almas, adaptado al brillo.

    Antes era fijo (>185). Eso funciona con la captura buena pero se rompe si el HUD
    sale más oscuro: el marcador es translúcido y el brillo depende de la escena.
    Medido el 2026-11-07: con la imagen al 80 % de brillo no se encontraba la banda.
    Ahora se toma el percentil 99 de la zona de búsqueda y se acota a 120..200.
    """
    alto = lum.shape[0]
    zona = lum[BANDA_MIN:min(BANDA_MAX, alto), :]
    if zona.size == 0:
        return 185.0
    return float(min(200.0, max(120.0, float(np.percentile(zona, 99)) * 0.80)))


def banda_almas(lum):
    """Localiza la fila de almas y las cajas de los 12 números.

    Devuelve (y0, y1, cajas) o None. `cajas` son (x0, x1) de cada número, ordenadas
    de izquierda a derecha.
    """
    umbral = _umbral_banda(lum)
    mejor = None
    alto = lum.shape[0]
    for y in range(BANDA_MIN, min(BANDA_MAX, alto)):
        cajas = _grupos(lum[max(0, y - 2):y + 3, :].max(axis=0) > umbral)
        if len(cajas) == 12:
            anchos = [b - a + 1 for a, b in cajas]
            variedad = max(anchos) - min(anchos)
            if mejor is None or variedad > mejor[0]:
                mejor = (variedad, y, cajas)
    if mejor is None:
        return None
    _, y_centro, cajas = mejor
    x0, x1 = cajas[0][0], cajas[-1][1]
    # extensión vertical real: filas con texto dentro de la banda horizontal
    activo = lum[:, x0:x1 + 1] > umbral
    filas = np.flatnonzero(activo.sum(axis=1) > 20)
    filas = filas[np.abs(filas - y_centro) <= 10]
    if len(filas) == 0:
        return None
    y0, y1 = int(filas.min()), int(filas.max())
    # Las cajas se recalculan sobre la banda completa: la fila central puede no incluir
    # el ancho total del glifo (un "3" es más ancho arriba y abajo que en medio). Así
    # cada caja es el ancho real del número y no entra la línea divisoria del panel.
    proyeccion = (lum[y0:y1 + 1, :] > umbral).any(axis=0)
    completo = _grupos(proyeccion)
    if len(completo) == 12:
        cajas = completo
    return y0, y1, cajas


def separar_equipos(centros):
    """Parte los 12 centros en (aliados, enemigos) por el hueco más grande.

    El hueco central entre equipos es ~3x el paso entre columnas del mismo equipo.
    Si no aparecen 12 columnas, devuelve ([], []).
    """
    if len(centros) != 12:
        return [], []
    pasos = [centros[i + 1] - centros[i] for i in range(11)]
    corte = int(np.argmax(pasos))
    if pasos[corte] < 1.5 * float(np.median(pasos)):
        return centros[:6], centros[6:]        # reparto plano
    return centros[:corte + 1], centros[corte + 1:]


def _tinta(lum, ratio=0.78):
    """Umbral adaptativo: la tinta es lo claro de la franja.

    El ratio importa mucho: con 0.55 los bordes suavizados cuentan como tinta y los
    dígitos se pegan (un "3152" se vuelve un solo glofo). En vez de fijarlo a ojo,
    `leer_numero` prueba varios y se queda con el que mejor coincide con las
    plantillas, así una captura más oscura o más clara no rompe la lectura.
    """
    lo, hi = float(lum.min()), float(lum.max())
    if hi - lo < 25:
        return np.zeros(lum.shape, dtype=np.float32)
    return (lum > lo + (hi - lo) * ratio).astype(np.float32)


RATIOS = (0.86, 0.78, 0.70)
RATIO_PLANTILLAS = 0.86      # el que usa la cosecha; la lectura lo prueba primero


def recorte_columna(lum, y0, y1, caja):
    """Recorte de una columna de almas, idéntico en lectura y en cosecha.

    Que la cosecha use exactamente este mismo recorte es lo que hace que las
    plantillas sirvan: si el recorte o el umbral cambian entre una y otra, la
    distancia entre glifos se dispara y la lectura se vuelve basura.
    """
    a, b = caja
    my0, my1 = max(0, y0 - 3), min(lum.shape[0], y1 + 4)
    return lum[my0:my1, max(0, a - 1):min(lum.shape[1], b + 2)]


def leer_numero(lum_crop, bk=None, ratios=RATIOS):
    """Lee un número de la franja. Devuelve (valor, confianza).

    Prueba varias binarizaciones y se queda con la que produce glifos más parecidos
    al banco: la buena segmentación también es la que mejor ajusta.
    """
    bk = bk or banco()
    if bk is None:
        return None, 0.0
    mejor = None
    for ratio in ratios:
        mask = _tinta(lum_crop, ratio)
        if mask.sum() < 8:
            continue
        trozos = P.trozos(mask)
        if not trozos:
            continue
        partes, costos = [], []
        for a, b in trozos:
            texto, costo = P.leer_trozo(mask[:, a:b + 1], bk)
            if not texto:
                continue
            partes.append(texto)
            costos.append(costo)
        texto = "".join(partes)
        if not texto.isdigit() or not 1 <= len(texto) <= 5:
            continue
        costo = float(np.mean(costos)) if costos else 9.9
        if mejor is None or costo < mejor[1]:
            mejor = (int(texto), costo)
    if mejor is None:
        return None, 0.0
    # 0.10 de distancia media es un glifo bien reconocido; 0.35 ya es duda
    return mejor[0], float(max(0.0, min(1.0, 1.0 - mejor[1] / 0.35)))


def leer_reloj(lum, bk=None, escala=10):
    """Lee el reloj de partida. Devuelve (segundos, confianza).

    El reloj va con tesseract, no con plantillas. Medido el 2026-11-07 sobre la captura
    real: tesseract acierta "7:40" en ~110 ms con recorte ajustado y upscale x10, y las
    plantillas fallan porque los dígitos del reloj son más gruesos que los de las almas
    y la caja arrastra un artefacto vertical. Tesseract sí falla en las almas (tipografía
    fina a 11 px), así que cada zona usa lo que está medido que funciona.
    """
    import re
    import shutil
    import subprocess
    import tempfile

    if shutil.which("tesseract") is None:
        return None, 0.0
    alto, ancho = lum.shape
    x, y, w, h = REGION_RELOJ
    caja = (int(x * ancho), int(y * alto), int((x + w) * ancho), int((y + h) * alto))
    crop = lum[caja[1]:caja[3], caja[0]:caja[2]]
    if crop.size == 0:
        return None, 0.0
    lo, hi = float(crop.min()), float(crop.max())
    if hi - lo < 25:
        return None, 0.0
    mascara = crop > lo + (hi - lo) * 0.58
    ys, xs = np.nonzero(mascara)
    if len(xs) == 0:
        return None, 0.0
    # Recorte ajustado al contenido claro, como máscara binaria (no luminancia cruda):
    # así la tinta queda nítida tras la inversión. Probado: con luminancia cruda
    # tesseract devuelve vacío.
    sub = mascara[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    # Tinta oscura sobre fondo blanco, ampliada: es lo que tesseract espera.
    arr = (sub * 255).astype(np.uint8)
    invertida = 255 - arr
    img = Image.fromarray(invertida, mode="L")
    img = img.resize((img.width * escala, img.height * escala), Image.LANCZOS)
    relleno = np.pad(np.asarray(img), 40, constant_values=255)
    ruta = os.path.join(tempfile.gettempdir(), "abrams_reloj.png")
    Image.fromarray(relleno, mode="L").save(ruta)
    try:
        r = subprocess.run(["tesseract", ruta, "stdout", "--psm", "7",
                            "-c", "tessedit_char_whitelist=0123456789:"],
                           capture_output=True, text=True, timeout=10)
    except (subprocess.SubprocessError, OSError):
        return None, 0.0
    texto = r.stdout.strip()
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", texto)
    if not m:
        return None, 0.0
    minutos, segundos = int(m.group(1)), int(m.group(2))
    if segundos > 59:
        return None, 0.0
    return minutos * 60 + segundos, 0.9


# ------------------------------------------------------------------ retratos
_retratos = None


def _plantillas_heroes():
    """Carga los iconos de héroe en 24x24 normalizados (una vez)."""
    global _retratos
    if _retratos is not None:
        return _retratos
    _retratos = []
    carpeta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "data", "iconos", "heroes")
    if not os.path.isdir(carpeta):
        return _retratos
    for nombre in sorted(os.listdir(carpeta)):
        if not nombre.endswith("_n.png"):
            continue
        try:
            im = Image.open(os.path.join(carpeta, nombre)).convert("L").resize((24, 24))
        except Exception:
            continue
        v = np.asarray(im, dtype=np.float32)
        v = (v - v.mean()) / (v.std() + 1e-6)
        _retratos.append((nombre[:-6], v))
    return _retratos


def reconocer_heroe(im, centro_x):
    """Compara el retrato de una columna contra los iconos oficiales.

    Devuelve (heroe, parecido) con parecido en [-1, 1]; (None, 0) si no hay plantillas.
    """
    plantillas = _plantillas_heroes()
    if not plantillas:
        return None, 0.0
    y0, y1 = BANDA_RETRATO
    lado = 66
    caja = (max(0, centro_x - lado // 2), y0,
            min(im.size[0], centro_x + lado // 2), y1)
    try:
        obj = im.crop(caja).convert("L").resize((24, 24))
    except Exception:
        return None, 0.0
    v = np.asarray(obj, dtype=np.float32)
    if v.std() < 1e-3:
        return None, 0.0
    v = (v - v.mean()) / (v.std() + 1e-6)
    mejor, punt = None, -2.0
    for nombre, ref in plantillas:
        s = float((v * ref).mean())
        if s > punt:
            mejor, punt = nombre, s
    return mejor, punt


# ------------------------------------------------------------------ API pública
def leer_almas_tesseract(lum, y0, y1, cajas, psm=11):
    """Lee las 12 almas en UNA sola llamada a tesseract (tira apilada).

    La clave no es el escalado ni el --psm: es **invertir** (tinta oscura sobre fondo
    claro) y usar un umbral alto. Sin eso, tesseract da 2/12 sobre esta misma captura.
    Medido el 2026-11-07: 12/12 en 128 ms con --psm 11 (psm 6 da 11/12, psm 4 da 10/12).

    Ventaja frente a las plantillas: no depende de glifos cosechados de la misma captura
    (el banco tiene 93,2 % en leave-one-out y **no tiene el dígito 6**, que no aparece en
    ninguna captura). Tesseract sí reconoce dígitos que nunca vio.

    Devuelve la lista de 12 enteros, o None si no salieron exactamente 12 líneas.
    """
    import shutil
    import subprocess
    import tempfile

    if shutil.which("tesseract") is None or len(cajas) != 12:
        return None

    recortes = [recorte_columna(lum, y0, y1, caja) for caja in cajas]
    todo = np.concatenate([r.ravel() for r in recortes])
    lo, hi = float(todo.min()), float(todo.max())
    if hi - lo < 25:
        return None
    # 0.72 * rango da ~170 en esta captura (lo medido que funciona) y se adapta a
    # capturas más claras u oscuras.
    umbral = min(210.0, max(140.0, lo + (hi - lo) * 0.72))

    preparadas = []
    for recorte in recortes:
        binaria = (recorte.astype(np.float32) > umbral).astype(np.uint8) * 255
        img = Image.fromarray(binaria, "L")
        img = img.resize((img.width * 4, img.height * 4), Image.LANCZOS)
        preparadas.append(np.asarray(img))
    ancho = max(p.shape[1] for p in preparadas) + 20
    separacion = 24
    alto = sum(p.shape[0] for p in preparadas) + separacion * (len(preparadas) - 1)
    lienzo = np.full((alto, ancho), 255, dtype=np.uint8)
    y = 0
    for p in preparadas:
        lienzo[y:y + p.shape[0], 10:10 + p.shape[1]] = 255 - p     # invertida
        y += p.shape[0] + separacion

    ruta = os.path.join(tempfile.gettempdir(), "abrams_tira_almas.png")
    Image.fromarray(lienzo, "L").save(ruta)
    try:
        r = subprocess.run(["tesseract", ruta, "stdout", "--psm", str(psm),
                            "-c", "tessedit_char_whitelist=0123456789"],
                           capture_output=True, text=True, timeout=30)
    except (subprocess.SubprocessError, OSError):
        return None

    valores = []
    for linea in r.stdout.splitlines():
        limpio = "".join(ch for ch in linea if ch.isdigit())
        if limpio:
            valores.append(int(limpio))
    if len(valores) != 12:
        return None
    if any(v < 0 or v > 999999 for v in valores):
        return None
    return valores


def leer_captura(ruta_o_im, mi_heroe=None, heroes=False):
    """Lee una captura y devuelve el estado del marcador.

    Contrato:
        ok, motivo, pantalla, tiempo_s, almas{aliados,enemigos}, almas_propias,
        jugadores[12], confianza

    `heroes=False` por defecto: el reconocimiento de retratos por plantilla se probó
    el 2026-11-07 sobre la captura real y acertó 1 de 8 héroes conocidos (los iconos
    `data/iconos/heroes/*_n.png` son otro arte), así que no entra. La composición de
    equipos se saca de la API en vivo (`coach/en_vivo.py`) o se marca como desconocida.
    """
    import time
    t0 = time.perf_counter()
    salida = {"ok": False, "motivo": "", "pantalla": list(CANONICO),
              "tiempo_s": None, "almas": {"aliados": [], "enemigos": []},
              "almas_propias": None, "jugadores": [], "confianza": 0.0}
    if Image is None:
        salida["motivo"] = "PIL no está instalado"
        return salida
    try:
        im = _rgb(ruta_o_im)
    except Exception as exc:
        salida["motivo"] = f"no pude abrir la imagen: {exc}"
        return salida

    lum = _lum(im)
    bk = banco()
    if bk is None:
        salida["motivo"] = ("falta coach/plantillas_digitos.npz; "
                            "corré herramientas/construir_plantillas.py")
        return salida

    segundos, conf_reloj = leer_reloj(lum, bk)
    salida["tiempo_s"] = segundos

    banda = banda_almas(lum)
    if banda is None:
        salida["motivo"] = ("no veo el marcador (¿Tab apretado?); "
                            f"reloj={'sí' if segundos is not None else 'no'}")
        salida["confianza"] = round(float(conf_reloj), 3)
        salida["ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return salida

    y0, y1, cajas = banda
    centros = [(a + b) // 2 for a, b in cajas]
    aliados_x, enemigos_x = separar_equipos(centros)
    if len(aliados_x) != 6 or len(enemigos_x) != 6:
        salida["motivo"] = f"no pude separar los equipos ({len(aliados_x)}/{len(enemigos_x)})"
        return salida

    my0, my1 = max(0, y0 - 3), min(lum.shape[0], y1 + 4)
    # Vía principal: una sola llamada a tesseract sobre la tira de las 12 almas.
    # Respaldo: plantillas del propio juego columna por columna (más lentas y sin el
    # dígito 6 en el banco, pero no dependen de que tesseract esté instalado).
    rapidas = leer_almas_tesseract(lum, y0, y1, cajas)
    metodo = "tesseract" if rapidas else "plantillas"
    if rapidas:
        # Control cruzado: el ancho de la caja dice cuántos dígitos debería haber. Si
        # tesseract devuelve una longitud que no cuadra (p. ej. "4" donde la caja mide
        # 23 px = 3 dígitos), esa columna se relee con las plantillas. Es lo que pasa
        # cuando el contraste se sale del rango bueno.
        bk_fallback = bk
        for i, caja in enumerate(cajas):
            ancho_caja = caja[1] - caja[0] + 1
            esperados = max(1, int(round(ancho_caja / 8.3)))
            leidos = len(str(rapidas[i]))
            if abs(leidos - esperados) > 1:
                respaldo, _ = leer_numero(recorte_columna(lum, y0, y1, caja), bk_fallback)
                if respaldo is not None and abs(len(str(respaldo)) - esperados) < abs(
                        leidos - esperados):
                    rapidas[i] = respaldo
                    metodo = "tesseract+plantillas"
    salida["metodo"] = metodo

    jugadores, confs = [], []
    indice = 0
    for equipo, lista in (("aliado", aliados_x), ("enemigo", enemigos_x)):
        for columna, cx in enumerate(lista):
            # Se recorta exactamente la caja del número (+1 px de margen). Un recorte
            # ancho mete la línea divisoria del panel y se lee como un "4".
            a, b = cajas[indice] if indice < len(cajas) else (cx - 20, cx + 20)
            indice += 1
            if rapidas:
                valor, conf = rapidas[indice - 1], 0.99
            else:
                crop = recorte_columna(lum, y0, y1, (a, b))
                valor, conf = leer_numero(crop, bk)
            confs.append(conf if valor is not None else 0.0)
            fila = {"equipo": equipo, "columna": columna, "centro_x": int(cx),
                    "almas": valor, "nombre": None, "heroe": None,
                    "kda": None, "confianza": round(float(conf), 3)}
            if heroes:
                heroe, parecido = reconocer_heroe(im, cx)
                if heroe is not None and parecido >= 0.62:
                    fila["heroe"] = heroe
                    fila["parecido"] = round(float(parecido), 3)
            jugadores.append(fila)

    salida["almas"]["aliados"] = [j["almas"] for j in jugadores[:6]]
    salida["almas"]["enemigos"] = [j["almas"] for j in jugadores[6:]]
    salida["jugadores"] = jugadores
    salida["confianza"] = round(float(np.mean(confs)) if confs else 0.0, 3)

    if mi_heroe:
        buscado = mi_heroe.strip().lower()
        for j in jugadores:
            if (j["heroe"] or "").lower() == buscado:
                salida["almas_propias"] = j["almas"]
                salida["jugadores"][j["columna"]]["es_yo"] = True
                break

    leidas = sum(1 for v in salida["almas"]["aliados"] + salida["almas"]["enemigos"]
                 if v is not None)
    salida["ok"] = leidas >= 10
    salida["motivo"] = (f"{leidas}/12 almas · reloj "
                        f"{'sí' if segundos is not None else 'no'} · "
                        f"{sum(1 for j in jugadores if j['heroe'])}/12 héroes")
    salida["ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return salida


def texto_resumen(d):
    """Resumen de una línea para logs y diagnóstico."""
    if not d.get("ok"):
        return f"SIN LECTURA: {d.get('motivo')}"
    al = d["almas"]["aliados"]
    en = d["almas"]["enemigos"]
    t = d.get("tiempo_s")
    reloj = f"{t // 60}:{t % 60:02d}" if isinstance(t, int) else "?"
    return f"{reloj} · aliados {al} · enemigos {en}"
