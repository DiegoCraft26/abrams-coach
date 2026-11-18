"""Cupo local de peticiones: el freno que no depende de lo que diga el servidor.

Por qué existe. La API de espectador permite 6 aperturas por hora e IP. El 2026-11-18
una racha de reintentos gastó la hora entera y dejó la app sin datos hasta que expirara
la ventana: el panel decía «cuota de espectador» y no había forma de jugar con él. La
pausa que devuelve un 429 sirve, pero llega **después** de gastar: cuando el contador
ya está en 6, ya perdimos.

Esto pone el freno del lado de casa: un balde de fichas persistido en disco que se
rellena a la tasa real del permiso (6/hora) y que se consulta **antes** de abrir nada.
El servidor puede mentir, el CDN puede devolver 504 y el proceso puede reiniciarse; el
balde no. Si no hay ficha, no se llama: se espera y se dice cuánto falta.

Reglas de diseño:

- Nunca lanza. Un archivo corrupto, un disco lleno o un reloj raro no pueden tumbar el
  arranque de la app; en el peor caso el balde se reinicia y se anota el fallo.
- Escritura atómica con `fsync` antes y después de `os.replace`: si el proceso muere a
  media escritura, el archivo anterior sigue entero (y no se pierde el conteo, que es
  justo lo que disparaba la racha de reintentos al reiniciar).
- Tasa y capacidad se pueden pisar por entorno (`ABRAMS_CUPO_TASA`, `ABRAMS_CUPO_MAX`)
  para auditar sin tocar código.
- `DISPONIBLE` es público y barato: la UI lo puede leer para decir «vuelvo en N s» sin
  gastar nada.

Uso:
    from coach import cuota
    if cuota.tomar("espectador"):
        abrir_stream()
    else:
        esperar(cuota.faltan_s("espectador"))
"""
import json
import os
import threading
import time

RUTA = os.path.expanduser(os.environ.get(
    "ABRAMS_CUPO", "~/.cache/abrams-coach/cupo.json"))

# Un permiso por nombre: capacidad (fichas de golpe) y tasa de recarga por hora.
PERMISOS = {
    # 6 espectáculos/hora por IP es el límite publicado; 2 de golpe permiten recuperar
    # un corte sin agotar la hora de una sola vez.
    "espectador": {"capacidad": 2.0, "por_hora": 6.0},
    # Las consultas normales (no espectan) ya las limita la puerta de 3 s de
    # `en_vivo._esperar_turno`, que es exactamente el 20/min publicado. Aquí solo va
    # el permiso que se gasta con un recurso escaso y persistente.
}

_lock = threading.Lock()
_baldes = {}
_cargado = False
_ultimo_fallo = None       # último error de escritura, para el diagnóstico


def _ajuste(nombre):
    """Capacidad y tasa del permiso, con override por entorno para auditar."""
    base = dict(PERMISOS.get(nombre) or {"capacidad": 1.0, "por_hora": 60.0})
    prefijo = f"ABRAMS_CUPO_{nombre.upper()}"
    try:
        if os.environ.get(prefijo + "_MAX"):
            base["capacidad"] = float(os.environ[prefijo + "_MAX"])
        if os.environ.get(prefijo + "_TASA"):
            base["por_hora"] = float(os.environ[prefijo + "_TASA"])
    except (TypeError, ValueError):
        pass
    return base


def _recargar(balde, ahora):
    """Rellena el balde según el tiempo pasado. Devuelve las fichas resultantes."""
    ajuste = _ajuste(balde["nombre"])
    capacidad = max(1.0, float(ajuste["capacidad"]))
    tasa_s = max(1e-6, float(ajuste["por_hora"]) / 3600.0)
    pasado = max(0.0, min(ahora - float(balde["ts"]), 7 * 24 * 3600.0))
    fichas = min(capacidad, float(balde["fichas"]) + pasado * tasa_s)
    balde["fichas"] = fichas
    balde["ts"] = ahora
    return fichas


def _leer_disco():
    """Carga el estado guardado una vez. Un archivo roto se ignora, no se propaga."""
    global _cargado
    if _cargado:
        return
    _cargado = True
    try:
        with open(RUTA, encoding="utf-8") as f:
            crudo = json.load(f)
    except (OSError, ValueError, TypeError):
        return
    if not isinstance(crudo, dict):
        return
    ahora = time.time()
    for nombre, datos in crudo.items():
        if not isinstance(datos, dict):
            continue
        try:
            fichas = float(datos.get("fichas", 0.0))
            ts = float(datos.get("ts", ahora))
        except (TypeError, ValueError):
            continue
        if not (0.0 <= fichas <= 1e6) or ts <= 0:
            continue
        # Un `ts` en el futuro (reloj hacia atrás, archivo tocado a mano) NO descarta
        # el balde: se recorta a ahora. Descartarlo regalaba la capacidad entera.
        if ts > ahora:
            ts = ahora
        _baldes[nombre] = {"nombre": nombre, "fichas": fichas, "ts": ts}


