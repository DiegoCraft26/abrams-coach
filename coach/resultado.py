"""Resultado de una partida desde la API: cierra el bucle recomendación → victoria.

Hasta ahora la app medía «parecido con lo que compran los humanos» (cobertura) y
residuales, pero no sabía si sus recomendaciones ganaban partidas: `resultados` en la
base llevaba vacío desde el principio. Esto lo llena.

Dos capas, a propósito:

  `desde_metadata(metadata, ...)` es pura: recibe el JSON ya descargado y devuelve el
  resultado. Se prueba sin red, que es lo que evita que un cambio de la API rompa la app.

  `desde_api(match_id, ...)` descarga y delega. **Nunca lanza**: si la API está caída, el
  id no existe o el JSON cambió de forma, devuelve None y quien llama decide.

No adivina de quién es la partida: si no se le pasa cuenta ni slot y hay más de un
Abrams, devuelve None. Un resultado mal atribuido es peor que no tener resultado.
"""
from __future__ import annotations
from . import identidad

import json
import urllib.request

API = "https://api.deadlock-api.com"
H = {"User-Agent": identidad.AGENTE, "Accept": "application/json"}
HEROE = 6                      # Abrams
TIMEOUT = 60


def jugador_de(match_info, cuenta=None, slot=None, heroe=HEROE):
    """El jugador observado dentro de `match_info`, o None si no se puede saber.

    Orden: cuenta explícita > slot explícito > héroe único. Con dos Abrams sin cuenta
    ni slot no hay forma honesta de elegir y se devuelve None.
    """
    if not isinstance(match_info, dict):
        return None
    jugadores = match_info.get("players") or []
    jugadores = [j for j in jugadores if isinstance(j, dict)]
    if cuenta is not None:
        for j in jugadores:
            if str(j.get("account_id")) == str(cuenta):
                return j
        return None
    if slot is not None:
        for j in jugadores:
            if str(j.get("player_slot")) == str(slot):
                return j
        return None
    candidatos = [j for j in jugadores if str(j.get("hero_id")) == str(heroe)]
    return candidatos[0] if len(candidatos) == 1 else None


def desde_metadata(metadata, cuenta=None, slot=None, heroe=HEROE, fuente="api"):
    """Resultado a partir del JSON de `/v1/matches/{id}/metadata`.

    Devuelve `{match_id, win, duracion_s, kda, fuente}` o None. `win` es 1/0 (la base
    guarda enteros), no True/False.
    """
    if not isinstance(metadata, dict):
        return None
    match_info = metadata.get("match_info") or {}
    jugador = jugador_de(match_info, cuenta, slot, heroe)
    if jugador is None:
        return None
    ganador = match_info.get("winning_team")
    equipo = jugador.get("team")
    if ganador is None or equipo is None:
        return None
    try:
        win = 1 if int(equipo) == int(ganador) else 0
    except (TypeError, ValueError):
        return None
    kills, muertes, asistencias = (jugador.get(k) or 0
                                   for k in ("kills", "deaths", "assists"))
    return {
        "match_id": match_info.get("match_id"),
        "win": win,
        "duracion_s": match_info.get("duration_s"),
        "kda": f"{kills}/{muertes}/{asistencias}",
        "fuente": fuente,
    }


def desde_api(match_id, cuenta=None, slot=None, heroe=HEROE, timeout=TIMEOUT,
              api=API):
    """Descarga el metadata y devuelve el resultado. Nunca lanza."""
    url = f"{api}/v1/matches/{int(match_id)}/metadata?include_player_info=true"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=H),
                                    timeout=timeout) as r:
            datos = json.load(r)
    except Exception:                                        # noqa: BLE001
        return None
    return desde_metadata(datos, cuenta=cuenta, slot=slot, heroe=heroe)
