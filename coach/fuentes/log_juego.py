"""Fase de la partida leída del console.log del juego (`-condebug`).

No sustituye al HUD ni al broadcast: sirve para saber **si hay partida** y con qué
héroe, sin capturar la pantalla ni gastar API. Cuando el log no existe (juego sin
`-condebug`), todo esto queda en `None` y la app sigue como antes.
"""
import os
import re
import time

RUTA = os.path.expanduser(
    "~/.local/share/Steam/steamapps/common/Deadlock/game/citadel/console.log")

_FASE = re.compile(r"ChangeGameState:\s+(\w+)\s+\((\d+)\)")
_CUENTA = re.compile(r"\[U:1:(\d+)\]")
_HEROE = re.compile(r"models/heroes(?:_wip|_staging)?/(\w+)/")
_LOBBY = re.compile(r"Lobby\s+(\d+)\s+for\s+Match\s+(\d+)\s+created")
# El mapa que el juego acaba de cargar. Es la señal que distingue una partida de verdad
# del hideout: el menú también pasa por HeroSelection y GameInProgress, así que la fase
# sola mentía (el panel decía «en partida» con Diego en el menú, 2026-11-15).
_MAPA = re.compile(r"Host activate: Loading \((\w+)\)")
# El juego escribe esto al cerrarse. Sin esta señal, el panel seguía diciendo «en partida»
# hasta que el log cumplía 90 s: el cierre es inmediato y se sabe.
_CIERRE = "Source2Shutdown"

_cache = {"mtime": None, "size": None, "pos": 0, "fase": None, "cuenta": None,
          "heroe": None, "lobby": None, "match": None, "mapa": None, "cerrado": False,
          "ts": 0.0}


def _leer_desde(pos, tam):
    try:
        with open(RUTA, "rb") as f:
            f.seek(pos)
            return f.read(max(0, tam - pos)).decode("utf-8", "ignore")
    except OSError:
        return None


def actualizar(force=False):
    """Lee solo lo nuevo del log (o todo la primera vez). Devuelve el estado."""
    try:
        st = os.stat(RUTA)
    except OSError:
        _cache.update({"mtime": None, "size": None, "pos": 0, "fase": None,
                       "cuenta": None, "heroe": None, "lobby": None,
                       "match": None, "mapa": None, "cerrado": False,
                       "ts": time.time()})
        return _cache
    if (not force and _cache["mtime"] == st.st_mtime
            and _cache["size"] == st.st_size):
        return _cache
    if st.st_size < _cache["pos"]:          # el juego reescribió el archivo
        _cache["pos"] = 0
        _cache.update({"fase": None, "cuenta": None, "heroe": None,
                       "lobby": None, "match": None, "mapa": None, "cerrado": False})
    inicio = _cache["pos"] if _cache["pos"] else 0
    texto = _leer_desde(inicio, st.st_size)
    if texto is None:
        return _cache
    fases = _FASE.findall(texto)
    cuentas = _CUENTA.findall(texto)
    heroes = _HEROE.findall(texto)
    lobbies = _LOBBY.findall(texto)
    mapas = _MAPA.findall(texto)
    # ¿Lo último que pasó fue el cierre del juego o un evento de partida?
    cierre = texto.rfind(_CIERRE)
    if cierre >= 0:
        evento = max(texto.rfind("ChangeGameState:"), texto.rfind("Host activate:"))
        _cache["cerrado"] = cierre > evento
    elif "ChangeGameState:" in texto or "Host activate:" in texto:
        _cache["cerrado"] = False
    _cache.update({
        "mtime": st.st_mtime, "size": st.st_size, "pos": st.st_size,
        "fase": fases[-1][0] if fases else _cache.get("fase"),
        "cuenta": int(cuentas[-1]) if cuentas else _cache.get("cuenta"),
        "heroe": heroes[-1] if heroes else _cache.get("heroe"),
        "lobby": int(lobbies[-1][0]) if lobbies else _cache.get("lobby"),
        "match": int(lobbies[-1][1]) if lobbies else _cache.get("match"),
        "mapa": mapas[-1] if mapas else _cache.get("mapa"),
        "ts": time.time(),
    })
    return _cache


def disponible():
    return os.path.exists(RUTA)


def mapa():
    """Último mapa cargado (`dl_hideout`, `dl_midtown`...), o None.

    Es la señal que de verdad separa menú de partida: el hideout del menú también pasa
    por HeroSelection y termina en `GameInProgress`, así que la fase sola decía «estás
    en partida» con el jugador en el menú (visto 2026-11-15).
    """
    return actualizar().get("mapa")


def en_menu():
    """True si el mapa cargado es el hideout del menú."""
    m = mapa()
    return bool(m) and str(m).lower().endswith("hideout")


def cerrado():
    """True si el juego se cerró después del último evento de partida."""
    return bool(actualizar().get("cerrado"))


def en_partida():
    """True solo con `GameInProgress` y un mapa que no sea el hideout."""
    if cerrado() or en_menu():
        return False
    return actualizar().get("fase") == "GameInProgress"


def fase():
    return actualizar().get("fase")


def frescura():
    """Segundos desde la última escritura del log, o None si no hay log.

    El juego escribe constantemente mientras corre (red, entrada, recursos): un log con
    minutos de antigüedad significa que el juego ya no está y que la última fase escrita
    no vale como estado actual.
    """
    try:
        return time.time() - os.path.getmtime(RUTA)
    except OSError:
        return None


def fase_fresca(max_s=90.0):
    """La fase, solo si el log se escribió hace menos de `max_s` segundos."""
    f = frescura()
    if f is None or f > max_s:
        return None
    return fase()


def estado_ui(max_s=90.0):
    """('menu' | 'partida' | None, frescura_s): lo que el panel puede afirmar sin capturar.

    `None` = no hay log o está viejo: no se sabe, y no se inventa. Estar en el menú, en
    la cola o en el hideout no es `GameInProgress`, y eso no es un error.
    """
    f = frescura()
    if f is None or f > max_s:
        return None, f
    if cerrado():
        return None, f
    if en_menu():
        return "menu", f
    return ("partida" if actualizar().get("fase") == "GameInProgress" else "menu"), f


def match_id():
    return actualizar().get("match")


def cuenta():
    return actualizar().get("cuenta")


def heroe():
    return actualizar().get("heroe")
