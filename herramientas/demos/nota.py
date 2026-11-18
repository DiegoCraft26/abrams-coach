#!/usr/bin/env python3
"""La nota de después de la partida: tres reglas, tres números, un veredicto.

Mide con el pipeline ya validado (`personal.py` sobre `consulta.py`) las tres reglas
que separan victorias de derrotas en las partidas de Abrams del dueño:

  1. primer ítem de 3 200 antes del minuto 12   ->  min3200 <= 12.0
  2. 6 muertes o menos en toda la partida       ->  muertes <= 6
  3. >= 0,40 (kills + asistencias) por minuto   ->  participacion >= 0.40

y la escribe en tres líneas: qué partida fue, qué regla se cumplió y cuál no (con su
número) y la tasa histórica de victoria del **mismo perfil**, medida sobre las 24
partidas de Abrams de `informes/lab/personal-demos.json`. La partida analizada se
excluye de esa cohorte («sin esta») para no calcular la tasa con su propio resultado.

Nada se estima: si la demo no está, la regla 1 queda «sin dato», el perfil no se
completa y no se aplica ninguna tasa. Un 404 no se rellena con la mediana de nadie.

Uso:
    python3 herramientas/demos/nota.py --match 139556523
    python3 herramientas/demos/nota.py --ultima
    python3 herramientas/demos/nota.py --ultima --json
    python3 herramientas/demos/nota.py --match 139556523 --rondas-demo 3 --espera-demo 300
    python3 herramientas/demos/nota.py --match 139556523 --sin-red

Códigos de salida: 0 nota completa · 3 nota parcial (falta la demo) · 2 sin nota
(no hay metadata, la cuenta no aparece, o no se pudo leer el historial).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
AQUI = Path(__file__).resolve().parent
if str(AQUI) not in sys.path:
    sys.path.insert(0, str(AQUI))

import consulta  # noqa: E402
import personal  # noqa: E402

API = "https://api.deadlock-api.com"
AGENTE = "abrams-coach/nota"
CUENTA = RAIZ / ".cuenta"
COHORTE = RAIZ / "informes" / "lab" / "personal-demos.json"
HEROES = RAIZ / "data" / "heroes.json"
HEROE_ABRAMS = 6
PAUSA_API = 0.5          # cortesía entre peticiones; una nota son 1-3 llamadas

# La regla, el umbral y cómo se lee en la nota. El texto y el corte salen del informe
# `PERSONAL-DEMOS-2026-11-18.md` (§5); aquí no se elige ningún umbral nuevo.
REGLAS = (
    {"clave": "min3200", "signo": "<=", "umbral": 12.0, "meta": "12:00"},
    {"clave": "muertes", "signo": "<=", "umbral": 6, "meta": "≤6"},
    {"clave": "participacion", "signo": ">=", "umbral": 0.40, "meta": "0.40"},
)
# Tasas marginales por regla, medidas en 3 538 partidas de Abrams en ranked de la
# temporada 2 (`informes/lab/REGLAS-VALIDADAS-2026-11-18.md`). Son «cumplir ESTA regla»,
# no el perfil combinado: la cohorte propia (24 partidas) es demasiado chica para decidir
# sola y sirve para saber si este perfil ya se había visto.
POBLACION = {"n": 3538, "muertes": (76.9, 36.2), "participacion": (70.9, 12.8)}
UMBRAL = {r["clave"]: r["umbral"] for r in REGLAS}
META = {r["clave"]: r["meta"] for r in REGLAS}


class SinDato(RuntimeError):
    """No hay dato, no se reintenta más y no se inventa."""


# ------------------------------------------------------------------ utilidades

def numero(valor) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)


def mmss(segundos: float) -> str:
    """Segundos -> `M:SS` (15:32), el formato del ejemplo del informe."""
    total = int(round(float(segundos)))
    return f"{total // 60}:{total % 60:02d}"


def marca(cumple: bool | None) -> str:
    return "✓" if cumple is True else "✗" if cumple is False else "?"


def nombre_heroe(heroe) -> str:
    try:
        datos = json.loads(HEROES.read_text(encoding="utf-8"))
        nombre = (datos.get(str(int(heroe))) or {}).get("nombre")
        if nombre:
            return nombre
    except (OSError, ValueError, TypeError):
        pass
    return f"Héroe {heroe}"


def _get_json(url: str, intentos: int = 3) -> dict | list:
    """GET con reintentos; 429 respeta `retry-after` y 404 no se reintenta."""
    ultimo = "sin intentos"
    for i in range(intentos):
        peticion = urllib.request.Request(
            url, headers={"User-Agent": AGENTE, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(peticion, timeout=90) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            cuerpo = e.read().decode("utf-8", "replace")[:300]
            if e.code == 404:
                raise SinDato(f"HTTP 404 en {url}") from None
            if e.code == 429:
                crudo = (e.headers.get("retry-after") or "").strip()
                espera = float(crudo) if crudo.replace(".", "", 1).isdigit() else 5.0 * (i + 1)
                ultimo = f"HTTP 429: la API pidió esperar {espera:.0f}s"
                if i < intentos - 1:
                    time.sleep(min(espera, 60.0))
                    continue
                break
            ultimo = f"HTTP {e.code}: {cuerpo}"
            if i < intentos - 1:
                time.sleep(2 * (i + 1))
                continue
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            ultimo = f"{type(e).__name__}: {e}"
            if i < intentos - 1:
                time.sleep(2 * (i + 1))
                continue
    raise SinDato(str(ultimo))


@contextmanager
def entorno(meta_dir=None, demo_dir=None, cuenta=None):
    """Apunta `personal.py` a otras carpetas/cuenta sin tocarle la firma.

    `por_partida` lee `CACHE_META`, `CACHE_DEMO` y `.cuenta` de constantes de módulo.
    Se cambian y se restauran aquí para que las pruebas usen datos fake en `tmp` y el
    CLI siga usando las cachés reales. La cuenta se pasa por archivo porque es así
    como `personal.py` la lee; se escribe uno temporal y se borra al salir.
    """
    previo = (personal.CACHE_META, personal.CACHE_DEMO, personal.CUENTA)
    temporal = None
    try:
        if meta_dir is not None:
            personal.CACHE_META = Path(meta_dir)
        if demo_dir is not None:
            personal.CACHE_DEMO = Path(demo_dir)
        if cuenta is not None:
            temporal = Path(tempfile.mkdtemp(prefix="nota-cuenta-"))
            (temporal / ".cuenta").write_text(str(int(cuenta)), encoding="utf-8")
            personal.CUENTA = temporal / ".cuenta"
        yield
    finally:
        personal.CACHE_META, personal.CACHE_DEMO, personal.CUENTA = previo
        if temporal is not None:
            shutil.rmtree(temporal, ignore_errors=True)


# ------------------------------------------------------------------- descargas

def descargar_metadata(match: int, cache_meta: Path, permitir_red: bool = True) -> dict:
    ruta = Path(cache_meta) / f"{match}.json"
    if ruta.exists():
        return {"estado": "caché", "ruta": str(ruta)}
    if not permitir_red:
        return {"estado": "sin red y sin caché", "ruta": str(ruta)}
    time.sleep(PAUSA_API)
    try:
        datos = _get_json(f"{API}/v1/matches/{match}/metadata")
    except SinDato as e:
        return {"estado": "no disponible", "detalle": str(e), "ruta": str(ruta)}
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".json.tmp")
    temporal.write_text(json.dumps(datos), encoding="utf-8")
    temporal.replace(ruta)
    return {"estado": "descargada", "ruta": str(ruta)}


def asegurar_demo(match: int, cache_demo: Path, *, permitir_red: bool = True,
                  rondas: int = 1, espera: float = 60.0, reintentos: int = 2) -> dict:
    """Deja la demo en caché o dice por qué no. Un 404 no se convierte en dato."""
    ruta = Path(cache_demo) / f"{match}__todo.ndjson"
    if ruta.exists():
        return {"estado": "caché", "ruta": str(ruta), "filas": consulta.contar_lineas(ruta)}
    if not permitir_red:
        return {"estado": "sin red y sin caché", "ruta": str(ruta)}
    _, sql = consulta.construir_sql("todo")
    rondas = max(1, int(rondas))
    fallo = "sin intentos"
    for ronda in range(rondas):
        time.sleep(PAUSA_API)
        try:
            resumen = consulta.una(match, "todo", sql, Path(cache_demo),
                                   reintentos=max(0, int(reintentos)), tope_s=300.0,
                                   callar=True)
            return {"estado": "descargada", "ruta": resumen["ruta"],
                    "filas": resumen["filas"], "segundos": resumen["segundos"]}
        except consulta.ErrorFatal as e:
            fallo = str(e)
            if ronda + 1 < rondas:
                time.sleep(espera)
        except consulta.ErrorDemo as e:
            fallo = str(e)
            if ronda + 1 < rondas:
                time.sleep(espera)
    return {"estado": "no disponible", "detalle": fallo, "ruta": str(ruta)}


def historial(cuenta: int, permitir_red: bool = True, limite: int = 50) -> list[dict]:
    """Partidas recientes de la cuenta, la más nueva primero."""
    if not permitir_red:
        raise SinDato("--ultima necesita red: el historial no está en caché")
    datos = _get_json(f"{API}/v1/players/{int(cuenta)}/match-history?limit={int(limite)}")
    if not isinstance(datos, list):
        raise SinDato(f"el historial no vino como lista: {type(datos).__name__}")
    return [m for m in datos if m.get("match_id")]


def elegir_ultima(partidas: list[dict]) -> dict:
    """La más reciente por `start_time` (el orden del API no se asume)."""
    if not partidas:
        raise SinDato("el historial vino vacío")
    return max(partidas, key=lambda m: (m.get("start_time") or 0, m.get("match_id") or 0))


# ------------------------------------------------------------------ medición

_CATALOGO = None


def _costes() -> dict[int, int]:
    """Coste de catálogo por ítem, cargado una sola vez."""
    global _CATALOGO
    if _CATALOGO is None:
        try:
            _CATALOGO = {k: v["coste"] for k, v in personal.catalogo().items()}
        except Exception:                                   # noqa: BLE001
            _CATALOGO = {}
    return _CATALOGO


def completar_desde_metadata(fila: dict, match: int, meta_dir: Path, cuenta: int) -> dict:
    """Lo que el metadata sabe y la demo no dio.

    Muertes y participación salen de aquí si `por_partida` no las puso. Y desde el
    2026-11-18 también el **minuto del primer 3 200**: el metadata trae `items[]` con
    `game_time_s`, así que la regla se puede medir aunque la demo no exista (era el caso
    más común: la demo tarda horas o nunca llega). Se marca la fuente.
    """
    if not fila or "heroe" not in fila:
        return fila
    falta_muertes = fila.get("muertes") is None
    falta_participacion = fila.get("participacion") is None
    falta_3200 = fila.get("min3200") is None
    if not (falta_muertes or falta_participacion or falta_3200):
        return fila
    try:
        meta = json.loads((Path(meta_dir) / f"{match}.json").read_text(encoding="utf-8"))
        jugadores = (meta.get("match_info") or {}).get("players") or []
        yo = next(p for p in jugadores if int(p.get("account_id") or 0) == int(cuenta))
    except (OSError, ValueError, AttributeError, StopIteration):
        return fila
    if falta_muertes:
        detalles = yo.get("death_details")
        fila["muertes"] = (len(detalles) if isinstance(detalles, list)
                           else int(yo.get("deaths") or 0))
    if falta_3200:
        items = yo.get("items")
        if isinstance(items, list) and items:
            costes = _costes()
            for it in sorted(items, key=lambda x: float(x.get("game_time_s") or 0)):
                if costes.get(int(it.get("item_id") or 0)) == 3200:
                    fila["min3200"] = round(float(it.get("game_time_s") or 0) / 60.0, 2)
                    fila["min3200_fuente"] = "metadata"
                    break
    duracion = fila.get("duracion_s") or 0
    if falta_participacion and duracion:
        fila["participacion"] = round(
            (int(yo.get("kills") or 0) + int(yo.get("assists") or 0))
            / (duracion / 60), 2)
    return fila


def medir(match: int, *, cuenta: int | None = None, meta_dir=None, demo_dir=None,
          permitir_red: bool = True, rondas_demo: int = 1, espera_demo: float = 60.0,
          reintentos: int = 2) -> dict:
    """Metadata + demo de una partida, medidos con `personal.por_partida`."""
    meta_dir = Path(meta_dir or personal.CACHE_META)
    demo_dir = Path(demo_dir or personal.CACHE_DEMO)
    with entorno(meta_dir, demo_dir, cuenta):
        try:
            efectiva = int(personal.CUENTA.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            raise SinDato(f"no se pudo leer la cuenta en {personal.CUENTA}") from None
        meta = descargar_metadata(match, meta_dir, permitir_red)
        demo = asegurar_demo(match, demo_dir, permitir_red=permitir_red,
                             rondas=rondas_demo, espera=espera_demo,
                             reintentos=reintentos)
        # `por_partida` ya distingue «demo presente» de «demo ausente» y devuelve
        # muertes y participación del metadata aunque falte la demo.
        fila = personal.por_partida(match, personal.catalogo())
        fila = completar_desde_metadata(fila, match, meta_dir, efectiva)
    return {"match_id": match, "metadata": meta, "demo": demo, "fila": fila}


def metricas_de(fila: dict | None) -> dict:
    """Las tres cifras de la nota, tal como las midió `personal.py`."""
    fila = fila or {}
    compras = fila.get("compras") or []
    segundos_3200 = next((float(c["t"]) for c in compras if c.get("coste") == 3200), None)
    min3200 = fila.get("min3200")
    if segundos_3200 is None and numero(min3200):
        segundos_3200 = float(min3200) * 60.0
    return {
        "min3200": min3200 if numero(min3200) else None,
        "min3200_s": round(segundos_3200, 1) if segundos_3200 is not None else None,
        "compras": len(compras),
        "muertes": int(fila["muertes"]) if numero(fila.get("muertes")) else None,
        "participacion": round(float(fila["participacion"]), 2)
        if numero(fila.get("participacion")) else None,
        "kills": fila.get("kills"),
        "assists": fila.get("assists"),
        "duracion_s": fila.get("duracion_s"),
    }


def _regla_3200(m: dict) -> tuple[bool | None, str]:
    if numero(m.get("min3200")):
        cumple = m["min3200"] <= UMBRAL["min3200"]
        # «Referencia», no «meta»: a escala el corte de 12 min no separa nada
        # (`informes/lab/REGLA-3200-2026-11-18.md`). Llegar tarde es señal de ir corto
        # de oro, no una palanca.
        tarde = " · tarde = señal de ir corto de oro" if m["min3200"] > 15 else ""
        texto = (f"3 200 al min {mmss(m['min3200_s'])} {marca(cumple)} "
                 f"(referencia {META['min3200']}){tarde}")
        return cumple, texto
    if m.get("compras"):
        # midió compras y ninguna costó 3 200: la regla no se cumple.
        return False, f"3 200 sin comprar ✗ (referencia {META['min3200']})"
    return None, f"3 200: sin dato (referencia {META['min3200']})"


def _regla_muertes(m: dict) -> tuple[bool | None, str]:
    if numero(m.get("muertes")):
        cumple = m["muertes"] <= UMBRAL["muertes"]
        return cumple, f"{m['muertes']} muertes {marca(cumple)} (meta {META['muertes']})"
    return None, f"muertes: sin dato (meta {META['muertes']})"


def _regla_participacion(m: dict) -> tuple[bool | None, str]:
    if numero(m.get("participacion")):
        cumple = m["participacion"] >= UMBRAL["participacion"]
        return cumple, (f"{m['participacion']:.2f} k+a/min {marca(cumple)} "
                        f"(meta {META['participacion']})")
    return None, f"k+a/min: sin dato (meta {META['participacion']})"


# --------------------------------------------------------------- la cohorte

def cargar_cohorte(ruta=None) -> list[dict]:
    """Las partidas de Abrams del dueño con las tres métricas medidas."""
    ruta = Path(ruta or COHORTE)
    if not ruta.exists():
        return []
    try:
        crudo = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    partidas = crudo.get("partidas") if isinstance(crudo, dict) else crudo
    cohorte = []
    for p in partidas or []:
        if p.get("heroe") != HEROE_ABRAMS:
            continue
        if not all(numero(p.get(k)) for k in ("min3200", "muertes", "participacion")):
            continue
        cohorte.append({"match": int(p["match"]), "gane": int(bool(p.get("gane"))),
                        "min3200": float(p["min3200"]),
                        "muertes": int(p["muertes"]),
                        "participacion": float(p["participacion"])})
    return cohorte


def _perfil_de(min3200, muertes, participacion) -> tuple:
    return (min3200 <= UMBRAL["min3200"], muertes <= UMBRAL["muertes"],
            participacion >= UMBRAL["participacion"])


def _texto_historico(n_e, v_e, pct_e, grupo, n_cohorte, sin_esta) -> str:
    cola = f" · {n_cohorte} partidas de Abrams" + (" (sin esta)" if sin_esta else "")
    part = "partida" if n_e == 1 else "partidas"
    vict = "victoria" if v_e == 1 else "victorias"
    if n_e == 0:
        cuerpo = "Histórico: sin partidas con ese perfil exacto"
    else:
        cuerpo = f"Histórico: {n_e} {part} con ese perfil → {v_e} {vict} ({pct_e} %)"
    if grupo and grupo["n"] > n_e:
        cuerpo += (f" · {grupo['reglas']}/3 reglas: {grupo['n']} partidas → "
                   f"{grupo['victorias']} ({grupo['tasa_pct']} %)")
    return cuerpo + cola


def historico(flags: tuple, cohorte: list[dict], match: int, heroe) -> dict:
    """Tasa de victoria del mismo perfil, sin contar la partida que se analiza."""
    if heroe != HEROE_ABRAMS:
        n = len(cohorte)
        texto = (f"Histórico: las 3 reglas se midieron en {n} partidas de Abrams; "
                 "este héroe no tiene cohorte, no se aplica") if n else (
                 "Histórico: sin cohorte de Abrams cargada; no se aplica")
        return {"tipo": "sin_cohorte", "n": 0, "victorias": 0, "tasa_pct": None,
                "cohorte_n": n, "texto": texto}
    faltan = [nombre for nombre, f in zip(("el 3 200", "las muertes", "la participación"),
                                          flags) if f is None]
    if faltan:
        verbo = "falta" if len(faltan) == 1 else "faltan"
        return {"tipo": "sin_perfil", "n": 0, "victorias": 0, "tasa_pct": None,
                "cohorte_n": len([c for c in cohorte if c["match"] != match]),
                "texto": (f"Histórico: sin perfil completo ({verbo} {', '.join(faltan)})"
                          " — no se aplica ninguna tasa")}

    sin_esta = any(c["match"] == match for c in cohorte)
    resto = [c for c in cohorte if c["match"] != match]
    if not resto:
        return {"tipo": "sin_cohorte", "n": 0, "victorias": 0, "tasa_pct": None,
                "cohorte_n": 0, "sin_esta": sin_esta,
                "texto": ("Histórico: sin cohorte de Abrams"
                          + (" (solo estaba esta partida)" if sin_esta else "")
                          + " — no se aplica")}
    perfil = tuple(bool(f) for f in flags)

    def de(c):
        return _perfil_de(c["min3200"], c["muertes"], c["participacion"])

    exactos = [c for c in resto if de(c) == perfil]
    n_e = len(exactos)
    v_e = sum(c["gane"] for c in exactos)
    pct_e = round(100 * v_e / n_e) if n_e else 0

    k = sum(perfil)
    grupo = [c for c in resto if sum(de(c)) == k]
    grupo_doc = None
    if grupo and len(grupo) > n_e:
        v_g = sum(c["gane"] for c in grupo)
        grupo_doc = {"reglas": k, "n": len(grupo), "victorias": v_g,
                     "tasa_pct": round(100 * v_g / len(grupo))}

    return {"tipo": "perfil", "n": n_e, "victorias": v_e, "tasa_pct": pct_e,
            "perfil": [bool(f) for f in perfil],
            "grupo": grupo_doc, "cohorte_n": len(resto), "sin_esta": sin_esta,
            "texto": _texto_historico(n_e, v_e, pct_e, grupo_doc, len(resto), sin_esta)}


# ------------------------------------------------------------------ la nota

def evaluar(match: int, fila: dict | None, cohorte: list[dict] | None = None) -> dict:
    """Convierte la fila medida en reglas cumplidas/no y en la nota de texto."""
    cohorte = cohorte or []
    fila = fila or {}
    heroe = fila.get("heroe")
    if not fila or "heroe" not in fila:
        razon = "; ".join(fila.get("no_medible") or []) or "metadata no disponible"
        nota = f"{match}: no se pudo medir — {razon}"
        return {"match_id": match, "heroe": None, "heroe_nombre": None, "gane": None,
                "duracion_s": None, "metricas": metricas_de(None), "reglas": [],
                "cumplidas": 0, "evaluadas": 0, "perfil_completo": False,
                "historico": {"tipo": "sin_dato", "texto": "", "n": 0,
                              "victorias": 0, "tasa_pct": None, "cohorte_n": len(cohorte)},
                "nota": nota, "motivo": razon, "poblacion": POBLACION}

    m = metricas_de(fila)
    cumple3200, texto3200 = _regla_3200(m)
    cumple_m, texto_m = _regla_muertes(m)
    cumple_p, texto_p = _regla_participacion(m)
    reglas = [
        {"clave": "min3200", "signo": "<=", "umbral": UMBRAL["min3200"],
         "meta": META["min3200"], "valor": m["min3200"],
         "segundos": m["min3200_s"], "cumple": cumple3200, "texto": texto3200},
        {"clave": "muertes", "signo": "<=", "umbral": UMBRAL["muertes"],
         "meta": META["muertes"], "valor": m["muertes"], "cumple": cumple_m,
         "texto": texto_m},
        {"clave": "participacion", "signo": ">=", "umbral": UMBRAL["participacion"],
         "meta": META["participacion"], "valor": m["participacion"],
         "cumple": cumple_p, "texto": texto_p},
    ]
    flags = tuple(r["cumple"] for r in reglas)
    cumplidas = sum(1 for f in flags if f is True)
    evaluadas = sum(1 for f in flags if f is not None)
    hist = historico(flags, cohorte, match, heroe)

    gane = fila.get("gane")
    resultado = "victoria" if gane else "derrota" if gane is not None else "sin resultado"
    dur = fila.get("duracion_s")
    heroe_nombre = nombre_heroe(heroe)
    cabeza = (f"{match} · {heroe_nombre} · {resultado}"
              + (f" · {mmss(dur)}" if numero(dur) else ""))
    linea = " · ".join(r["texto"] for r in reglas)
    n_pob = f"{POBLACION['n']:,}".replace(",", " ")
    poblacion = (f"Población ({n_pob} partidas de Abrams): "
                 f"≤6 muertes {POBLACION['muertes'][0]} % · "
                 f"≥0.40 k+a/min {POBLACION['participacion'][0]} % · "
                 "el 3 200 temprano no separa (n=3 935)")
    nota = "\n".join(x for x in (cabeza, linea, poblacion, hist.get("texto", "")) if x)

    return {"match_id": match, "heroe": heroe, "heroe_nombre": heroe_nombre,
            "gane": bool(gane) if gane is not None else None, "duracion_s": dur,
            "metricas": m, "reglas": reglas, "cumplidas": cumplidas,
            "evaluadas": evaluadas, "perfil_completo": evaluadas == 3,
            "historico": hist, "nota": nota}


def analizar(match: int, *, cuenta: int | None = None, cohorte=None, meta_dir=None,
             demo_dir=None, permitir_red: bool = True, rondas_demo: int = 1,
             espera_demo: float = 60.0, reintentos: int = 2) -> dict:
    """De la partida a la nota: descarga lo que falte, mide y evalúa."""
    medido = medir(match, cuenta=cuenta, meta_dir=meta_dir, demo_dir=demo_dir,
                   permitir_red=permitir_red, rondas_demo=rondas_demo,
                   espera_demo=espera_demo, reintentos=reintentos)
    doc = evaluar(match, medido["fila"], cohorte if cohorte is not None
                  else cargar_cohorte())
    doc["metadata"] = medido["metadata"]
    doc["demo"] = medido["demo"]
    doc["fuente"] = ("demo + metadata de la partida"
                     if "demo" in (medido["fila"] or {}).get("fuente", [])
                     else "solo metadata de la partida")
    if doc["perfil_completo"]:
        doc["codigo"] = 0
    elif doc.get("heroe") is None:
        doc["codigo"] = 2
    else:
        doc["codigo"] = 3
    return doc


# ---------------------------------------------------------------------- CLI

def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Nota de después de la partida: 3 200, muertes y participación",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Uso:", 1)[-1])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--match", type=int, help="id de partida")
    g.add_argument("--ultima", action="store_true",
                   help="la última del historial de la cuenta en .cuenta")
    p.add_argument("--cuenta", type=int, default=None,
                   help="account_id (defecto: .cuenta)")
    p.add_argument("--json", action="store_true", help="salida para el panel")
    p.add_argument("--salida", default="", help="guarda además la nota de texto aquí")
    p.add_argument("--guardar", action="store_true",
                   help="archiva la nota en salida/notas/<match>.{json,txt}")
    p.add_argument("--cohorte", default=str(COHORTE),
                   help="JSON con las partidas medidas (defecto: informes/lab/personal-demos.json)")
    p.add_argument("--sin-red", action="store_true",
                   help="solo caché: no pide metadata, demo ni historial")
    p.add_argument("--rondas-demo", type=int, default=1,
                   help="rondas para una demo recién jugada (defecto: 1)")
    p.add_argument("--espera-demo", type=float, default=60.0,
                   help="segundos entre rondas de demo (defecto: 60)")
    p.add_argument("--reintentos", type=int, default=2,
                   help="reintentos del job de demo (defecto: 2)")
    args = p.parse_args(argv)

    if args.cuenta is not None:
        cuenta = args.cuenta
    else:
        try:
            cuenta = int(CUENTA.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            print(f"no se pudo leer la cuenta en {CUENTA}; pasa --cuenta", file=sys.stderr)
            return 2

    if args.ultima:
        try:
            partidas = historial(cuenta, permitir_red=not args.sin_red)
            match = int(elegir_ultima(partidas)["match_id"])
        except SinDato as e:
            print(f"ultima: {e}", file=sys.stderr)
            return 2
    else:
        match = int(args.match)

    doc = analizar(match, cuenta=cuenta, cohorte=cargar_cohorte(args.cohorte),
                   permitir_red=not args.sin_red, rondas_demo=args.rondas_demo,
                   espera_demo=args.espera_demo, reintentos=args.reintentos)

    if args.json:
        print(json.dumps(doc, indent=1, ensure_ascii=False))
    else:
        print(doc["nota"])
        if doc["demo"].get("estado") == "no disponible":
            print(f"(demo no disponible: {doc['demo'].get('detalle', '')})", file=sys.stderr)

    if args.guardar:
        carpeta = Path(RAIZ) / "salida" / "notas"
        carpeta.mkdir(parents=True, exist_ok=True)
        mid = doc.get("match_id")
        if mid:
            (carpeta / f"{mid}.json").write_text(
                json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
            (carpeta / f"{mid}.txt").write_text(doc["nota"] + "\n", encoding="utf-8")
            print(f"nota archivada -> {carpeta / str(mid)}.json", file=sys.stderr)

    if args.salida:
        ruta = Path(args.salida).expanduser()
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(doc["nota"] + "\n", encoding="utf-8")
        print(f"nota -> {ruta}", file=sys.stderr)

    return int(doc.get("codigo", 0))


if __name__ == "__main__":
    sys.exit(main())
