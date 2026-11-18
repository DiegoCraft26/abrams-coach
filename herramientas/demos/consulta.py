#!/usr/bin/env python3
"""Consulta la API de demos de Deadlock y cachea el resultado como NDJSON.

Flujo de la API (verificado 2026-11-18):

    POST /v1/matches/demo/query  {match_id, query, format:"ndjson"}  -> {job_id, status:"queued"}
    GET  /v1/matches/demo/query/{job_id}                            -> running | done | failed
    done -> result_url  (NDJSON comprimido con zstd)

Una consulta tarda 10-30 s en el servidor. Aquí se envían como mucho 2-3 jobs a la
vez, se espera con backoff y el NDJSON descomprimido se guarda en
`data/demos_cache/<match>__<consulta>.ndjson`. Si el archivo ya está, no se vuelve
a pedir salvo que se pase `--forzar`.

El motor no es ClickHouse: es **DataFusion** (Arrow). Eso importa para escribir SQL:
las columnas con mayúsculas (`"m_steamID"`, `"m_iTeamNum"`) y las palabras
reservadas (`"delta"`, `"change"`) necesitan comillas dobles, y en un `UNION ALL`
todas las ramas tienen que devolver el mismo tipo (por eso se castea todo a VARCHAR).

Sin dependencias nuevas: `urllib` de la stdlib. Para descomprimir se usa el módulo
`zstandard` si está instalado y, si no, el binario `zstd`/`unzstd` del sistema.

Uso:
    python3 herramientas/demos/consulta.py --dry-run --match 132662221
    python3 herramientas/demos/consulta.py --match 132662221 --consulta todo
    python3 herramientas/demos/consulta.py --match 132662221,132597784 --consulta compras
    python3 herramientas/demos/consulta.py --match 132662221 --consulta oro --jugador 3
    python3 herramientas/demos/consulta.py --match 132662221 --consulta "SELECT tick FROM AbilitiesChangedEvent LIMIT 5"

Consultas con nombre:
    todo        compras + moneda + mapeo de slots en un solo job  (por defecto)
    compras     AbilitiesChangedEvent: qué se compró, quién, en qué tick
    oro         CurrencyChangedEvent: oro absoluto después de cada cambio
    mapa        CCitadelPlayerController: entity_index -> steamID y slot de lobby
    pausas      CCitadelGameRulesProxy: tramos de pausa (afectan a la conversión tick->reloj)
    oro_minuto  GoldHistoryEvent: los `minute_records` del servidor (suele venir vacío)
    control     COUNT(*) por tabla, para ver si una tabla trae datos en esa partida
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
CACHE_POR_DEFECTO = RAIZ / "data" / "demos_cache"

BASE = "https://api.deadlock-api.com"
AGENTE = "abrams-coach/lab-demos"


def api_key() -> str | None:
    """La clave de deadlock-api, si está configurada.

    Sin clave, `demo/query` tiene una cuota por IP que hoy está rota (429 en cadena). Con
    clave, la API deja de limitar por IP. No la traemos en el repo: se lee del entorno o de
    `~/.config/abrams-coach/api_key`, la primera línea.
    """
    valor = (os.environ.get("DEADLOCK_API_KEY") or "").strip()
    if valor:
        return valor
    try:
        ruta = Path(os.path.expanduser("~/.config/abrams-coach/api_key"))
        texto = ruta.read_text(encoding="utf-8").strip().splitlines()
        return texto[0].strip() if texto and texto[0].strip() else None
    except (OSError, IndexError):
        return None
TIPOS_OK = {"done"}
TIPOS_MUERTOS = {"failed", "error", "cancelled", "expired"}

# Ticks por segundo del demo y desfase medido entre el tick 0 del demo y el reloj
# de la partida (el que usa `data/replay_cache.json` y `/v1/matches/{id}/metadata`).
# El valor exacto se recalcula en `piloto.py`; aquí es solo para leer los ticks.
TPS = 64
DESFASE_S = 33.3

_impresion = threading.Lock()


def log(msg: str) -> None:
    with _impresion:
        print(msg, file=sys.stderr, flush=True)


def a_segundos(tick: int) -> float:
    """Tick del demo -> segundo del reloj de la partida (aproximado)."""
    return tick / TPS - DESFASE_S


def ticks_pausados(pausas: list[tuple[int, int]], tick: int) -> int:
    """Ticks acumulados de pausa en ese momento del demo.

    `pausas` son los tramos [(tick_inicio, pausado_acumulado)] del GameRules.
    """
    actual = 0
    for inicio, acumulado in pausas:
        if tick < inicio:
            break
        actual = acumulado
    return actual


def segundos_juego(tick: int, pausas: list[tuple[int, int]] | None = None,
                   preambulo: float = 0.0) -> float:
    """Tick del demo -> segundo del reloj de partida, descontando las pausas.

    El reloj de la partida NO avanza durante una pausa pero los ticks del demo sí.
    Sin descontarlas, un evento posterior a la pausa se lee ~33 s tarde.
    """
    return (tick - ticks_pausados(pausas or [], tick)) / TPS - preambulo


# --------------------------------------------------------------------------- SQL

_CABECERA_UNION = (
    "SELECT '{}' AS tag, CAST(tick AS VARCHAR) AS t, CAST({} AS VARCHAR) AS a, "
    "CAST({} AS VARCHAR) AS b, CAST({} AS VARCHAR) AS c, CAST({} AS VARCHAR) AS d "
    "FROM {}"
)


def _sql_compras(slot: int | None = None) -> str:
    filtro = f"\nWHERE purchaser_player_slot = {int(slot)}" if slot is not None else ""
    return (
        "SELECT tick, purchaser_player_slot, ability_id, change\n"
        "FROM AbilitiesChangedEvent" + filtro + "\nORDER BY tick"
    )


def _sql_oro(slot: int | None = None) -> str:
    filtro = f"WHERE userid = {int(slot)} " if slot is not None else ""
    return (
        "SELECT tick, userid, currency_type, currency_source, \"delta\", new_value\n"
        "FROM CurrencyChangedEvent " + filtro + "\nORDER BY tick"
    )


def _sql_mapa() -> str:
    return (
        'SELECT entity_index, MIN(tick) AS t0, MIN("m_steamID") AS steam_id, '
        'MIN("m_unLobbyPlayerSlot") AS lobby, MIN("m_iTeamNum") AS equipo, '
        'MIN("m_iszPlayerName") AS nombre\n'
        'FROM CCitadelPlayerController\nGROUP BY entity_index ORDER BY entity_index'
    )


def _sql_pausas() -> str:
    """Cambios de `m_nTotalPausedTicks`: el reloj de partida no avanza mientras dura la pausa."""
    return (
        'SELECT MIN(tick) AS tick_pausa, '
        'CAST("m_pGameRules__m_nTotalPausedTicks" AS BIGINT) AS pausado\n'
        'FROM CCitadelGameRulesProxy\n'
        'GROUP BY "m_pGameRules__m_nTotalPausedTicks" ORDER BY MIN(tick)'
    )


def _sql_oro_minuto() -> str:
    return "SELECT tick, entindex_player, minute_records FROM GoldHistoryEvent ORDER BY tick"


def _sql_control() -> str:
    return (
        "SELECT 'AbilitiesChangedEvent' AS tabla, COUNT(*) AS filas FROM AbilitiesChangedEvent\n"
        "UNION ALL SELECT 'CurrencyChangedEvent', COUNT(*) FROM CurrencyChangedEvent\n"
        "UNION ALL SELECT 'GoldHistoryEvent', COUNT(*) FROM GoldHistoryEvent\n"
        "UNION ALL SELECT 'CCitadelPlayerController', COUNT(*) FROM CCitadelPlayerController"
    )


def _sql_todo(slot: int | None = None) -> str:
    """Compras + moneda + mapa en un solo job (todo casteado a VARCHAR)."""
    filtro_oro = f" WHERE userid = {int(slot)}" if slot is not None else ""
    return "\nUNION ALL\n".join([
        _CABECERA_UNION.format("ab", "purchaser_player_slot", "ability_id", "change",
                               "NULL", "AbilitiesChangedEvent"),
        _CABECERA_UNION.format("cur", "userid", "currency_type", "\"delta\"",
                               "new_value", "CurrencyChangedEvent" + filtro_oro),
        "SELECT 'ctrl' AS tag, '0' AS t, CAST(entity_index AS VARCHAR) AS a, "
        "CAST(MIN(\"m_steamID\") AS VARCHAR) AS b, "
        "CAST(MIN(\"m_unLobbyPlayerSlot\") AS VARCHAR) AS c, "
        "CAST(MIN(\"m_iszPlayerName\") AS VARCHAR) AS d "
        "FROM CCitadelPlayerController GROUP BY entity_index",
        "SELECT 'pausa' AS tag, CAST(MIN(tick) AS VARCHAR) AS t, "
        "CAST(\"m_pGameRules__m_nTotalPausedTicks\" AS VARCHAR) AS a, "
        "CAST(NULL AS VARCHAR) AS b, CAST(NULL AS VARCHAR) AS c, "
        "CAST(NULL AS VARCHAR) AS d "
        "FROM CCitadelGameRulesProxy GROUP BY \"m_pGameRules__m_nTotalPausedTicks\"",
    ])


CONSULTAS = {
    "todo": _sql_todo,
    "compras": _sql_compras,
    "oro": _sql_oro,
    "mapa": lambda slot=None: _sql_mapa(),
    "pausas": lambda slot=None: _sql_pausas(),
    "oro_minuto": lambda slot=None: _sql_oro_minuto(),
    "control": lambda slot=None: _sql_control(),
}


def construir_sql(consulta: str, slot: int | None = None) -> tuple[str, str]:
    """Devuelve (nombre, sql). Acepta un nombre, SQL suelto o `@archivo.sql`."""
    clave = consulta.strip()
    if clave in CONSULTAS:
        return clave, CONSULTAS[clave](slot)
    if clave.startswith("@"):
        ruta = Path(clave[1:]).expanduser()
        return ruta.stem, ruta.read_text(encoding="utf-8").strip().rstrip(";")
    if clave.lower().lstrip("(").startswith(("select", "with")):
        return "suelta", clave.rstrip(";")
    raise SystemExit(
        f"consulta desconocida: {consulta!r}. Válidas: {', '.join(CONSULTAS)} "
        "— o pasa SQL que empiece por SELECT, o @ruta.sql"
    )


# ------------------------------------------------------------------------ HTTP

class ErrorDemo(RuntimeError):
    """Fallo que conviene reintentar (red, 5xx, 429, job caído)."""


class ErrorFatal(RuntimeError):
    """Fallo que no se arregla reintentando (400 de SQL, 404 de partida)."""


def _http(url: str, datos: bytes | None = None, timeout: float = 90.0) -> bytes:
    cabeceras = {"User-Agent": AGENTE}
    clave = api_key()
    if clave:
        cabeceras["X-API-KEY"] = clave
    if datos is not None:
        cabeceras["Content-Type"] = "application/json"
    peticion = urllib.request.Request(url, data=datos, headers=cabeceras)
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        cuerpo = e.read().decode("utf-8", "replace")[:400]
        if e.code in (400, 404, 422):
            raise ErrorFatal(f"HTTP {e.code} en {url}: {cuerpo}") from None
        raise ErrorDemo(f"HTTP {e.code} en {url}: {cuerpo}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ErrorDemo(f"red caída en {url}: {e}") from None


def enviar(match: int, sql: str) -> str:
    cuerpo = json.dumps({"match_id": int(match), "query": sql, "format": "ndjson"}).encode()
    datos = json.loads(_http(f"{BASE}/v1/matches/demo/query", cuerpo))
    job = datos.get("job_id")
    if not job:
        raise ErrorDemo(f"respuesta sin job_id: {datos}")
    return job


def estado(job: str) -> dict:
    return json.loads(_http(f"{BASE}/v1/matches/demo/query/{job}"))


def esperar(job: str, tope_s: float = 300.0) -> str:
    """Espera el job con backoff. Devuelve el result_url."""
    arranque = time.monotonic()
    pausa = 1.0
    while True:
        datos = estado(job)
        situacion = str(datos.get("status", "")).lower()
        if situacion in TIPOS_OK:
            url = datos.get("result_url")
            if not url:
                raise ErrorDemo(f"job {job} terminó sin result_url: {datos}")
            return url
        if situacion in TIPOS_MUERTOS:
            raise ErrorDemo(f"job {job} {situacion}: {json.dumps(datos)[:300]}")
        if time.monotonic() - arranque > tope_s:
            raise ErrorDemo(f"job {job} sigue en {situacion} tras {tope_s:.0f}s")
        time.sleep(pausa)
        pausa = min(pausa * 1.6, 6.0)


def descargar(url: str, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix(destino.suffix + ".tmp")
    with urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": AGENTE}), timeout=300
    ) as r, open(temporal, "wb") as f:
        shutil.copyfileobj(r, f)
    if temporal.stat().st_size == 0:
        temporal.unlink(missing_ok=True)
        raise ErrorDemo(f"descarga vacía desde {url}")
    temporal.replace(destino)


# ------------------------------------------------------------------ zstd

def _descomprimir_zstandard(origen: Path, destino: Path) -> bool:
    try:
        import zstandard  # type: ignore
    except ImportError:
        return False
    with open(origen, "rb") as f, open(destino, "wb") as g:
        zstandard.ZstdDecompressor().copy_stream(f, g, read_size=1 << 20)
    return True


def _descomprimir_binario(origen: Path, destino: Path) -> bool:
    for programa in ("unzstd", "zstd"):
        exe = shutil.which(programa)
        if not exe:
            continue
        banderas = ["-d", "-q", "-c"] if programa == "unzstd" else ["-d", "-q", "-c"]
        with open(destino, "wb") as g:
            hecho = subprocess.run([exe, *banderas, str(origen)], stdout=g,
                                   stderr=subprocess.PIPE)
        if hecho.returncode == 0:
            return True
        destino.unlink(missing_ok=True)
    return False


def descomprimir(origen: Path, destino: Path) -> None:
    """Descomprime a un temporal y renombra: nunca queda un NDJSON a medias.

    Una tabla puede devolver 0 filas de forma legítima (p.ej. `oro_minuto`), así que
    el archivo de 0 bytes es un resultado válido y no se puede confundir con un fallo.
    """
    temporal = destino.with_name(destino.name + ".tmp")
    try:
        if not (_descomprimir_zstandard(origen, temporal)
                or _descomprimir_binario(origen, temporal)):
            raise ErrorFatal(
                "no hay con qué descomprimir zstd: instala el módulo `zstandard` "
                "o el binario `zstd`"
            )
        temporal.replace(destino)
    finally:
        temporal.unlink(missing_ok=True)


# ------------------------------------------------------------------ ejecución

def ruta_cache(cache: Path, match: int, nombre: str) -> Path:
    return cache / f"{int(match)}__{nombre}.ndjson"


def contar_lineas(ruta: Path) -> int:
    with open(ruta, "rb") as f:
        return sum(1 for _ in f)


def una(match: int, nombre: str, sql: str, cache: Path, *, forzar: bool = False,
        reintentos: int = 2, tope_s: float = 300.0, guardar_zst: bool = False,
        callar: bool = True) -> dict:
    """Ejecuta una consulta para una partida. Devuelve un resumen."""
    destino = ruta_cache(cache, match, nombre)
    resumen = {"match": match, "consulta": nombre, "ruta": str(destino),
               "cacheado": False, "filas": 0, "segundos": 0.0, "reintentos": 0}
    if destino.exists() and not forzar:
        resumen.update(cacheado=True, filas=contar_lineas(destino))
        if not callar:
            log(f"  {match} {nombre}: ya estaba en caché ({resumen['filas']} filas)")
        return resumen

    arranque = time.monotonic()
    fallo: Exception | None = None
    for intento in range(reintentos + 1):
        resumen["reintentos"] = intento
        try:
            job = enviar(match, sql)
            if not callar:
                log(f"  {match} {nombre}: job {job}")
            url = esperar(job, tope_s)
            crudo = destino.with_suffix(".ndjson.zst")
            descargar(url, crudo)
            descomprimir(crudo, destino)
            if not guardar_zst:
                crudo.unlink(missing_ok=True)
            resumen.update(filas=contar_lineas(destino),
                           segundos=round(time.monotonic() - arranque, 1))
            if not callar:
                log(f"  {match} {nombre}: {resumen['filas']} filas en "
                    f"{resumen['segundos']}s")
            return resumen
        except ErrorFatal as e:
            raise ErrorFatal(f"{match} {nombre}: {e}") from None
        except ErrorDemo as e:
            fallo = e
            if intento < reintentos:
                espera = 3.0 * (2 ** intento) + random.random()
                log(f"  {match} {nombre}: fallo {e} — reintento "
                    f"{intento + 1}/{reintentos} en {espera:.0f}s")
                time.sleep(espera)
    resumen["segundos"] = round(time.monotonic() - arranque, 1)
    raise ErrorDemo(f"{match} {nombre}: {fallo} (agotados los {reintentos} reintentos)")


def varias(matches: list[int], nombre: str, sql: str, cache: Path, **opciones) -> list[dict]:
    """Ejecuta la misma consulta sobre varias partidas, como mucho `paralelo` a la vez."""
    paralelo = max(1, min(int(opciones.pop("paralelo", 2)), 3))
    resultados: list[dict] = []
    with ThreadPoolExecutor(max_workers=paralelo) as grupo:
        futuros = [grupo.submit(una, m, nombre, sql, cache, **opciones) for m in matches]
        for futuro, match in zip(futuros, matches):
            try:
                resultados.append(futuro.result())
            except (ErrorFatal, ErrorDemo) as e:
                log(f"  {match}: {e}")
                resultados.append({"match": match, "consulta": nombre, "error": str(e)})
    return resultados


# --------------------------------------------------------------------- main

def lista_matches(texto: str) -> list[int]:
    vistos: list[int] = []
    for trozo in texto.replace(";", ",").replace(" ", ",").split(","):
        trozo = trozo.strip()
        if trozo:
            vistos.append(int(trozo))
    return vistos


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Extrae tablas de una demo de Deadlock vía api.deadlock-api.com",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Uso:", 1)[-1],
    )
    p.add_argument("--match", default="", help="id(s) de partida, separados por coma")
    p.add_argument("--consulta", default="todo",
                   help="nombre de la consulta, SQL suelto o @archivo.sql (defecto: todo)")
    p.add_argument("--dry-run", action="store_true",
                   help="enseña el SQL, la URL y la caché sin tocar la red")
    p.add_argument("--reintentos", type=int, default=2, help="reintentos por partida (defecto: 2)")
    p.add_argument("--paralelo", type=int, default=2, help="jobs en vuelo, 1-3 (defecto: 2)")
    p.add_argument("--jugador", type=int, default=None,
                   help="filtra por slot de jugador en SQL (0-11) para bajar el tamaño")
    p.add_argument("--cache", default=str(CACHE_POR_DEFECTO), help="carpeta de caché")
    p.add_argument("--forzar", action="store_true", help="ignora la caché y vuelve a pedir")
    p.add_argument("--guardar-zst", action="store_true", help="conserva el .ndjson.zst")
    p.add_argument("--espera-max", type=float, default=300.0, help="segundos máximos por job")
    p.add_argument("--json", action="store_true", help="imprime el resumen en JSON")
    args = p.parse_args(argv)

    cache = Path(args.cache).expanduser()
    nombre, sql = construir_sql(args.consulta, args.jugador)
    if args.jugador is not None:
        # un filtro por jugador es otro recorte: no puede pisar la caché sin filtro
        nombre = f"{nombre}-slot{args.jugador}"
    matches = lista_matches(args.match)

    if args.dry_run:
        print(f"consulta : {nombre}")
        print(f"caché    : {cache}")
        print(f"matches  : {matches or '(ninguno)'}")
        print(f"en vuelo : {max(1, min(args.paralelo, 3))}")
        print(f"reintentos: {args.reintentos}   espera máx: {args.espera_max:.0f}s")
        print("\n--- SQL ---")
        print(sql)
        print("--- fin SQL ---")
        for m in matches:
            destino = ruta_cache(cache, m, nombre)
            print(f"{m}: {'YA EN CACHÉ' if destino.exists() else 'pendiente'} -> {destino}")
        if matches:
            print(f"POST {BASE}/v1/matches/demo/query")
        return 0

    if not matches:
        p.error("hace falta --match (uno o varios ids separados por coma)")

    log(f"[{nombre}] {len(matches)} partida(s), {max(1, min(args.paralelo, 3))} en vuelo")
    resultados = varias(matches, nombre, sql, cache, forzar=args.forzar,
                        reintentos=max(0, args.reintentos), tope_s=args.espera_max,
                        guardar_zst=args.guardar_zst, paralelo=args.paralelo)

    if args.json:
        print(json.dumps(resultados, indent=1, ensure_ascii=False))
    else:
        total = sum(r.get("filas", 0) for r in resultados)
        buenas = sum(1 for r in resultados if "error" not in r)
        segundos = sum(r.get("segundos", 0.0) for r in resultados)
        print(f"{buenas}/{len(resultados)} partidas ok, {total} filas, "
              f"{segundos:.0f}s de servidor")
        for r in resultados:
            if "error" in r:
                print(f"  FALLO {r['match']}: {r['error']}")
            else:
                marca = "caché" if r["cacheado"] else f"{r['segundos']}s"
                print(f"  {r['match']}: {r['filas']} filas ({marca}) -> {r['ruta']}")
    return 0 if all("error" not in r for r in resultados) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ErrorFatal as e:
        log(f"error: {e}")
        sys.exit(2)
    except KeyboardInterrupt:
        log("interrumpido")
        sys.exit(130)
