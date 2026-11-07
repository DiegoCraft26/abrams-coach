"""Herramientas puras (y testeables) del agente de compras de Deadlock.

Cada función devuelve dict serializable y nunca lanza: ante dato faltante
devuelve None en ese campo; ante error, `{"error": "..."}`.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from .proveedor import AGENTE_USUARIO, leer_credencial

BASE_API = "https://api.deadlock-api.com"
CABECERAS_API = {"User-Agent": AGENTE_USUARIO + " (Deadlock local)", "Accept": "application/json"}

# Rutas permitidas de la API pública. Todo lo demás se rechaza sin salir a red.
RUTAS_PERMITIDAS = (
    "/v1/items",
    "/v1/heroes",
    "/v1/analytics/item-stats",
    "/v1/analytics/hero-stats",
    "/v1/analytics/item-permutation-stats",
)


def _permitida(ruta: str) -> bool:
    """True si la ruta está en la lista blanca (incluye metadata de partidas)."""
    if ruta in RUTAS_PERMITIDAS:
        return True
    if ruta.startswith("/v1/matches/") and ruta.endswith("/metadata"):
        numero = ruta[len("/v1/matches/"):-len("/metadata")]
        return numero.isdigit()
    return False


def _get_json(url: str, timeout_s: float = 10):
    peticion = urllib.request.Request(url, headers=CABECERAS_API)
    with urllib.request.urlopen(peticion, timeout=timeout_s) as respuesta:
        return json.loads(respuesta.read().decode("utf-8"))


def _heroes_de(lista):
    """Nombres de héroe presentes en una lista de dicts (sin vacíos ni repetidos)."""
    nombres = []
    for jugador in lista or []:
        if not isinstance(jugador, dict):
            continue
        heroe = jugador.get("heroe")
        if heroe and heroe not in nombres:
            nombres.append(heroe)
    return nombres


def estado_actual(estado: dict) -> dict:
    """Resume tiempo, almas, oro, ítems, enemigos y compras de un estado.

    El dict de estado ya lo calculó el motor (`motor.recomendar`). No inventa
    nada: si falta un dato, el campo sale None.
    """
    try:
        if not isinstance(estado, dict):
            return {"tiempo_s": None, "almas": None, "oro": None, "items": None,
                    "enemigos": None, "compras": None, "heroe": None}
        yo = estado.get("yo") if isinstance(estado.get("yo"), dict) else {}
        enemigos = estado.get("enemigos") if isinstance(estado.get("enemigos"), list) else None
        recomendaciones = estado.get("recomendaciones")
        if isinstance(recomendaciones, list):
            compras = [r.get("nombre") for r in recomendaciones
                       if isinstance(r, dict) and r.get("nombre")]
        else:
            compras = None
        items = yo.get("items") or estado.get("inventario")
        if isinstance(items, list):
            nombres = [it.get("nombre") if isinstance(it, dict) else str(it) for it in items]
        else:
            nombres = None
        return {
            "tiempo_s": estado.get("t"),
            "almas": estado.get("almas") if estado.get("almas") is not None else yo.get("almas"),
            "oro": yo.get("oro"),
            "items": nombres,
            "enemigos": _heroes_de(enemigos) if enemigos is not None else None,
            "compras": compras,
            "heroe": yo.get("heroe"),
        }
    except Exception:
        return {"error": "estado no legible"}


def explicar_recomendacion(estado: dict) -> dict:
    """Explica la primera recomendación y deja las 2 siguientes como alternativas."""
    try:
        if not isinstance(estado, dict):
            return {"error": "sin estado"}
        recs = estado.get("recomendaciones")
        if not isinstance(recs, list) or not recs:
            return {"error": "sin recomendaciones"}
        primera = recs[0] if isinstance(recs[0], dict) else {}
        almas = estado.get("almas")
        if almas is None and isinstance(estado.get("yo"), dict):
            almas = estado["yo"].get("almas")
        costo = primera.get("costo")
        alcanza = None
        if costo is not None and almas is not None:
            alcanza = costo <= almas
        # Las alternativas van con sus propias razones y su score: si solo se manda el
        # nombre, el informe no puede explicar por qué quedaron abajo (pasó el
        # 2026-11-07 y tuvo que decir "no tengo ese desglose").
        alternativas = [
            {"nombre": r.get("nombre"), "costo": r.get("costo"),
             "score": r.get("score"), "razones": r.get("razones") or []}
            for r in recs[1:4] if isinstance(r, dict) and r.get("nombre")]
        return {
            "nombre": primera.get("nombre"),
            "costo": costo,
            "razones": primera.get("razones"),
            "score": primera.get("score"),
            "alternativas": alternativas,
            "alcanza": alcanza,
        }
    except Exception:
        return {"error": "recomendación no legible"}


def historial(db, match_id=None, limite=5) -> dict:
    """Últimas partidas o resumen de una partida desde la base SQLite.

    `db` es una conexión sqlite3 (ver `coach.persistencia.db.conectar`). Si no
    hay conexión o la BD no existe, devuelve `{"error": "sin base de datos"}`.
    """
    try:
        if db is None:
            return {"error": "sin base de datos"}
        from coach.persistencia import repos
        if match_id is not None:
            return {"resumen": repos.resumen_partida(db, match_id)}
        try:
            n = int(limite)
        except (TypeError, ValueError):
            n = 5
        return {"partidas": repos.ultimas_partidas(db, n)}
    except Exception:
        return {"error": "sin base de datos"}


def api_query(ruta: str, params: dict | None = None, timeout_s=10) -> dict:
    """GET a la API pública de Deadlock con lista blanca de rutas.

    Cualquier ruta fuera de la lista blanca devuelve `{"error": "ruta no
    permitida"}` sin tocar la red.
    """
    try:
        if not isinstance(ruta, str) or not _permitida(ruta):
            return {"error": "ruta no permitida"}
        query = urllib.parse.urlencode(params or {}, doseq=True)
        url = BASE_API + ruta + ("?" + query if query else "")
        try:
            datos = _get_json(url, timeout_s)
        except (urllib.error.URLError, OSError) as exc:
            return {"error": f"red: {type(exc).__name__}"}
        except ValueError:
            return {"error": "respuesta no es JSON"}
        return {"ruta": ruta, "datos": datos}
    except Exception:
        return {"error": "consulta no legible"}


def buscar_web(consulta: str, max_resultados=3) -> dict:
    """Busca en Tavily y devuelve título, URL y extracto de cada resultado.

    La clave (`TAVILY_API_KEY`) sale del archivo de credenciales; si falta o la
    búsqueda falla, devuelve `{"error": ...}`.
    """
    try:
        if not isinstance(consulta, str) or not consulta.strip():
            return {"error": "consulta vacía"}
        clave = leer_credencial("TAVILY_API_KEY")
        if not clave:
            return {"error": "sin credencial TAVILY_API_KEY"}
        try:
            n = int(max_resultados)
        except (TypeError, ValueError):
            n = 3
        cuerpo = {"query": consulta, "max_results": max(1, min(n, 5))}
        peticion = urllib.request.Request(
            "https://api.tavily.com/search",
            data=json.dumps(cuerpo, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "User-Agent": AGENTE_USUARIO,
                     "Authorization": "Bearer " + clave},
        )
        try:
            with urllib.request.urlopen(peticion, timeout=15) as respuesta:
                datos = json.loads(respuesta.read().decode("utf-8"))
        except (urllib.error.URLError, OSError) as exc:
            return {"error": f"red: {type(exc).__name__}"}
        except ValueError:
            return {"error": "respuesta no es JSON"}
        resultados = []
        for item in (datos.get("results") or [])[:n]:
            if not isinstance(item, dict):
                continue
            extracto = str(item.get("content") or item.get("snippet") or "")
            resultados.append({
                "titulo": item.get("title"),
                "url": item.get("url"),
                "extracto": extracto[:400],
            })
        return {"consulta": consulta, "resultados": resultados}
    except Exception:
        return {"error": "búsqueda no legible"}


ESQUEMAS = [
    {
        "type": "function",
        "function": {
            "name": "estado_actual",
            "description": "Resume tiempo, almas, oro, ítems, enemigos y compras de la partida actual.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explicar_recomendacion",
            "description": "Explica la recomendación principal del motor: por qué, cuánto cuesta, qué alternativas hay y si alcanza el oro.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "historial",
            "description": "Consulta partidas anteriores (mías) en la base local, o el resumen de una partida concreta.",
            "parameters": {
                "type": "object",
                "properties": {
                    "match_id": {"type": "integer", "description": "ID de la partida a resumir; si se omite, devuelve las últimas."},
                    "limite": {"type": "integer", "description": "Cuántas partidas recientes devolver (por defecto 5)."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "api_query",
            "description": "Consulta la API pública de Deadlock (ítems, héroes, estadísticas o metadata de una partida).",
            "parameters": {
                "type": "object",
                "properties": {
                    "ruta": {"type": "string", "description": "Ruta permitida, por ejemplo /v1/items o /v1/analytics/item-stats."},
                    "params": {"type": "object", "description": "Parámetros de la consulta como objeto."},
                },
                "required": ["ruta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_web",
            "description": "Busca información actualizada en internet (guías, parches, builds).",
            "parameters": {
                "type": "object",
                "properties": {
                    "consulta": {"type": "string", "description": "Qué buscar, por ejemplo 'mejor ítem de Abrams Deadlock'."},
                    "max_resultados": {"type": "integer", "description": "Cuántos resultados devolver (por defecto 3)."},
                },
                "required": ["consulta"],
            },
        },
    },
]
