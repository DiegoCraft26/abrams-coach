"""La partida en vivo por HTTP, sin visión y sin adivinar.

Qué resuelve: hasta hoy el reloj y el oro se leían de píxeles (OCR, plantillas) porque se
creía que una partida normal no tenía broadcast. No es así, y quedó medido el 2026-11-09:

- `GET /v1/matches/active` es el watch tab del juego: **top 200**, un catálogo, no un
  permiso. La lista de URLs en vivo (`/v1/matches/live/urls`) tenía 83 partidas, **65 de
  ellas fuera de ese top 200**: el broadcast existe, lo que está limitado es el escaparate.
- `GET /v1/matches/{match_id}/live/url` devuelve el enlace del TV de Valve para una
  partida concreta: `http://dist1-ord1.steamcontent.com/tv/<match>_<salt>`. En caché
  responde en 0.34 s; sin caché gasta 1 de los 6 espectáculos por hora sin API key.
- Con esa URL, `GET /v1/matches/demo/live/query` (SSE con SQL) entrega **las 12 filas de
  jugador en 1.2-1.4 s**: almas, oro, KDA, héroe, equipo, nivel e ítems. Ese endpoint no
  especta cuando se le pasa `broadcast_url`, así que su límite propio es 20 req/min.

Lo que NO hace: leer memoria, archivos del juego, ni el tráfico de red. Es la misma vía
que usa el cliente de espectador.

Uso:

    from coach.fuentes import live_api
    estado = live_api.instantanea(match_id=134651996, cuenta=TU_ACCOUNT_ID)
    estado["t"]          # 887.0 s de partida, del tick/64
    estado["yo"]["almas"]  # 13211, leído, no estimado
    live_api.estado_motor(match_id)   # ya en el formato que come el motor
"""
import json
import os
import threading
import time

from coach import cuota, en_vivo

BASE = en_vivo.BASE
CABECERAS = dict(en_vivo.CABECERAS)
TICKS_POR_SEGUNDO = en_vivo.TICKS_POR_SEGUNDO

# La URL del TV de una partida no cambia: deadlock-api la cachea una hora. Se cachea
# igual en memoria (y en disco) para no volver a gastar un espectáculo al reconectar.
URL_TTL_S = 3600.0
# `/v1/matches/live/urls` es gratis (100 req/s) y trae el enlace de las partidas que ya
# están en el escaparate. Se mira ANTES de espectar: lo listado se abre sin gastar nada
# de la cuota de 6/hora. Medido el 2026-11-18: 39 partidas listadas, 23 con URL.
LISTA_TTL_S = 30.0
# Con la ventana ya por encima del límite (12 peticiones para un tope de 6), esperar los
# 90 s del `next_request_in` no sirve: al expirar siguen 6 encima. Se deja drenar.
PAUSA_SATURADA_S = 1800.0
# Segundos máximos esperando filas. Medido: las 12 llegan en 1.2-1.4 s; 5 s es margen
# para una partida con la red cargada sin quedarse colgado en el hilo del panel.
SEGUNDOS_INSTANTANEA = 5.0
# Un tick trae una fila por jugador. Menos de esto no se publica: se prefiere "no lo sé"
# a un estado a medias que el motor leería como una partida de 3 jugadores.
MIN_FILAS_GRUPO = 6

_lock = threading.Lock()
_cache_url = {}          # match_id -> (url, ts)
_sin_cuota = {}          # match_id -> ts del 429: no se vuelve a pedir esa partida
_cache_lista = {"ts": 0.0, "urls": {}}   # escaparate `/live/urls` cacheado
# La caché de URLs vive también en disco. Sin ella, cerrar y abrir el coach durante una
# partida gastaba otro espectáculo de los 6/hora por cada arranque: seis reaperturas y
# la partida se quedaba sin broadcast (que es justo lo que Diego pidió no romper nunca).
RUTA_CACHE_URL = os.path.expanduser(os.environ.get(
    "ABRAMS_CACHE_URL", "~/.cache/abrams-coach/urls_broadcast.json"))
