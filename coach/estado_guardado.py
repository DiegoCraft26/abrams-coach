"""El último estado bueno del coach, guardado en disco.

Si el coach se cae o se reinicia, el panel se quedaba sin nada que enseñar y decía «sin
respuesta». Lo que se sabe de la partida no cambia por unos segundos de caída: se guarda
el último estado publicado y se sirve con su edad, diciendo de dónde viene. Nunca se
presenta como fresco.

El archivo vive en `salida/` (ignorado por git) y se escribe de forma atómica: si el
proceso muere a media escritura, el archivo anterior sigue entero.
"""
import json
import os
import tempfile
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA = os.path.join(RAIZ, "salida", "estado_ultimo.json")

# El coach publica cada pocos segundos; escribir en cada vuelta sería castigar el disco
# para guardar el mismo estado. Con 2 s ya se salva una partida que se cae.
INTERVALO_GUARDADO_S = 2.0
_ultimo_guardado = 0.0


def guardar(datos, ruta=None, forzar=False):
    """Guarda el estado si pasó el intervalo (o si `forzar`). Devuelve True si escribió.

    Acepta cualquier dict; lo que no sea dict se ignora en silencio: el respaldo no debe
    romper el bucle que sí funciona.
    """
    global _ultimo_guardado
    if not isinstance(datos, dict):
        return False
    ahora = time.time()
    if not forzar and ahora - _ultimo_guardado < INTERVALO_GUARDADO_S:
        return False
    destino = ruta or RUTA
    carpeta = os.path.dirname(destino)
    try:
        os.makedirs(carpeta, exist_ok=True)
        # El JSON puede traer tipos raros (temporales, deques): `default=str` evita que
        # un detalle sin serializar tumbe el respaldo entero.
        texto = json.dumps({"ts": ahora, "datos": datos}, ensure_ascii=False, default=str)
        with tempfile.NamedTemporaryFile("w", dir=carpeta, prefix=".estado-",
                                         suffix=".tmp", delete=False,
                                         encoding="utf-8") as f:
            f.write(texto)
            temporal = f.name
        os.replace(temporal, destino)
    except (OSError, TypeError, ValueError):
        return False
    _ultimo_guardado = ahora
    return True


def cargar(ruta=None):
    """Devuelve (datos, edad_s) del último estado guardado, o (None, None).

    La edad se recalcula con el reloj de ahora: un estado de hace una hora no puede
    aparecer como recién leído.
    """
    destino = ruta or RUTA
    try:
        with open(destino, encoding="utf-8") as f:
            guardado = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None, None
    if not isinstance(guardado, dict):
        return None, None
    datos = guardado.get("datos")
    try:
        edad = max(0.0, time.time() - float(guardado.get("ts") or 0))
    except (TypeError, ValueError):
        edad = None
    if not isinstance(datos, dict):
        return None, edad
    return datos, (round(edad, 1) if edad is not None else None)


def como_respaldo(ruta=None, umbral_s=30.0):
    """Estado guardado listo para publicar, con la edad y la marca de origen.

    Devuelve None si no hay nada guardado o si ya es demasiado viejo para enseñarlo:
    preferible decir «sin datos» que mostrar una partida de anteayer.
    """
    datos, edad = cargar(ruta)
    if datos is None or edad is None or edad > umbral_s:
        return None
    respaldo = dict(datos)
    respaldo["edad_s"] = edad
    respaldo["rancio"] = True
    respaldo["origen"] = "guardado"
    if respaldo.get("mensaje"):
        respaldo["mensaje"] = f"{respaldo['mensaje']} (guardado hace {int(edad)} s)"
    return respaldo