def _guardar_disco():
    """Escribe el estado de todos los baldes de forma atómica. Si falla, no pasa nada."""
    carpeta = os.path.dirname(RUTA)
    temporal = RUTA + ".tmp"
    try:
        os.makedirs(carpeta, exist_ok=True)
        texto = json.dumps({n: {"fichas": round(b["fichas"], 6),
                                "ts": round(b["ts"], 3)}
                            for n, b in _baldes.items()})
        with open(temporal, "w", encoding="utf-8") as f:
            f.write(texto)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporal, RUTA)
        # El rename es atómico, pero el directorio también tiene que llegar al disco o
        # un corte de luz puede dejar el archivo viejo.
        try:
            dfd = os.open(carpeta, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass
    except (OSError, TypeError, ValueError) as exc:
        # Antes se tragaba el fallo en silencio y el docstring decía que se anotaba:
        # un directorio sin permiso de escritura reiniciaba el balde a capacidad
        # completa en cada arranque.
        global _ultimo_fallo
        _ultimo_fallo = f"{type(exc).__name__}: {exc}"[:200]
        try:
            os.unlink(temporal)
        except OSError:
            pass


def _balde(nombre):
    _leer_disco()
    balde = _baldes.get(nombre)
    if balde is None:
        balde = {"nombre": nombre, "fichas": _ajuste(nombre)["capacidad"],
                 "ts": time.time()}
        _baldes[nombre] = balde
    return balde


def disponible(nombre="espectador"):
    """Fichas disponibles ahora, sin consumir ninguna."""
    with _lock:
        return _recargar(_balde(nombre), time.time())


def faltan_s(nombre="espectador"):
    """Segundos hasta la próxima ficha. 0.0 si ya hay una disponible."""
    with _lock:
        balde = _balde(nombre)
        ahora = time.time()
        fichas = _recargar(balde, ahora)
        if fichas >= 1.0:
            return 0.0
        ajuste = _ajuste(nombre)
        tasa_s = max(1e-6, float(ajuste["por_hora"]) / 3600.0)
        return round(max(0.0, (1.0 - fichas) / tasa_s), 1)


def tomar(nombre="espectador"):
    """Gasta una ficha si hay. Devuelve True si se puede llamar, False si hay que esperar."""
    with _lock:
        balde = _balde(nombre)
        ahora = time.time()
        fichas = _recargar(balde, ahora)
        if fichas < 1.0:
            return False
        balde["fichas"] = fichas - 1.0
        balde["ts"] = ahora
        _guardar_disco()
        return True


def devolver(nombre="espectador"):
    """Devuelve una ficha que no se usó (la llamada falló antes de gastar cuota).

    Se usa cuando el fallo es de red y no llegó al servidor. No se pasa de la capacidad.
    """
    with _lock:
        balde = _balde(nombre)
        ahora = time.time()
        tope = max(1.0, float(_ajuste(nombre)["capacidad"]))
        balde["fichas"] = min(tope, _recargar(balde, ahora) + 1.0)
        balde["ts"] = ahora
        _guardar_disco()


def estado():
    """Foto para el diagnóstico y para arrancar limpio en las pruebas."""
    with _lock:
        ahora = time.time()
        foto = {n: {"fichas": round(_recargar(b, ahora), 3),
                    "faltan_s": round(_faltan_sin_lock(n), 1),
                    "capacidad": _ajuste(n)["capacidad"],
                    "por_hora": _ajuste(n)["por_hora"]}
                for n, b in _baldes.items()}
    if _ultimo_fallo:
        foto["_escritura"] = _ultimo_fallo
    return foto


def _faltan_sin_lock(nombre):
    balde = _baldes.get(nombre)
    if balde is None or balde["fichas"] >= 1.0:
        return 0.0
    tasa_s = max(1e-6, float(_ajuste(nombre)["por_hora"]) / 3600.0)
    return max(0.0, (1.0 - balde["fichas"]) / tasa_s)


def reiniciar(nombre=None):
    """Borra el estado en memoria y en disco. Solo para pruebas y para un reset manual."""
    global _baldes, _cargado
    with _lock:
        if nombre is None:
            _baldes = {}
        else:
            _baldes.pop(nombre, None)
        _cargado = True
        _guardar_disco()