# Las partidas que la API ya nos negó por cuota también se recuerdan en disco: si el
# coach se reinicia en mitad de un 429, no vuelve a pedir el espectáculo de la misma
# partida (cada intento suma otra petición a la ventana de 6/hora).
RUTA_NEGADAS = os.path.expanduser(os.environ.get(
    "ABRAMS_CUOTA_NEGADAS", "~/.cache/abrams-coach/sin_cuota.json"))
NEGADA_TTL_S = 3600.0
_metricas = {
    "urls_pedidas": 0, "urls_de_cache": 0, "urls_de_listado": 0,
    "urls_sin_cuota": 0, "urls_en_pausa": 0, "urls_cupo_local": 0,
    "consultas": 0, "fallos": 0,
    "ultima_latencia_s": None, "ultimo_error": None,
}


def _cargar_cache_url():
    """Rellena `_cache_url` desde disco. Nunca lanza: una caché rota no rompe la app."""
    try:
        with open(RUTA_CACHE_URL, encoding="utf-8") as f:
            guardado = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(guardado, dict):
        return
    ahora = time.time()
    for clave, valor in guardado.items():
        try:
            mid, url, ts = int(clave), valor[0], float(valor[1])
        except (TypeError, ValueError, IndexError):
            continue
        if isinstance(url, str) and url.startswith("http") and ahora - ts < URL_TTL_S:
            _cache_url[mid] = (url, ts)


def _guardar_cache_url():
    """Escribe la caché de forma atómica. Si falla, la app sigue igual."""
    ahora = time.time()
    vivos = {str(k): [v[0], v[1]] for k, v in _cache_url.items()
             if isinstance(v, tuple) and ahora - v[1] < URL_TTL_S}
    try:
        os.makedirs(os.path.dirname(RUTA_CACHE_URL), exist_ok=True)
        temporal = f"{RUTA_CACHE_URL}.tmp"
        with open(temporal, "w", encoding="utf-8") as f:
            json.dump(vivos, f)
        os.replace(temporal, RUTA_CACHE_URL)
    except (OSError, TypeError, ValueError):
        pass


_cargar_cache_url()


def _cargar_negadas(archivo=None):
    """Recupera las partidas sin cuota. Nunca lanza."""
    ruta = archivo or RUTA_NEGADAS
    try:
        with open(ruta, encoding="utf-8") as f:
            guardado = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(guardado, dict):
        return
    ahora = time.time()
    for clave, ts in guardado.items():
        try:
            mid, ts = int(clave), float(ts)
        except (TypeError, ValueError):
            continue
        if ahora - ts < NEGADA_TTL_S:
            _sin_cuota[mid] = ts


def _guardar_negadas(archivo=None):
    """Apunta en disco qué partidas ya dijeron que no. Si falla, la app sigue igual."""
    ruta = archivo or RUTA_NEGADAS
    ahora = time.time()
    vivos = {str(k): v for k, v in _sin_cuota.items()
             if ahora - v < NEGADA_TTL_S}
    try:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        temporal = f"{ruta}.tmp"
        with open(temporal, "w", encoding="utf-8") as f:
            json.dump(vivos, f)
        os.replace(temporal, ruta)
    except (OSError, TypeError, ValueError):
        pass


_cargar_negadas()


def metricas():
    """Contadores para el panel y la telemetría. Copia, no referencia."""
    with _lock:
        return dict(_metricas)


def _anotar(clave, valor=None):
    with _lock:
        if valor is None:
            _metricas[clave] += 1
        else:
            _metricas[clave] = valor


