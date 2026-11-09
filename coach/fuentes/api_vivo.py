"""Descubrimiento de la partida en 3 capas, con presupuesto de golpes a la API.

Medido el 2026-11-08 (docs/experto/api.md):

- La caché del CDN de `matches/active` es de 120 s (stale hasta ~240 s), así que una
  partida recién empezada puede tardar minutos en aparecer y un `[]` también puede ser
  rancio. Por eso esta capa busca como máximo una vez cada 30 s y, cuando lleva tres
  respuestas vacías seguidas (90 s), repite la consulta con un parámetro de cache-bust.
- El listado global son 150 partidas y trae `account_id` por jugador: filtrar en local
  por cuenta no necesita nada más.
- `matches/live/urls` (~5.8 KB) dice qué partidas tienen broadcast de verdad y no gasta
  cuota de espectador.
- La cuota de espectador es 6/h y el 429 trae `retry-after`: `coach.en_vivo` ya la
  respeta en una sola puerta para todas las llamadas.

Las tres capas, en orden:
  1. HUD: "MATCH: …" de la esquina inferior derecha. Cuesta una captura (`spectacle -f`,
     0.41 s y 449 KB medidos), así que se lee como mucho cada 10 s. No depende de la
     nube ni de la cuota.
  2. API por cuenta: `matches/active?account_ids=<cuenta>`, 1.4 KB.
  3. Listado global: `matches/active` completo, filtrado en local por la cuenta.
"""
from __future__ import annotations

import time

from coach import en_vivo

TTL_S = 30.0             # una búsqueda cada 30 s: la caché de la API es de 120 s
CADA_HUD_S = 10.0        # cadencia máxima de la capa 1
SONDEOS_PARA_UNICO = 3   # tres vacíos seguidos (90 s) -> una consulta sin caché
# Un match_id al que se le abrió el stream y no dio un solo estado en este tiempo se
# da por muerto: se suelta en vez de devolverlo una y otra vez desde la caché.
SIN_SENAL_S = 90.0

_cache = {"match": None, "via": None, "detalle": "sin buscar", "ts": 0.0}
_hud_ts = 0.0
_vacios = 0


def _por_silencio():
    """¿El match cacheado lleva demasiado tiempo sin dar un solo estado del stream?

    Solo aplica si de verdad se le abrió el stream (si no, no hay silencio que juzgar).
    """
    match = _cache["match"]
    if not match:
        return False
    red = en_vivo.DIARIO.resumen()
    if red.get("match") != match:
        return False
    edad = red.get("edad_senal_s")
    return edad is None or edad > SIN_SENAL_S


def _guardar(match, via, detalle):
    _cache.update({"match": int(match) if match is not None else None,
                   "via": via, "detalle": detalle, "ts": time.time()})
    return dict(_cache, de_cache=False)


def _leer_hud():
    """Capa 1: 'MATCH: …' del HUD. Devuelve None si no toca leer, o si no hay HUD."""
    global _hud_ts
    ahora = time.time()
    if ahora - _hud_ts < CADA_HUD_S:
        return None
    _hud_ts = ahora
    try:
        from coach import hud
        return hud.leer_match_id()
    except Exception as exc:                                   # noqa: BLE001
        en_vivo.DIARIO.error(f"HUD: {type(exc).__name__}: {exc}")
        return None


