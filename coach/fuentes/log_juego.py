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

_cache = {"mtime": None, "size": None, "pos": 0, "fase": None, "cuenta": None,
          "heroe": None, "lobby": None, "match": None, "ts": 0.0}


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
                       "match": None, "ts": time.time()})
        return _cache
    if (not force and _cache["mtime"] == st.st_mtime
            and _cache["size"] == st.st_size):
        return _cache
    if st.st_size < _cache["pos"]:          # el juego reescribió el archivo
        _cache["pos"] = 0
        _cache.update({"fase": None, "cuenta": None, "heroe": None,
                       "lobby": None, "match": None})
    inicio = _cache["pos"] if _cache["pos"] else 0
    texto = _leer_desde(inicio, st.st_size)
    if texto is None:
        return _cache
    fases = _FASE.findall(texto)
    cuentas = _CUENTA.findall(texto)
    heroes = _HEROE.findall(texto)
    lobbies = _LOBBY.findall(texto)
    _cache.update({
        "mtime": st.st_mtime, "size": st.st_size, "pos": st.st_size,
        "fase": fases[-1][0] if fases else _cache.get("fase"),
        "cuenta": int(cuentas[-1]) if cuentas else _cache.get("cuenta"),
        "heroe": heroes[-1] if heroes else _cache.get("heroe"),
        "lobby": int(lobbies[-1][0]) if lobbies else _cache.get("lobby"),
        "match": int(lobbies[-1][1]) if lobbies else _cache.get("match"),
        "ts": time.time(),
    })
    return _cache


def disponible():
    return os.path.exists(RUTA)


def en_partida():
    """True solo con `GameInProgress`. En menú/hideout/cola devuelve False."""
    return actualizar().get("fase") == "GameInProgress"


def fase():
    return actualizar().get("fase")


def match_id():
    return actualizar().get("match")


def cuenta():
    return actualizar().get("cuenta")


def heroe():
    return actualizar().get("heroe")
