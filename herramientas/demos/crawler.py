#!/usr/bin/env python3
"""Crawler de demos recién terminadas de Deadlock.

La demo caduca y `POST /v1/matches/demo/query` tarda 15-30 s por consulta. Por eso
no se hace backfill del corpus viejo: se descubren partidas que acaban de terminar
y se extraen mientras su demo todavía existe.

Fuentes de descubrimiento (las dos, cada una aporta lo suyo):

* `GET /v1/matches/active`: foto del watch tab. Un id que estaba en la foto anterior
  y ya no está se toma como terminado. Detecta partidas "en caliente".
* `GET /v1/matches/recently-fetched`: catálogo de partidas que la API ya vio. Se
  filtran las de 12 jugadores, duración >= `--duracion-min` y arranque dentro de
  `--ventana-h`. Aporta el lote que terminó mientras el crawler estaba apagado.

Cada partida se extrae con **dos** jobs, sin filtro de jugador (los 12 slots):

    AbilitiesChangedEvent   -> abilities.ndjson
    CurrencyChangedEvent    -> currency_gold.ndjson   (currency_type = 0, oro)

El NDJSON crudo (descomprimido) queda en `datos/demos/<match_id>/` y el estado en
`datos/demos/estado.json`. Es idempotente: si el archivo existe, no se vuelve a
pedir; al arrancar, lo que quedó `en_curso` vuelve a la cola.

Límites: 2-3 jobs en vuelo (tope duro 3), <= `--rpm` peticiones por minuto (150 por
defecto de la API, aquí 120) y ante un 429 se para todo el proceso el tiempo que
diga `Retry-After` (mínimo 60 s).

Uso:
    python3 herramientas/demos/crawler.py --dry-run
    python3 herramientas/demos/crawler.py --minutos 25 --max-partidas 40
    python3 herramientas/demos/crawler.py --match 139680544 --sin-descubrir --minutos 3
    python3 herramientas/demos/crawler.py --minutos 25 --resumen datos/demos/ultima-corrida.json
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
BASE = "https://api.deadlock-api.com"
AGENTE = "abrams-coach/crawler-demos/1"


def _leer_clave():
    """La clave de deadlock-api: entorno o `~/.config/abrams-coach/api_key`."""
    valor = (os.environ.get("DEADLOCK_API_KEY") or "").strip()
    if valor:
        return valor
    try:
        with open(os.path.expanduser("~/.config/abrams-coach/api_key"),
                  encoding="utf-8") as f:
            primera = f.readline().strip()
            return primera or None
    except OSError:
        return None
SALIDA_POR_DEFECTO = RAIZ / "datos" / "demos"
TPS = 64

SQL_COMPRAS = (
    "SELECT tick, purchaser_player_slot, ability_id, change\n"
    "FROM AbilitiesChangedEvent\n"
    "ORDER BY tick"
)
SQL_ORO = (
    "SELECT tick, userid, currency_type, currency_source, \"delta\", new_value\n"
    "FROM CurrencyChangedEvent\n"
    "WHERE currency_type = 0\n"
    "ORDER BY tick"
)

TIPOS_MUERTOS = {"failed", "error", "cancelled", "expired"}
JUGADORES_PARTIDA = 12

_PARADA = threading.Event()


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def iso(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts if ts else time.time()))


# ------------------------------------------------------------------ errores

class Error404(RuntimeError):
    """La partida no tiene demo (todavía o nunca)."""


class ErrorFatal(RuntimeError):
    """No se arregla reintentando: SQL inválido, 400/422."""


class ErrorTemporal(RuntimeError):
    """Red, 5xx, job caído: reintentar con espera."""


# ------------------------------------------------------- límites de peticiones

class Limitador:
    """Espacia las peticiones para no pasar de `rpm` por minuto."""

    def __init__(self, rpm: int) -> None:
        self.intervalo = 60.0 / max(1, rpm)
        self._candado = threading.Lock()
        self._siguiente = 0.0

    def esperar(self) -> None:
        with self._candado:
            ahora = time.monotonic()
            cuando = max(ahora, self._siguiente)
            self._siguiente = cuando + self.intervalo
        falta = cuando - time.monotonic()
        if falta > 0:
            time.sleep(falta)


class Cortacircuitos:
    """Ante 429 se para todo: ningún hilo vuelve a pedir hasta que pase."""

    def __init__(self) -> None:
        self._candado = threading.Lock()
        self._hasta = 0.0

    def pausar(self, segundos: float) -> None:
        with self._candado:
            self._hasta = max(self._hasta, time.monotonic() + segundos)

    def esperar(self) -> None:
        while not _PARADA.is_set():
            with self._candado:
                falta = self._hasta - time.monotonic()
            if falta <= 0:
                return
            time.sleep(min(falta, 5.0))


# ------------------------------------------------------------------- cliente

class Cliente:
    """HTTP con límite de tasa, corte por 429 y contadores."""

    def __init__(self, rpm: int) -> None:
        self.limitador = Limitador(rpm)
        self.corte = Cortacircuitos()
        self._clave = _leer_clave()      # X-API-KEY si está configurada; si no, None
        self._candado = threading.Lock()
        self.contadores = {"peticiones": 0, "jobs": 0, "429": 0, "errores": 0}

    def _contar(self, clave: str, n: int = 1) -> None:
        with self._candado:
            self.contadores[clave] += n

    def _abrir(self, url: str, datos: bytes | None, timeout: float):
        cabeceras = {"User-Agent": AGENTE}
        # La misma clave que usa consulta.py: con X-API-KEY la API deja de limitar por IP.
        clave = getattr(self, "_clave", None)
        if clave:
            cabeceras["X-API-KEY"] = clave
        if datos is not None:
            cabeceras["Content-Type"] = "application/json"
        peticion = urllib.request.Request(url, data=datos, headers=cabeceras)
        self.limitador.esperar()
        self.corte.esperar()
        self._contar("peticiones")
        return urllib.request.urlopen(peticion, timeout=timeout)

    def pedir(self, url: str, datos: bytes | None = None,
              timeout: float = 90.0) -> bytes:
        ultimo: Exception | None = None
        for _ in range(5):
            try:
                with self._abrir(url, datos, timeout) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                cuerpo = e.read().decode("utf-8", "replace")[:400]
                if e.code == 429:
                    self._contar("429")
                    crudo = e.headers.get("Retry-After") if e.headers else None
                    try:
                        espera = float(crudo) if crudo else 60.0
                    except ValueError:
                        espera = 60.0
                    espera = max(60.0, espera)
                    log(f"429: paro {espera:.0f}s (todo el proceso) — {url}")
                    self.corte.pausar(espera)
                    ultimo = ErrorTemporal(f"429 en {url}")
                    continue
                if e.code == 404:
                    raise Error404(cuerpo) from None
                if e.code in (400, 422):
                    raise ErrorFatal(f"HTTP {e.code} en {url}: {cuerpo}") from None
                self._contar("errores")
                ultimo = ErrorTemporal(f"HTTP {e.code} en {url}: {cuerpo}")
                break
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                self._contar("errores")
                ultimo = ErrorTemporal(f"red en {url}: {e}")
                break
        raise ultimo or ErrorTemporal(f"sin respuesta de {url}")

    def json(self, ruta: str, timeout: float = 60.0):
        crudo = self.pedir(BASE + ruta, timeout=timeout)
        return json.loads(crudo)

    def post_json(self, ruta: str, cuerpo: dict, timeout: float = 60.0):
        datos = json.dumps(cuerpo).encode()
        return json.loads(self.pedir(BASE + ruta, datos=datos, timeout=timeout))

    def descargar(self, url: str, destino: Path, timeout: float = 300.0) -> None:
        """Descarga el .ndjson.zst a un temporal (sin cargarlo entero en RAM)."""
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal = destino.with_name(destino.name + ".tmp")
        for _ in range(5):
            try:
                with self._abrir(url, None, timeout) as r, open(temporal, "wb") as f:
                    shutil.copyfileobj(r, f)
                if temporal.stat().st_size == 0:
                    temporal.unlink(missing_ok=True)
                    raise ErrorTemporal(f"descarga vacía: {url}")
                temporal.replace(destino)
                return
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    self._contar("429")
                    log("429 en la descarga: paro 60s")
                    self.corte.pausar(60.0)
                    continue
                temporal.unlink(missing_ok=True)
                # Que el extracto caduque no significa que la demo no exista: la
                # partida se reintenta, no se marca como 404.
                raise ErrorTemporal(f"HTTP {e.code} al bajar {url}") from None
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                temporal.unlink(missing_ok=True)
                raise ErrorTemporal(f"red al bajar {url}: {e}") from None
        raise ErrorTemporal(f"no se pudo bajar {url}")


# ------------------------------------------------------------------- zstd

def descomprimir(origen: Path, destino: Path) -> None:
    """Descomprime a temporal y renombra: nunca queda un NDJSON a medias."""
    temporal = destino.with_name(destino.name + ".tmp")
    try:
        hecho = False
        try:
            import zstandard  # type: ignore

            with open(origen, "rb") as f, open(temporal, "wb") as g:
                zstandard.ZstdDecompressor().copy_stream(f, g, read_size=1 << 20)
            hecho = True
        except ImportError:
            hecho = False
        if not hecho:
            for programa in ("unzstd", "zstd"):
                exe = shutil.which(programa)
                if not exe:
                    continue
                with open(temporal, "wb") as g:
                    hecho = subprocess.run(
                        [exe, "-d", "-q", "-c", str(origen)],
                        stdout=g, stderr=subprocess.PIPE,
                    ).returncode == 0
                if hecho:
                    break
                temporal.unlink(missing_ok=True)
        if not hecho:
            raise ErrorFatal("no hay con qué descomprimir zstd (módulo ni binario)")
        temporal.replace(destino)
    finally:
        temporal.unlink(missing_ok=True)


def contar_lineas(ruta: Path) -> int:
    with open(ruta, "rb") as f:
        return sum(1 for _ in f)


# ------------------------------------------------------------------ trabajos

def lanzar(cliente: Cliente, match: int, sql: str) -> str:
    datos = cliente.post_json(
        "/v1/matches/demo/query",
        {"match_id": int(match), "query": sql, "format": "ndjson"},
    )
    job = datos.get("job_id")
    if not job:
        raise ErrorTemporal(f"respuesta sin job_id: {datos}")
    cliente._contar("jobs")
    return str(job)


def esperar_job(cliente: Cliente, job: str, tope_s: float) -> str:
    arranque = time.monotonic()
    pausa = 2.0
    while not _PARADA.is_set():
        try:
            datos = cliente.json(f"/v1/matches/demo/query/{job}", timeout=40.0)
        except Error404:
            # Un job que ya no existe no es una partida sin demo.
            raise ErrorTemporal(f"job {job} desapareció (404)") from None
        situacion = str(datos.get("status", "")).lower()
        if situacion == "done":
            url = datos.get("result_url")
            if not url:
                raise ErrorTemporal(f"job {job} terminó sin result_url")
            return str(url)
        if situacion in TIPOS_MUERTOS:
            # Un "failed" del parser de demos no se arregla reintentando el mismo SQL.
            detalle = json.dumps(datos, ensure_ascii=False)[:300]
            if "demo" in detalle.lower() and ("no demo" in detalle.lower()
                                              or "not found" in detalle.lower()):
                raise Error404(detalle)
            raise ErrorTemporal(f"job {job} {situacion}: {detalle}")
        if time.monotonic() - arranque > tope_s:
            raise ErrorTemporal(f"job {job} sigue en {situacion} tras {tope_s:.0f}s")
        time.sleep(pausa)
        pausa = min(pausa * 1.3, 5.0)
    raise ErrorTemporal("parada pedida mientras esperaba el job")


def extraer(cliente: Cliente, match: int, carpeta: Path, args) -> dict:
    """Baja las dos tablas que no estén ya. Devuelve filas, bytes y segundos."""
    arranque = time.monotonic()
    carpeta.mkdir(parents=True, exist_ok=True)
    filas: dict[str, int] = {}
    for nombre, sql in (("abilities", SQL_COMPRAS), ("currency_gold", SQL_ORO)):
        destino = carpeta / f"{nombre}.ndjson"
        if destino.exists():
            filas[nombre] = contar_lineas(destino)
            continue
        fallo: Exception | None = None
        for intento in range(args.reintentos + 1):
            try:
                job = lanzar(cliente, match, sql)
                url = esperar_job(cliente, job, args.espera_job)
                crudo = destino.with_name(destino.name + ".zst")
                cliente.descargar(url, crudo)
                descomprimir(crudo, destino)
                crudo.unlink(missing_ok=True)
                filas[nombre] = contar_lineas(destino)
                log(f"  {match} {nombre}: {filas[nombre]} filas")
                fallo = None
                break
            except Error404:
                raise
            except ErrorFatal:
                raise
            except ErrorTemporal as e:
                fallo = e
                if intento < args.reintentos and not _PARADA.is_set():
                    espera = 5.0 * (2 ** intento) + random.random()
                    log(f"  {match} {nombre}: {e} — reintento en {espera:.0f}s")
                    time.sleep(espera)
        if fallo is not None:
            raise fallo
    tam = 0
    for ruta in carpeta.glob("*.ndjson"):
        tam += ruta.stat().st_size
    return {
        "filas": filas,
        "bytes": tam,
        "segundos": round(time.monotonic() - arranque, 1),
    }


def escribir_meta(carpeta: Path, match: int, info: dict, resultado: dict) -> None:
    meta = {
        "match_id": match,
        "fuente": info.get("fuente"),
        "inicio_partida": info.get("inicio"),
        "duracion_s": info.get("duracion"),
        "fin_partida": info.get("fin"),
        "extraido": iso(),
        "filas": resultado["filas"],
        "bytes_ndjson": resultado["bytes"],
        "segundos": resultado["segundos"],
        "consultas": {"abilities": SQL_COMPRAS, "currency_gold": SQL_ORO},
    }
    destino = carpeta / "meta.json"
    temporal = destino.with_name(destino.name + ".tmp")
    temporal.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    temporal.replace(destino)


# ------------------------------------------------------------------- estado

def estado_nuevo() -> dict:
    return {
        "version": 1,
        "creado": iso(),
        "actualizado": iso(),
        "partidas": {},
        "activos": {},
        "contadores": {},
        "ultima_corrida": None,
    }


def cargar_estado(ruta: Path) -> dict:
    if not ruta.exists():
        return estado_nuevo()
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        respaldo = ruta.with_name(ruta.name + f".roto-{int(time.time())}")
        ruta.replace(respaldo)
        log(f"estado ilegible ({e}); respaldado en {respaldo}")
        return estado_nuevo()
    if not isinstance(datos, dict) or "partidas" not in datos:
        respaldo = ruta.with_name(ruta.name + f".roto-{int(time.time())}")
        ruta.replace(respaldo)
        log(f"estado con forma inesperada; respaldado en {respaldo}")
        return estado_nuevo()
    datos.setdefault("activos", {})
    datos.setdefault("contadores", {})
    datos.setdefault("ultima_corrida", None)
    # Reanudable: lo que quedó en vuelo cuando se murió el proceso vuelve a la cola.
    for info in datos["partidas"].values():
        if info.get("estado") == "en_curso":
            info["estado"] = "espera"
            info["siguiente"] = 0
    return datos


def guardar_estado(ruta: Path, estado: dict) -> None:
    partidas = estado["partidas"]
    estado["actualizado"] = iso()
    estado["contadores"] = {
        "descubiertas": len(partidas),
        "procesadas": sum(1 for p in partidas.values() if p.get("estado") == "procesada"),
        "fallidas": sum(1 for p in partidas.values() if p.get("estado") == "fallida"),
        "404": sum(1 for p in partidas.values() if p.get("estado") == "404"),
        "en_espera": sum(1 for p in partidas.values() if p.get("estado") == "espera"),
        "bytes": sum(int(p.get("bytes") or 0) for p in partidas.values()),
    }
    temporal = ruta.with_name(ruta.name + ".tmp")
    temporal.write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")
    temporal.replace(ruta)


def alta(estado: dict, match: int, fuente: str, inicio: float | None,
         duracion: float | None, fin: float, args) -> bool:
    """Añade una partida a la cola si no estaba. Devuelve si era nueva."""
    clave = str(match)
    if clave in estado["partidas"]:
        return False
    ahora = time.time()
    if fin <= 0:
        fin = ahora
    listo = max(ahora, fin + args.edad_demo_min * 60.0)
    estado["partidas"][clave] = {
        "descubierta": ahora,
        "fuente": fuente,
        "inicio": inicio,
        "duracion": duracion,
        "fin": fin,
        "estado": "espera",
        "siguiente": listo,
        "intentos_demo": 0,
        "fallos_red": 0,
        "bytes": 0,
        "filas": None,
        "ultimo_error": None,
    }
    return True


# -------------------------------------------------------------- descubrimiento

def en_cola(estado: dict) -> int:
    return sum(1 for p in estado["partidas"].values() if p.get("estado") == "espera")


def descubrir_active(cliente: Cliente, estado: dict, args) -> int:
    datos = cliente.json("/v1/matches/active", timeout=60.0)
    ahora = time.time()
    actuales: dict[str, dict] = {}
    for m in datos or []:
        if len(m.get("players") or []) != JUGADORES_PARTIDA:
            continue
        actuales[str(m["match_id"])] = {
            "visto": ahora,
            "inicio": m.get("start_time"),
            "match_mode": m.get("match_mode"),
        }
    previos = estado.get("activos") or {}
    lleno = en_cola(estado) >= args.max_cola
    nuevas = 0
    for clave, info in previos.items():
        if clave in actuales or lleno:
            continue
        # Estaba en la foto anterior y ya no está: terminó (o salió del top 200).
        if alta(estado, int(clave), "active", info.get("inicio"), None, ahora, args):
            nuevas += 1
    estado["activos"] = actuales
    return nuevas


def descubrir_recientes(cliente: Cliente, estado: dict, args) -> int:
    if en_cola(estado) >= args.max_cola:
        return 0
    datos = cliente.json("/v1/matches/recently-fetched", timeout=90.0)
    ahora = time.time()
    nuevas = 0
    for m in datos or []:
        if len(m.get("players") or []) != JUGADORES_PARTIDA:
            continue
        duracion = m.get("duration_s")
        if not duracion or duracion < args.duracion_min:
            continue
        inicio = m.get("start_time")
        if not inicio:
            continue
        fin = inicio + duracion
        if ahora - inicio > args.ventana_h * 3600:
            continue
        if ahora - fin < args.edad_demo_min * 60:
            continue
        if alta(estado, int(m["match_id"]), "recently-fetched", inicio, duracion, fin, args):
            nuevas += 1
    return nuevas


def listos(estado: dict, ahora: float) -> list[tuple[str, dict]]:
    pendientes = [
        (clave, info) for clave, info in estado["partidas"].items()
        if info.get("estado") == "espera" and float(info.get("siguiente") or 0) <= ahora
    ]
    # Un reintento vencido va antes que el backlog: si no, con cientos de partidas
    # nuevas por delante, el 404 de una demo que acaba de aparecer no se reintenta
    # nunca dentro de la pasada.
    pendientes.sort(key=lambda par: (
        0 if int(par[1].get("intentos_demo") or 0) > 0 else 1,
        par[1].get("siguiente") or 0,
        par[1].get("inicio") or 0,
    ))
    return pendientes


# --------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Crawler de demos recién terminadas (Deadlock)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Uso:", 1)[-1],
    )
    p.add_argument("--minutos", type=float, default=25.0, help="presupuesto de reloj (defecto 25)")
    p.add_argument("--max-partidas", type=int, default=0, help="tope de partidas procesadas (0 = sin tope)")
    p.add_argument("--max-cola", type=int, default=500,
                   help="tope de partidas en espera; frena el descubrimiento (defecto 500)")
    p.add_argument("--paralelo", type=int, default=3, help="jobs en vuelo, 1-3 (defecto 3)")
    p.add_argument("--rpm", type=int, default=120, help="peticiones por minuto (defecto 120, tope 150)")
    p.add_argument("--ventana-h", type=float, default=4.0,
                   help="antigüedad máxima de la partida (horas desde el inicio, defecto 4)")
    p.add_argument("--edad-demo-min", type=float, default=20.0,
                   help="minutos desde el fin antes de pedir la demo (defecto 20)")
    p.add_argument("--duracion-min", type=float, default=300.0,
                   help="duración mínima de la partida en segundos (defecto 300)")
    p.add_argument("--espera-404-min", type=float, default=12.0,
                   help="espera tras un 404 antes de reintentar (defecto 12)")
    p.add_argument("--max-intentos-demo", type=int, default=6,
                   help="404 tolerados por partida antes de darla por perdida (defecto 6)")
    p.add_argument("--max-fallos-red", type=int, default=5,
                   help="fallos de red tolerados por partida (defecto 5)")
    p.add_argument("--reintentos", type=int, default=2, help="reintentos por consulta (defecto 2)")
    p.add_argument("--espera-job", type=float, default=300.0, help="segundos máximos por job")
    p.add_argument("--intervalo-active", type=float, default=90.0,
                   help="segundos entre fotos de /matches/active (defecto 90)")
    p.add_argument("--intervalo-rf", type=float, default=240.0,
                   help="segundos entre /matches/recently-fetched (defecto 240)")
    p.add_argument("--gracia", type=float, default=180.0,
                   help="segundos para dejar terminar lo que esté en vuelo (defecto 180)")
    p.add_argument("--espacio-min-gb", type=float, default=5.0,
                   help="si al disco de salida le quedan menos GB, no arranca más trabajo")
    p.add_argument("--salida", default=str(SALIDA_POR_DEFECTO), help="carpeta de datos")
    p.add_argument("--estado", default="", help="ruta de estado.json (defecto <salida>/estado.json)")
    p.add_argument("--resumen", default="", help="ruta del resumen de la corrida")
    p.add_argument("--match", default="", help="ids manuales separados por coma (para pruebas)")
    p.add_argument("--sin-descubrir", action="store_true", help="no consulta active/recently-fetched")
    p.add_argument("--dry-run", action="store_true", help="enseña la configuración y sale")
    p.add_argument("--verbose", action="store_true", help="más detalle por partida")
    args = p.parse_args(argv)

    if args.paralelo < 1 or args.paralelo > 3:
        p.error("--paralelo debe ser 1, 2 o 3 (la API no documenta más y 150 rpm es el techo)")
    if args.rpm > 150:
        p.error("--rpm no puede pasar de 150 (límite de la API)")
    if args.minutos <= 0 and args.max_partidas <= 0:
        p.error("con --minutos 0 hace falta --max-partidas > 0")

    salida = Path(args.salida).expanduser().resolve()
    estado_ruta = Path(args.estado).expanduser().resolve() if args.estado else salida / "estado.json"
    resumen_ruta = Path(args.resumen).expanduser().resolve() if args.resumen else salida / "ultima-corrida.json"
    manuales = [int(x) for x in args.match.replace(" ", ",").split(",") if x.strip()]

    if args.dry_run:
        print(f"salida   : {salida}")
        print(f"estado   : {estado_ruta}")
        print(f"resumen  : {resumen_ruta}")
        print(f"presupuesto: {args.minutos:g} min, {args.max_partidas or 'sin'} partidas")
        print(f"vuelo    : {args.paralelo} jobs, {args.rpm} rpm")
        print(f"ventana  : {args.ventana_h:g} h, demo a los {args.edad_demo_min:g} min del fin")
        print(f"espacio  : para si quedan < {args.espacio_min_gb:g} GB")
        print(f"fuentes  : {'manual' if args.sin_descubrir else 'active + recently-fetched'}")
        print(f"manuales : {manuales or '(ninguna)'}")
        print("\n--- SQL abilities ---")
        print(SQL_COMPRAS)
        print("--- SQL currency_gold ---")
        print(SQL_ORO)
        return 0

    salida.mkdir(parents=True, exist_ok=True)
    estado = cargar_estado(estado_ruta)
    cliente = Cliente(args.rpm)

    if manuales:
        ahora = time.time()
        for mid in manuales:
            alta(estado, mid, "manual", None, None, ahora - 3600, args)

    t_inicio = time.time()
    m_inicio = time.monotonic()
    deadline = m_inicio + args.minutos * 60.0 if args.minutos > 0 else float("inf")
    corrida = {"inicio": iso(t_inicio), "procesadas": 0, "404": 0, "fallidas": 0,
               "bytes": 0, "descubiertas": 0, "segundos_partida": []}

    log(f"crawler: {args.paralelo} jobs, {args.rpm} rpm, {args.minutos:g} min, "
        f"salida={salida}")
    log(f"estado: {len(estado['partidas'])} partidas conocidas, "
        f"{estado['contadores'].get('procesadas', 0)} ya procesadas")

    ultimo_active = 0.0
    ultimo_rf = 0.0
    ultimo_disco = 0.0
    en_vuelo: dict = {}
    procesadas_corrida = 0
    parada_suave = False
    aviso_cola = False

    def pedir_parada(signum, frame):  # noqa: ANN001
        nonlocal parada_suave
        parada_suave = True
        _PARADA.set()
        log(f"señal {signum}: cierro en cuanto termine lo que está en vuelo")

    signal.signal(signal.SIGTERM, pedir_parada)
    signal.signal(signal.SIGINT, pedir_parada)

    with ThreadPoolExecutor(max_workers=args.paralelo) as grupo:
        while True:
            ahora_m = time.monotonic()
            ahora = time.time()

            # 0) guardia de disco: mejor parar que llenar la máquina
            if ahora_m - ultimo_disco >= 60:
                ultimo_disco = ahora_m
                try:
                    libre = shutil.disk_usage(salida).free
                except OSError:
                    libre = float("inf")
                if libre < args.espacio_min_gb * 1e9:
                    log(f"disco: quedan {libre / 1e9:.1f} GB "
                        f"(< {args.espacio_min_gb:g} GB), no arranco más")
                    break

            # 1) descubrir (con tope de cola: el catálogo surte más de lo que se puede extraer)
            if en_cola(estado) >= args.max_cola:
                if not aviso_cola:
                    log(f"cola llena ({args.max_cola}); dejo de descubrir hasta que baje")
                    aviso_cola = True
            else:
                aviso_cola = False
            if not args.sin_descubrir and not _PARADA.is_set():
                try:
                    if ahora_m - ultimo_active >= args.intervalo_active:
                        n = descubrir_active(cliente, estado, args)
                        ultimo_active = ahora_m
                        if n:
                            log(f"active: {n} partidas terminadas nuevas")
                            corrida["descubiertas"] += n
                        guardar_estado(estado_ruta, estado)
                    if ahora_m - ultimo_rf >= args.intervalo_rf:
                        n = descubrir_recientes(cliente, estado, args)
                        ultimo_rf = ahora_m
                        if n:
                            log(f"recently-fetched: {n} partidas nuevas en la ventana")
                            corrida["descubiertas"] += n
                        guardar_estado(estado_ruta, estado)
                except ErrorTemporal as e:
                    log(f"descubrimiento: {e} (sigo con lo que ya hay)")
                except ErrorFatal as e:
                    log(f"descubrimiento fatal: {e}")

            # 2) lanzar lo que toca
            tope_alcanzado = args.max_partidas > 0 and procesadas_corrida >= args.max_partidas
            if not _PARADA.is_set() and not tope_alcanzado and ahora_m < deadline:
                cupo = args.paralelo - len(en_vuelo)
                if cupo > 0:
                    for clave, info in listos(estado, ahora)[:cupo]:
                        info["estado"] = "en_curso"
                        info["siguiente"] = 0
                        guardar_estado(estado_ruta, estado)
                        futuro = grupo.submit(extraer_y_cerrar, cliente, int(clave),
                                              dict(info), salida / clave, args)
                        en_vuelo[futuro] = clave
                        if args.verbose:
                            log(f"  {clave}: empiezo")

            # 3) recoger
            if en_vuelo:
                hechos, _ = wait(list(en_vuelo), timeout=0.5,
                                 return_when=FIRST_COMPLETED)
                for futuro in hechos:
                    clave = en_vuelo.pop(futuro)
                    info = estado["partidas"][clave]
                    try:
                        resultado = futuro.result()
                    except Exception as e:  # noqa: BLE001
                        resultado = {"estado": "red", "error": f"{type(e).__name__}: {e}"}
                    aplicar_resultado(estado, clave, info, resultado, args, corrida)
                    if resultado["estado"] == "procesada":
                        procesadas_corrida += 1
                    guardar_estado(estado_ruta, estado)
            else:
                time.sleep(0.4)

            # 4) fin
            if _PARADA.is_set():
                break
            if tope_alcanzado:
                log(f"tope de {args.max_partidas} partidas alcanzado")
                break
            if time.monotonic() >= deadline:
                log("presupuesto de minutos agotado")
                break

        # dejar terminar lo que está en vuelo, con tope
        if en_vuelo:
            log(f"espero {len(en_vuelo)} partida(s) en vuelo (máx {args.gracia:.0f}s)")
            hechos, pendientes = wait(list(en_vuelo),
                                      timeout=max(30.0, args.gracia))
            for futuro in hechos:
                clave = en_vuelo.pop(futuro)
                info = estado["partidas"][clave]
                try:
                    resultado = futuro.result()
                except Exception as e:  # noqa: BLE001
                    resultado = {"estado": "red", "error": f"{type(e).__name__}: {e}"}
                aplicar_resultado(estado, clave, info, resultado, args, corrida)
                if resultado["estado"] == "procesada":
                    procesadas_corrida += 1
                guardar_estado(estado_ruta, estado)
            if pendientes:
                for futuro in pendientes:
                    clave = en_vuelo.pop(futuro, None)
                    if clave and estado["partidas"][clave].get("estado") == "en_curso":
                        estado["partidas"][clave]["estado"] = "espera"
                        estado["partidas"][clave]["siguiente"] = 0
                guardar_estado(estado_ruta, estado)
                log("quedaron partidas en vuelo: vuelven a la cola al arrancar")

    segundos = round(time.monotonic() - m_inicio, 1)
    resumen = {
        "inicio": corrida["inicio"],
        "fin": iso(),
        "segundos": segundos,
        "minutos": round(segundos / 60.0, 2),
        "partidas_procesadas": corrida["procesadas"],
        "partidas_404": corrida["404"],
        "partidas_fallidas": corrida["fallidas"],
        "partidas_descubiertas": corrida["descubiertas"],
        "mb": round(corrida["bytes"] / 1e6, 2),
        "jobs": cliente.contadores["jobs"],
        "peticiones": cliente.contadores["peticiones"],
        "errores_429": cliente.contadores["429"],
        "ritmo_partidas_min": round(corrida["procesadas"] / max(segundos / 60.0, 0.01), 2),
        "en_espera": estado["contadores"].get("en_espera", 0),
        "acumulado": estado["contadores"],
        "por_partida_mb": round(
            corrida["bytes"] / max(corrida["procesadas"], 1) / 1e6, 3),
        "segundos_por_partida_media": round(
            sum(corrida["segundos_partida"]) / max(len(corrida["segundos_partida"]), 1), 1),
        "espacio_libre_gb": round(shutil.disk_usage(salida).free / 1e9, 1),
    }
    estado["ultima_corrida"] = resumen
    guardar_estado(estado_ruta, estado)
    resumen_ruta.parent.mkdir(parents=True, exist_ok=True)
    resumen_ruta.write_text(json.dumps(resumen, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    log("resumen: " + json.dumps(
        {k: resumen[k] for k in ("partidas_procesadas", "partidas_404", "partidas_fallidas",
                                 "partidas_descubiertas", "mb", "ritmo_partidas_min")},
        ensure_ascii=False))
    return 0


def extraer_y_cerrar(cliente: Cliente, match: int, info: dict, carpeta: Path,
                     args) -> dict:
    try:
        resultado = extraer(cliente, match, carpeta, args)
        escribir_meta(carpeta, match, info, resultado)
        resultado["estado"] = "procesada"
        return resultado
    except Error404 as e:
        return {"estado": "404", "error": str(e)}
    except ErrorFatal as e:
        return {"estado": "fallida", "error": str(e)}
    except ErrorTemporal as e:
        return {"estado": "red", "error": str(e)}


def aplicar_resultado(estado: dict, clave: str, info: dict, resultado: dict,
                      args, corrida: dict) -> None:
    ahora = time.time()
    if resultado["estado"] == "procesada":
        info.update(
            estado="procesada",
            bytes=resultado["bytes"],
            filas=resultado["filas"],
            completada=iso(),
            ultimo_error=None,
        )
        corrida["procesadas"] += 1
        corrida["bytes"] += int(resultado["bytes"])
        corrida["segundos_partida"].append(resultado["segundos"])
        log(f"  {clave}: OK {resultado['filas']} filas, "
            f"{resultado['bytes'] / 1e6:.2f} MB, {resultado['segundos']:.0f}s")
        return
    if resultado["estado"] == "404":
        info["intentos_demo"] = int(info.get("intentos_demo") or 0) + 1
        info["ultimo_error"] = resultado["error"][:400]
        if info["intentos_demo"] >= args.max_intentos_demo:
            info["estado"] = "404"
            corrida["404"] += 1
            log(f"  {clave}: 404 definitivo tras {info['intentos_demo']} intentos")
        else:
            info["estado"] = "espera"
            info["siguiente"] = ahora + args.espera_404_min * 60.0
            log(f"  {clave}: sin demo (intento {info['intentos_demo']}), "
                f"reintento en {args.espera_404_min:.0f} min")
        return
    if resultado["estado"] == "fallida":
        info["estado"] = "fallida"
        info["ultimo_error"] = resultado["error"][:400]
        corrida["fallidas"] += 1
        log(f"  {clave}: FALLO {resultado['error'][:200]}")
        return
    # red
    info["fallos_red"] = int(info.get("fallos_red") or 0) + 1
    info["ultimo_error"] = resultado["error"][:400]
    if info["fallos_red"] >= args.max_fallos_red:
        info["estado"] = "fallida"
        corrida["fallidas"] += 1
        log(f"  {clave}: FALLO tras {info['fallos_red']} errores de red")
    else:
        info["estado"] = "espera"
        espera = min(600.0, 30.0 * (2 ** (info["fallos_red"] - 1)))
        info["siguiente"] = ahora + espera
        log(f"  {clave}: error de red ({resultado['error'][:120]}), "
            f"reintento en {espera:.0f}s")


if __name__ == "__main__":
    sys.exit(main())