def _get_json(url, timeout=20.0):
    """GET con cabeceras propias. Devuelve el JSON o levanta con el motivo legible."""
    import urllib.error
    import urllib.request
    peticion = urllib.request.Request(url, headers=CABECERAS)
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            return json.loads(respuesta.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        cuerpo = ""
        try:
            cuerpo = exc.read().decode("utf-8", "replace")[:600]
        except Exception:                                  # noqa: BLE001
            pass
        raise ErrorApi(exc.code, cuerpo or str(exc)) from None


def cuota_de_429(detalle):
    """Los números de un 429 (`type`, `limit`, `requests`, `next_request_in`).

    Sin esto un 429 solo dice «cuota agotada» y no se puede saber si la culpa es de
    nuestro gasto (type=IP) o de la cuota global de la API (type=Global).
    """
    import re
    salida = {}
    texto = str(detalle or "")
    for clave in ("type", "limit", "period", "requests", "remaining",
                  "next_request_in"):
        m = re.search(rf'"{clave}"\s*:\s*("?)([^",}}]+)\1', texto)
        if not m:
            continue
        valor = m.group(2).strip()
        try:
            salida[clave] = int(float(valor))
        except ValueError:
            salida[clave] = valor
    return salida


class ErrorApi(Exception):
    """La API contestó algo que no es un estado: 429, 500 o un JSON inesperado."""

    def __init__(self, codigo, detalle=""):
        super().__init__(f"HTTP {codigo}: {detalle}"[:300])
        self.codigo = codigo
        self.detalle = detalle


def _apuntar(evento, match_id=None, detalle="", rechazo=False, via="api", **campos):
    """Una línea de telemetría por decisión de esta fuente. Nunca lanza."""
    try:
        from coach import telemetria
        telemetria.anotar(evento, match=match_id, via=via, rechazo=rechazo,
                          detalle=str(detalle)[:400], **campos)
    except Exception:                                      # noqa: BLE001
        pass


def urls_en_vivo(forzar=False):
    """{match_id: url} de todas las partidas con TV disponible ahora. Gratis, 100 req/s.

    Confirmado por el operador de la API (2026-11-18): este listado se puede pedir
    «however often you want», y **la llamada por partida de los ids que aparecen aquí
    tampoco cuenta** contra el límite de 6/hora, porque su URL ya está resuelta.

    Por eso el TTL es corto: refrescar es gratis y lo que se gana es ver antes una
    partida que acaba de empezar a emitir. La caché de la URL de cada partida sigue
    siendo de una hora (`URL_TTL_S`), que es lo que la propia API cachea.
    """
    ahora = time.time()
    with _lock:
        lista = _cache_lista["urls"]
        if not forzar and lista and (ahora - _cache_lista["ts"]) < LISTA_TTL_S:
            return dict(lista)
    try:
        datos = _get_json(f"{BASE}/v1/matches/live/urls")
    except Exception as exc:                               # noqa: BLE001
        _anotar("fallos")
        _anotar("ultimo_error", f"live/urls: {type(exc).__name__}: {exc}")
        return {}
    salida = {}
    for fila in datos or []:
        try:
            salida[int(fila["match_id"])] = fila["broadcast_url"]
        except (KeyError, TypeError, ValueError):
            continue
    with _lock:
        _cache_lista["urls"] = dict(salida)
        _cache_lista["ts"] = ahora
    return salida


def sin_cuota(match_id):
    """¿La API ya nos negó el espectáculo de esa partida? Entonces no se reintenta."""
    with _lock:
        return int(match_id) in _sin_cuota


def url_broadcast(match_id, forzar=False):
    """URL del TV de Valve para esa partida, o None.

    Orden deliberado (2026-11-18): primero la caché, luego el escaparate gratuito y solo
    al final el espectáculo de pago. `live/url` cuesta 1 de los 6/hora por IP y un 504
    de la API obligaba a gastarlo; con el listado delante, la mayoría de las partidas no
    cuestan nada.
    """
    mid = int(match_id)
    ahora = time.time()
    with _lock:
        guardado = _cache_url.get(mid)
    if guardado and not forzar and (ahora - guardado[1]) < URL_TTL_S:
        _anotar("urls_de_cache")
        return guardado[0]

    # Escaparate: si la partida está en `/live/urls`, su URL sale gratis.
    if not forzar:
        listadas = urls_en_vivo()
        if mid in listadas:
            with _lock:
                _cache_url[mid] = (listadas[mid], ahora)
            _guardar_cache_url()
            _anotar("urls_de_listado")
            _apuntar("api_url", mid, via="listado",
                     detalle=f"URL del listado: "
                             f"{listadas[mid].rsplit('/', 1)[-1]}")
            return listadas[mid]

    # Ya se intentó esta partida y la API dijo que no hay cuota: no se vuelve a intentar
    # mientras viva ese id. Cada intento suma otra petición a la ventana de 6/hora, así
    # que insistir no acerca la recuperación, la aleja (2026-11-18: 6 -> 9 -> 12).
    if not forzar:
        with _lock:
            negada = _sin_cuota.get(mid)
        if negada is not None:
            _anotar("urls_sin_cuota")
            _apuntar("api_url", mid, rechazo=True, codigo=429, via="recordado",
                     detalle=f"sin cuota desde {time.strftime('%H:%M:%S', time.localtime(negada))}")
            return None
        if en_vivo.pausa_restante_s() > 0:
            _anotar("urls_en_pausa")
            return None

    # `live/url` es la llamada que gasta 1 de los 6 espectáculos por hora. Tenía que
    # pasar por el cupo local y no lo hacía: el freno de `en_vivo` solo corre cuando
    # la Escucha se abre SIN url_tv, y la app siempre la abre con url_tv resuelto, así
    # que ese freno era código muerto.
    if not cuota.tomar("espectador"):
        espera = cuota.faltan_s("espectador")
        _anotar("urls_cupo_local")
        _apuntar("api_url", mid, rechazo=True, codigo=0, via="cupo_local",
                 detalle=f"cupo local agotado: {int(espera)} s")
        return None
    _anotar("urls_pedidas")
    try:
        datos = _get_json(f"{BASE}/v1/matches/{mid}/live/url")
    except ErrorApi as exc:
        _anotar("fallos")
        _anotar("ultimo_error", f"live/url {mid}: {exc}")
        datos_cuota = cuota_de_429(exc.detalle)
        espera = datos_cuota.get("next_request_in")
        if exc.codigo == 429:
            # Reintentar antes de ese instante cuenta OTRA vez contra la ventana de 6/h:
            # un reintento por minuto mantiene la cuota agotada para siempre. Se apunta
            # en la pausa compartida y se cierra el paso a esta partida.
            limite, usadas = datos_cuota.get("limit"), datos_cuota.get("requests")
            if not isinstance(espera, (int, float)):
                espera = 0
            # Si la ventana ya lleva MÁS peticiones que el límite, el `next_request_in`
            # es el de la más vieja: cuando expire, todavía habrá 6 encima y volverá a
            # fallar. Ahí no sirve esperar 90 s, hay que dejar drenar la ventana.
            if (isinstance(usadas, (int, float)) and isinstance(limite, (int, float))
                    and usadas > limite):
                espera = max(espera, PAUSA_SATURADA_S)
            if espera > 0:
                en_vivo.anotar_pausa(espera)
            with _lock:
                _sin_cuota[mid] = time.time()
            _guardar_negadas()
        _apuntar("api_url", mid, rechazo=True, codigo=exc.codigo,
                 detalle=str(exc), **datos_cuota)
        return None
    except Exception as exc:                               # noqa: BLE001
        _anotar("fallos")
        _anotar("ultimo_error", f"live/url {mid}: {type(exc).__name__}: {exc}")
        # Un fallo de red (no un HTTP con respuesta) no contó en el servidor.
        cuota.devolver("espectador")
        return None
    url = (datos or {}).get("broadcast_url")
    if not url:
        _anotar("fallos")
        _anotar("ultimo_error", f"live/url {mid}: respuesta sin broadcast_url")
        return None
    with _lock:
        _cache_url[mid] = (url, ahora)
    # A disco: si la app se reinicia a mitad de partida, no se vuelve a espectar.
    _guardar_cache_url()
    _apuntar("api_url", mid, detalle=f"URL del TV resuelta: {url.rsplit('/', 1)[-1]}")
    return url


def _lineas(url_api, timeout):
    """Generador de líneas del SSE. Aislado para poder falsearlo en las pruebas."""
    import urllib.request
    # `CABECERAS` es de otro módulo: aquí se pide el agente explícito para que
    # ningún cambio futuro deje esta ruta sin identidad (la que fue anónima era
    # justo la del watcher del live).
    peticion = urllib.request.Request(
        url_api, headers=identidad.cabeceras(Accept="text/event-stream"))
    with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
        for linea in respuesta:
            yield linea.decode("utf-8", "replace")


def _consulta(url_tv):
    import urllib.parse
    return (f"{BASE}/v1/matches/demo/live/query?"
            + urllib.parse.urlencode({"broadcast_url": url_tv, "query": en_vivo.SQL}))


def instantanea(match_id=None, url=None, cuenta=None, heroe=None,
                segundos=SEGUNDOS_INSTANTANEA):
    """Una foto del estado en vivo: lo que el motor necesita, leído y no estimado.

    Se queda con el tick que más filas trajo (una fila por jugador) y lo pasa por
    `en_vivo.interpretar`, así que el formato es el mismo que el del stream largo:
    `t`, `tick`, `jugadores`, `yo`, `aliados`, `enemigos`.

    Devuelve None si no hay URL, si la partida no está en juego o si en `segundos` no
    llegó un grupo con al menos `MIN_FILAS_GRUPO` jugadores.
    """
    arranque = time.time()
    if url is None:
        if match_id is None:
            raise ValueError("hace falta match_id o url")
        url = url_broadcast(match_id)
        if url is None:
            return None

    por_tick = {}
    error = None
    try:
        for texto in _lineas(_consulta(url), timeout=max(10.0, segundos + 5)):
            texto = texto.strip()
            if not texto.startswith("data:"):
                continue
            carga = texto[5:].strip()
            if not carga or carga == "[DONE]":
                continue
            try:
                fila = json.loads(carga)
            except json.JSONDecodeError:
                continue
            if not isinstance(fila, dict):
                continue
            # El SSE usa `data:` tanto para las filas como para los errores
            # ({"status":500,"error":"Failed to spectate match: k_eNotInGame"}).
            if fila.get("error") and fila.get("tick") is None:
                error = str(fila["error"])[:200]
                break
            if fila.get("tick") is None:
                continue
            por_tick.setdefault(int(fila["tick"]), []).append(fila)
            # Tres ticks bastan para saber cuál es el último COMPLETO: el que llega
            # mientras se lee puede estar a medias (una fila por jugador, no todas).
            if len(por_tick) >= 3:
                break
            if time.time() - arranque > segundos:
                break
    except Exception as exc:                               # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    finally:
        latencia = round(time.time() - arranque, 2)
        _anotar("consultas")
        _anotar("ultima_latencia_s", latencia)
        if error:
            _anotar("fallos")
            _anotar("ultimo_error", f"instantanea: {error}"[:300])

    if not por_tick:
        return None
    # El más reciente completo: se descarta el último tick si trae menos filas que el
    # anterior, que es la firma de un grupo a medio decodificar.
    candidatos = dict(por_tick)
    ticks = sorted(candidatos)
    if len(ticks) > 1 and len(candidatos[ticks[-1]]) < len(candidatos[ticks[-2]]):
        candidatos.pop(ticks[-1])
    tick = max(candidatos)
    filas = candidatos[tick]
    if len(filas) < MIN_FILAS_GRUPO:
        return None
    estado = en_vivo.interpretar(filas, cuenta=cuenta,
                                 heroes=en_vivo._heroes(), heroe=heroe)
    if estado is not None:
        estado["fuente"] = "api"
        estado["latencia_api_s"] = latencia
    return estado


def estado_motor(match_id, cuenta=None, heroe=None, segundos=SEGUNDOS_INSTANTANEA):
    """Igual que `instantanea`, pero ya traducido al formato del motor."""
    from coach import nucleo_vivo
    est = instantanea(match_id=match_id, cuenta=cuenta, heroe=heroe, segundos=segundos)
    if est is None:
        return None
    salida = nucleo_vivo.estado_desde_vivo(est, cuenta)
    salida["fuente"] = "api"
    salida["notas"] = ["almas, ítems y reloj leídos del broadcast por HTTP "
                       "(sin visión, sin OCR)"]
    return salida
