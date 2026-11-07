"""FPS desde fuera del juego, sin overlay y sin tocar el proceso.

Estado: **fuente opcional, apagada por defecto**. La única vía precisa que no inyecta nada
es que el propio juego escriba su contador en un archivo (`cl_showfps` en la consola de
Source 2 con registro a archivo) y que esta app lo lea. Eso hay que activarlo en el juego y
está verificado solo a medias: ver `informes/investigacion-fps.md`.

Si no hay archivo configurado, `leer()` devuelve None y el panel no muestra FPS. No se
estima a partir de la utilización de la GPU: eso mide motores ocupados, no cuadros.
"""
import os
import re
import time

_RUTA = {"valor": None, "ts": 0.0, "ultimo_fps": None, "ultimo_ts": 0.0}


def configurar(ruta):
    """Ruta del log del juego donde aparezcan los FPS (o None para apagar)."""
    _RUTA["valor"] = ruta or None


def leer(max_edad_s=5.0):
    """Último FPS escrito en el log, o None si no hay fuente o el dato está viejo."""
    ruta = _RUTA["valor"]
    if not ruta or not os.path.exists(ruta):
        return None
    try:
        if os.path.getmtime(ruta) == _RUTA["ts"]:
            edad = time.time() - _RUTA["ultimo_ts"]
            if _RUTA["ultimo_fps"] is None or edad > max_edad_s:
                return None
            return {"fps": _RUTA["ultimo_fps"], "edad_s": round(edad, 2)}
        # solo la cola del archivo: estos logs crecen rápido
        with open(ruta, "rb") as f:
            f.seek(0, os.SEEK_END)
            tam = f.tell()
            f.seek(max(0, tam - 8192))
            texto = f.read().decode("utf-8", "ignore")
        numeros = re.findall(r"(\d{2,4}(?:\.\d+)?)\s*fps", texto, re.IGNORECASE)
        if not numeros:
            numeros = re.findall(r"\bfps[:\s]+(\d{2,4}(?:\.\d+)?)", texto, re.IGNORECASE)
        if not numeros:
            return None
        _RUTA.update({"ts": os.path.getmtime(ruta), "ultimo_fps": float(numeros[-1]),
                      "ultimo_ts": time.time()})
        return {"fps": _RUTA["ultimo_fps"], "edad_s": 0.0}
    except OSError:
        return None
