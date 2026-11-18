"""Cliente de los endpoints de analítica: caché en disco y presupuesto de peticiones.

Por qué existe: `item-stats`, `item-permutation-stats`, `hero-stats` y compañía no gastan
la cuota de espectador (esa es solo de `live/url`), pero sí tienen límite propio y son
datos que **no cambian dentro del día**. Sin caché, un experimento con 25 héroes se lleva
por delante el límite y deja al coach sin poder preguntar nada durante horas.

Reglas que impone este módulo:
- una respuesta se guarda en disco y se reutiliza durante `TTL_S` (24 h por defecto);
- nunca más de una petición cada `MIN_INTERVALO_S` (1 s) entre todos los hilos;
- un tope de `MAX_POR_HORA` (120) peticiones reales por ventana móvil de una hora;
- un 429 se respeta: se apunta el `retry-after` y no se vuelve a llamar antes.

Todo se puede falsear (`transporte=`) para probarlo sin red.
"""
from __future__ import annotations
from .. import identidad

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.deadlock-api.com"
CABECERAS = {
    "User-Agent": identidad.AGENTE,
    "Accept": "application/json",
}
TTL_S = 24 * 3600
MIN_INTERVALO_S = 1.0
MAX_POR_HORA = 120

CARPETA = os.path.expanduser(os.environ.get(
    "ABRAMS_CACHE_ANALITICA", "~/.cache/abrams-coach/analitica"))
ESTADO = os.path.join(CARPETA, "_presupuesto.json")

_lock = threading.Lock()
_memoria = {}                      # url -> (datos, ts)
_estado = {"llamadas": [], "hasta": 0.0, "errores": 0, "servidas_de_cache": 0}


class PresupuestoAgotado(Exception):
    """No se puede pedir más: tope por hora o un 429 pendiente."""


def _clave(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]


def _cargar_estado():
    try:
        with open(ESTADO, encoding="utf-8") as f:
            guardado = json.load(f)
    except (OSError, ValueError):
        return
    if isinstance(guardado, dict):
        for k in ("llamadas", "hasta", "errores", "servidas_de_cache"):
            if k in guardado and isinstance(guardado[k], type(_estado[k])):
                _estado[k] = guardado[k]


def _guardar_estado():
    try:
        os.makedirs(CARPETA, exist_ok=True)
        temporal = ESTADO + ".tmp"
        with open(temporal, "w", encoding="utf-8") as f:
            json.dump(_estado, f)
        os.replace(temporal, ESTADO)
    except OSError:
        pass


def _leer_cache(url):
    ahora = time.time()
    guardado = _memoria.get(url)
    if guardado and ahora - guardado[1] < TTL_S:
        return guardado[0]
    ruta = os.path.join(CARPETA, _clave(url) + ".json")
    try:
        with open(ruta, encoding="utf-8") as f:
            envoltorio = json.load(f)
        datos, ts = envoltorio["datos"], float(envoltorio["ts"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if ahora - ts > TTL_S:
        return None
    _memoria[url] = (datos, ts)
    return datos


def _guardar_cache(url, datos):
    ahora = time.time()
    _memoria[url] = (datos, ahora)
    try:
        os.makedirs(CARPETA, exist_ok=True)
        ruta = os.path.join(CARPETA, _clave(url) + ".json")
        temporal = ruta + ".tmp"
        with open(temporal, "w", encoding="utf-8") as f:
            json.dump({"url": url, "ts": ahora, "datos": datos}, f)
        os.replace(temporal, ruta)
    except (OSError, TypeError, ValueError):
        pass


def _turno(ahora):
    """Comprueba tope por hora, respeta el `retry-after` y separa las peticiones."""
    if _estado["hasta"] > ahora:
        raise PresupuestoAgotado(
            f"la API pidió esperar {int(_estado['hasta'] - ahora)} s")
    hace_una_hora = ahora - 3600
    _estado["llamadas"] = [t for t in _estado["llamadas"] if t > hace_una_hora]
    if len(_estado["llamadas"]) >= MAX_POR_HORA:
        espera = int(_estado["llamadas"][0] + 3600 - ahora)
        raise PresupuestoAgotado(f"tope de {MAX_POR_HORA}/hora: faltan {espera} s")
    if _estado["llamadas"]:
        falta = _estado["llamadas"][-1] + MIN_INTERVALO_S - ahora
        if falta > 0:
            time.sleep(min(falta, MIN_INTERVALO_S))


def _transporte_urllib(url, timeout):
    with urllib.request.urlopen(urllib.request.Request(url, headers=CABECERAS),
                                timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def pedir(ruta, timeout=60.0, transporte=None, forzar=False, **params):
    """JSON del endpoint, de caché si se puede. Lanza PresupuestoAgotado si no toca."""
    url = BASE + ruta + ("?" + urllib.parse.urlencode(params) if params else "")
    transporte = transporte or _transporte_urllib
    with _lock:
        if not forzar:
            cacheado = _leer_cache(url)
            if cacheado is not None:
                _estado["servidas_de_cache"] += 1
                return cacheado
        _turno(time.time())
        try:
            datos = transporte(url, timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                espera = 60.0
                try:
                    espera = float(exc.headers.get("retry-after") or 60.0)
                except (TypeError, ValueError):
                    pass
                _estado["hasta"] = time.time() + espera
            _estado["errores"] += 1
            _guardar_estado()
            raise
        _estado["llamadas"].append(time.time())
        _guardar_estado()
        _guardar_cache(url, datos)
        return datos


_cargar_estado()


def presupuesto():
    """Estado del presupuesto para el panel y los informes."""
    ahora = time.time()
    con_lock = list(_estado["llamadas"])
    usadas = len([t for t in con_lock if t > ahora - 3600])
    return {"usadas_ultima_hora": usadas, "tope_por_hora": MAX_POR_HORA,
            "espera_hasta": round(max(0.0, _estado["hasta"] - ahora), 1),
            "de_cache": _estado["servidas_de_cache"], "errores": _estado["errores"],
            "carpeta": CARPETA}
