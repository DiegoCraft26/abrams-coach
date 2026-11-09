"""Lectura de la tira del HUD: reloj, almas de equipo, oro e ítems en un solo cuadro.

El cuadro completo del juego a 640 px tarda ~23 s y 3 600 tokens y aún así no se lee el
reloj. Medido el 2026-11-09 con la partida en curso: el recorte del reloj a tamaño nativo
pesa 0.9 kB y se lee en **1.3 s con 314 tokens**.

De ahí esta tira: se recortan las dos zonas que importan del HUD (arriba: reloj y almas de
equipo; abajo-izquierda: oro y fila de ítems) a tamaño nativo, se apilan en una sola
imagen y se piden los cuatro números en una petición. Una lectura cuesta menos que un
cuadro completo y cabe en el ritmo del juego.

Las zonas están en fracciones del área de juego, no del escritorio.
"""
from __future__ import annotations

import io
import json

# Medidas sobre el HUD actual (2560×1440 de área de juego, captura del 2026-11-09):
#   arriba: el reloj en el centro y las dos cifras de almas de equipo a sus lados.
#   abajo:  el oro («$329 SOULS») y la rejilla de ítems del jugador.
ZONA_ARRIBA = (0.44, 0.00, 0.14, 0.08)
ZONA_ABAJO = (0.00, 0.80, 0.16, 0.18)

ANCHO_TIRA = 320
CALIDAD = 74

SISTEMA = """Lees el HUD de Deadlock. Devuelves SOLO un objeto JSON, sin explicaciones ni
markdown. Si un número no se ve con claridad, pon null: nunca lo inventes."""

PREGUNTA = """La imagen tiene dos recortes del HUD, uno encima del otro:
- ARRIBA: el reloj de la partida (M:SS) y las dos cifras de almas de los equipos.
- ABAJO: tu oro a la izquierda («$N SOULS») y la rejilla de ítems que llevas.

Devuelve exactamente:
{"reloj_s": <segundos totales o null>, "almas_equipo": <almas de tu equipo o null>,
 "oro": <oro disponible o null>, "items_visibles": <cuántos huecos tienen ítem o null>}"""

CLAVES = ("reloj_s", "almas_equipo", "oro", "items_visibles")


def _recorte(cuadro, juego, zona):
    jx, jy, jw, jh = juego
    x, y, ancho, alto = zona
    return cuadro.crop((jx + int(x * jw), jy + int(y * jh),
                        jx + int((x + ancho) * jw), jy + int((y + alto) * jh)))


def tira_hud(cuadro, juego, ancho: int = ANCHO_TIRA, calidad: int = CALIDAD) -> bytes:
    """Apila arriba+abajo en un JPEG pequeño. Es lo que se manda al modelo."""
    from PIL import Image

    arriba = _recorte(cuadro, juego, ZONA_ARRIBA)
    abajo = _recorte(cuadro, juego, ZONA_ABAJO)
    escala = ancho / max(1, abajo.width)
    alto_arriba = max(1, int(arriba.height * escala))
    alto_abajo = max(1, int(abajo.height * escala))
    arriba = arriba.resize((ancho, alto_arriba))
    abajo = abajo.resize((ancho, alto_abajo))
    tira = Image.new("RGB", (ancho, alto_arriba + alto_abajo + 2), (0, 0, 0))
    tira.paste(arriba.convert("RGB"), (0, 0))
    tira.paste(abajo.convert("RGB"), (0, alto_arriba + 2))
    salida = io.BytesIO()
    tira.save(salida, format="JPEG", quality=calidad, optimize=True)
    return salida.getvalue()


def normalizar(datos) -> dict:
    """Solo los cuatro números, con sus límites. Lo que no cuadre, null."""
    limpio = {}
    if not isinstance(datos, dict):
        return {clave: None for clave in CLAVES}
    limites = {"reloj_s": (0, 4 * 3600), "almas_equipo": (0, 500_000),
               "oro": (0, 200_000), "items_visibles": (0, 12)}
    for clave, (minimo, maximo) in limites.items():
        valor = datos.get(clave)
        if isinstance(valor, bool) or valor is None:
            limpio[clave] = None
            continue
        try:
            numero = int(float(valor))
        except (TypeError, ValueError):
            limpio[clave] = None
            continue
        limpio[clave] = numero if minimo <= numero <= maximo else None
    return limpio


def leer_jpeg(jpeg: bytes, proveedor, timeout_s: float = 35.0) -> dict | None:
    """Manda una tira ya codificada. Es lo que usa la cola (la imagen llega hecha)."""
    from . import vision

    try:
        respuesta = proveedor.chat_vision(jpeg, PREGUNTA, sistema=SISTEMA,
                                          timeout_s=timeout_s)
    except Exception:                                     # noqa: BLE001
        return None
    try:
        crudo = vision._extraer_json(vision.contenido(respuesta))
    except (ValueError, KeyError):
        return None
    datos = normalizar(crudo)
    datos["fase"] = "en_partida"      # la tira solo existe en partida
    datos["_peso_kb"] = round(len(jpeg) / 1024, 1)
    datos["_tokens"] = (respuesta.get("usage") or {}).get("total_tokens")
    return datos


def leer(cuadro, juego, proveedor, timeout_s: float = 35.0) -> dict | None:
    """Recorta, apila y lee. Devuelve los números o None si no hubo respuesta."""
    return leer_jpeg(tira_hud(cuadro, juego), proveedor, timeout_s=timeout_s)


def guardar_tira(ruta: str, cuadro, juego) -> str:
    """Deja la tira en disco: sirve para probar sin volver a gastar cuota."""
    with open(ruta, "wb") as f:
        f.write(tira_hud(cuadro, juego))
    return ruta


def como_json(datos) -> str:
    return json.dumps(datos, ensure_ascii=False)