def descubrir(cuenta=None, forzar=False, timeout=20.0, con_hud=True):
    """Busca la partida en las 3 capas y devuelve qué encontró y por dónde.

    Devuelve un dict:
        {"match": 133754270 o None, "via": "hud"|"cuenta"|"global"|None,
         "de_cache": bool, "detalle": "texto para el panel", "ts": epoch}

    Nunca lanza: si algo falla lo anota en `en_vivo.DIARIO` y sigue con la capa
    siguiente. Con `con_hud=False` se saltan la captura de pantalla. Un match cacheado
    que lleva más de 90 s sin dar un estado del stream se descarta: es la regla que
    evita quedarse clavado en la partida muerta.

        from coach.fuentes import api_vivo
        hallado = api_vivo.descubrir(cuenta=TU_STEAMID64)
        match = hallado["match"]      # None si no hay partida
    """
    ahora = time.time()
    if (not forzar and _cache["ts"] and (ahora - _cache["ts"]) < TTL_S
            and not _por_silencio()):
        return dict(_cache, de_cache=True)

    if con_hud:
        mid = _leer_hud()
        if mid:
            # El id del HUD se lee de una fuente pequeña y a veces se confunde. Si hay
            # cuenta, se contrasta con la partida que la API le asigna; si no, se
            # contrasta con la lista de partidas con retransmisión. Un id mal leído
            # enganchaba una partida inexistente y el panel se quedaba sin datos.
            if cuenta is not None:
                try:
                    de_cuenta = en_vivo.partida_activa(cuenta, timeout=timeout)
                except Exception as exc:                       # noqa: BLE001
                    de_cuenta = None
                    en_vivo.DIARIO.error(f"descubrir/hud-validar: {type(exc).__name__}: {exc}")
                if de_cuenta and int(de_cuenta) != int(mid):
                    en_vivo.DIARIO.error(
                        f"HUD {int(mid)} no coincide con la cuenta {cuenta} "
                        f"({int(de_cuenta)}); se usa la cuenta")
                    return _guardar(de_cuenta, "cuenta",
                                    f"el HUD decía {int(mid)}, pero la cuenta está en "
                                    f"{int(de_cuenta)}")
                if de_cuenta:
                    return _guardar(mid, "hud",
                                    f"match id del HUD verificado con la cuenta ({int(mid)})")
            try:
                con_broadcast = en_vivo.partidas_con_broadcast(timeout=timeout)
            except Exception as exc:                           # noqa: BLE001
                con_broadcast = set()
                en_vivo.DIARIO.error(f"descubrir/hud-urls: {type(exc).__name__}: {exc}")
            if con_broadcast and int(mid) not in con_broadcast:
                # Abrir el stream de un id que la lista no anuncia gasta una de las
                # 6 consultas/hora y termina en 429. Se descarta y se sigue con la
                # cuenta o el listado global.
                en_vivo.DIARIO.error(
                    f"HUD {int(mid)} no está en la lista de retransmisiones; "
                    f"se descarta para no gastar cuota")
            else:
                return _guardar(mid, "hud", f"match id del HUD ({int(mid)})")

    if cuenta is None:
        return _guardar(None, None, "sin cuenta: solo queda la capa del HUD")

    global _vacios
    unico = _vacios >= SONDEOS_PARA_UNICO
    try:
        match = en_vivo.partida_activa(cuenta, timeout=timeout, unico=unico)
    except Exception as exc:                                   # noqa: BLE001
        match = None
        en_vivo.DIARIO.error(f"descubrir/cuenta: {type(exc).__name__}: {exc}")
    if match:
        _vacios = 0
        return _guardar(match, "cuenta", f"la API lista la cuenta {cuenta} en {int(match)}")

    _vacios = 0 if unico else _vacios + 1
    cuco = " (consulta sin caché)" if unico else ""
    try:
        match, activas = en_vivo.buscar_en_listado(cuenta, timeout=timeout, unico=True)
    except Exception as exc:                                   # noqa: BLE001
        match, activas = None, 0
        en_vivo.DIARIO.error(f"descubrir/global: {type(exc).__name__}: {exc}")
    if match:
        return _guardar(match, "global",
                        f"la cuenta {cuenta} aparece en el listado global ({activas} partidas)")
    return _guardar(None, None,
                    f"la cuenta {cuenta} no está en ningún listado{cuco} "
                    f"({activas} partidas activas)")


def existe_match(match, timeout=20.0):
    """¿Ese match_id sigue activo y tiene broadcast? Para el diagnóstico del panel.

    Dos golpes a la API, sin gastar cuota de espectador. Lo que no se pudo medir
    queda en None, no se adivina.
    """
    resultado = {"match": int(match), "en_listado": None, "con_broadcast": None,
                 "activas": None}
    try:
        urls = en_vivo.partidas_con_broadcast(timeout=timeout)
        if urls:
            resultado["con_broadcast"] = int(match) in urls
    except Exception as exc:                                   # noqa: BLE001
        en_vivo.DIARIO.error(f"existe_match/urls: {type(exc).__name__}: {exc}")
    try:
        partidas = en_vivo.listado_activo(timeout=timeout, unico=True)
        if partidas:
            resultado["activas"] = len(partidas)
            resultado["en_listado"] = any(
                p.get("match_id") == int(match) for p in partidas)
    except Exception as exc:                                   # noqa: BLE001
        en_vivo.DIARIO.error(f"existe_match/listado: {type(exc).__name__}: {exc}")
    return resultado


def olvidar():
    """Suelta el match cacheado para forzar un descubrimiento nuevo en la próxima."""
    _cache.update({"match": None, "via": None, "detalle": "olvidado", "ts": 0.0})


def estado():
    """Lo último que se descubrió, sin tocar la red (para logs y diagnóstico)."""
    return dict(_cache, de_cache=bool(_cache["ts"]))
