#!/usr/bin/env python3
"""Suite de evaluación del lector de marcador (contrato coach.marcador.leer_captura).

Compara lo que devuelve `coach.marcador.leer_captura(ruta)` contra la verdad
terreno de `verdad/*.json` y decide con criterios duros.

Uso:
    python3 tests/test_lectura.py

Códigos de salida:
    0  todo dentro de los umbrales
    1  cualquier fallo: lector ausente o que revienta, verdad terreno ausente o
       incompleta, tiempo de partida distinto, acierto de almas < 80 % o
       evaluación total por encima de 10 s

La suite no inventa verdad terreno ni toca el lector: si falta algo, falla y lo dice.
"""
import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIR_VERDAD = RAIZ / "verdad"
MODULO = "coach.marcador"
UMBRAL_ALMAS = 80.0      # % mínimo de acierto global sobre las almas
LIMITE_SEG = 10.0        # presupuesto total de evaluación (todas las capturas)
POR_EQUIPO = 6
N_ALMAS = POR_EQUIPO * 2
ANCHO = 100
SIN_VERDAD = object()    # la verdad no define esa columna: no puntúa


def _marcas():
    """Símbolos legibles; ASCII si la terminal no aguanta UTF-8."""
    try:
        "\u2713\u2717\u2014".encode(sys.stdout.encoding or "ascii")
    except (LookupError, UnicodeEncodeError, AttributeError):
        return {"ok": "OK", "mal": "XX", "na": "--"}
    return {"ok": "\u2713", "mal": "\u2717", "na": "\u2014"}


M = _marcas()


def _txt(v):
    return M["na"] if v is None else str(v)


def _seg(v):
    return M["na"] if v is None else f"{v} s"


def _num(v):
    """Normaliza el valor leído sin ser blando: texto se compara tal cual."""
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v) if v.is_integer() else v
    item = getattr(v, "item", None)          # escalares de numpy
    if callable(item):
        try:
            return _num(item())
        except Exception:
            return v
    return v


def _rel(ruta):
    try:
        return str(Path(ruta).resolve().relative_to(RAIZ))
    except ValueError:
        return str(ruta)


def _corta(texto, n):
    texto = str(texto)
    return texto if len(texto) <= n else "\u2026" + texto[-(n - 1):]


# --------------------------------------------------------------------- carga

def cargar_lector():
    """Importa el lector. Devuelve (funcion | None, problema | None)."""
    sys.path.insert(0, str(RAIZ))
    try:
        import importlib
        marcador = importlib.import_module(MODULO)
    except Exception as e:                    # no traceback crudo
        return None, (f"no pude importar {MODULO}: {type(e).__name__}: {e}\n"
                      f"    se esperaba el módulo {RAIZ / 'coach' / 'marcador.py'}")
    funcion = getattr(marcador, "leer_captura", None)
    if funcion is None:
        publicas = sorted(n for n in dir(marcador) if not n.startswith("_"))
        return None, ("el módulo coach/marcador.py existe pero no define "
                      "leer_captura(ruta)\n"
                      f"    lo que sí expone: {', '.join(publicas) or '(nada público)'}")
    if not callable(funcion):
        return None, f"coach.marcador.leer_captura existe pero no es invocable ({type(funcion).__name__})"
    return funcion, None


def resolver_captura(archivo):
    """Resuelve 'archivo' de la verdad contra la raíz del proyecto (o verdad/)."""
    p = Path(str(archivo))
    if p.is_absolute():
        return p if p.is_file() else None
    for base in (RAIZ, DIR_VERDAD):
        cand = base / p
        if cand.is_file():
            return cand
    return None


def cargar_verdad():
    """Lee verdad/*.json. Devuelve (entradas, problemas, ignorados)."""
    entradas, problemas, ignorados = [], [], []
    if not DIR_VERDAD.is_dir():
        return [], [f"no existe la carpeta de verdad terreno {DIR_VERDAD}"], []
    for f in sorted(DIR_VERDAD.glob("*.json")):
        try:
            datos = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            problemas.append(f"{f.name}: JSON ilegible ({type(e).__name__}: {e})")
            continue
        if not isinstance(datos, dict):
            problemas.append(f"{f.name}: se esperaba un objeto JSON, llegó {type(datos).__name__}")
            continue
        archivo = datos.get("archivo")
        if not archivo:
            ignorados.append(f.name)          # sin "archivo" no es una captura evaluable
            continue
        faltan = [k for k in ("tiempo_s", "aliados", "enemigos") if k not in datos]
        if faltan:
            problemas.append(f"{f.name}: verdad incompleta, falta {', '.join(faltan)}")
            continue
        imagen = resolver_captura(archivo)
        if imagen is None:
            problemas.append(f"{f.name}: la captura '{archivo}' no existe "
                             f"(busqué en {RAIZ} y en {DIR_VERDAD})")
            continue
        mal = None
        for lado in ("aliados", "enemigos"):
            if not isinstance(datos[lado], (list, tuple)):
                mal = f"{f.name}: '{lado}' debe ser lista, llegó {type(datos[lado]).__name__}"
                break
            if len(datos[lado]) != POR_EQUIPO:
                mal = (f"{f.name}: '{lado}' trae {len(datos[lado])} valores, "
                       f"se esperaban {POR_EQUIPO}")
                break
        if mal:
            problemas.append(mal)
        else:
            entradas.append({"json": f, "datos": datos, "imagen": imagen})
    if not entradas and not problemas:
        problemas.append(f"no hay verdad terreno utilizable en {DIR_VERDAD} "
                         f"(0 .json con 'archivo')")
    return entradas, problemas, ignorados


# ----------------------------------------------------------------- evaluación

def revisar_forma(res):
    """Problemas de forma del dict devuelto por el lector."""
    probs = []
    if not isinstance(res, dict):
        return [f"devolvió {type(res).__name__}, se esperaba dict"]
    for k in ("ok", "motivo", "pantalla", "tiempo_s", "almas",
              "almas_propias", "jugadores", "confianza"):
        if k not in res:
            probs.append(f"al dict le falta la clave {k!r}")
    almas = res.get("almas")
    if not isinstance(almas, dict):
        probs.append("'almas' no es un dict")
    else:
        for lado in ("aliados", "enemigos"):
            v = almas.get(lado)
            if not isinstance(v, (list, tuple)):
                probs.append(f"'almas.{lado}' no es una lista")
            elif len(v) != POR_EQUIPO:
                probs.append(f"'almas.{lado}' trae {len(v)} valores, se esperaban {POR_EQUIPO}")
    jug = res.get("jugadores")
    if "jugadores" in res and (not isinstance(jug, list) or len(jug) != N_ALMAS):
        n = len(jug) if isinstance(jug, list) else type(jug).__name__
        probs.append(f"'jugadores' trae {n}, se esperaban {N_ALMAS}")
    return probs


def _lado(res, nombre):
    if not isinstance(res, dict):
        return []
    almas = res.get("almas")
    if not isinstance(almas, dict):
        return []
    v = almas.get(nombre)
    return list(v) if isinstance(v, (list, tuple)) else []


def comparar(reg):
    """Llena tiempo y las 12 celdas de alma de un registro."""
    datos, res = reg["datos"], reg["res"]
    fallo = reg["error"] is not None
    reg["t_leido"] = _num(res.get("tiempo_s")) if isinstance(res, dict) else None
    reg["t_esp"] = _num(datos.get("tiempo_s"))
    reg["t_ok"] = (not fallo) and reg["t_leido"] == reg["t_esp"]

    celdas, avisos = [], []
    for lado in ("aliados", "enemigos"):
        esp = list(datos.get(lado) or [])
        leido = _lado(res, lado)
        for i in range(POR_EQUIPO):
            if i < len(esp):
                esperado = _num(esp[i])
                leido_v = _num(leido[i]) if i < len(leido) else None
                ok = (not fallo) and (leido_v == esperado)
            else:
                esperado, leido_v, ok = SIN_VERDAD, None, None
            celdas.append({"lado": lado, "i": i, "leido": leido_v,
                           "esperado": esperado, "ok": ok})
    reg["celdas"] = celdas
    reg["avisos"].extend(avisos)


def evaluar(entradas, lector):
    registros = []
    for n, ent in enumerate(entradas, 1):
        reg = {"n": n, "total": len(entradas), "json": ent["json"],
               "imagen": ent["imagen"], "datos": ent["datos"],
               "error": None, "avisos": []}
        t0 = time.perf_counter()
        try:
            res = lector(str(ent["imagen"]))
        except KeyboardInterrupt:
            raise
        except BaseException as e:           # ni sys.exit del lector rompe la suite
            res, reg["error"] = None, f"{type(e).__name__}: {e}"
        reg["seg"] = time.perf_counter() - t0
        reg["res"] = res
        reg["avisos"] = revisar_forma(res) if reg["error"] is None else []
        comparar(reg)
        imprimir_bloque(reg)
        registros.append(reg)
    return registros


# --------------------------------------------------------------- impresión

def _ancho(celdas):
    vals = []
    for c in celdas:
        for v in (c["leido"], c["esperado"]):
            vals.append(M["na"] if v is None else str(v))
    return max([3] + [len(v) for v in vals])


def _fila(etiqueta, valores, w):
    return f"    {etiqueta:<7} " + " ".join(f"{v:>{w}}" for v in valores)


def imprimir_bloque(reg):
    print()
    print(f"[{reg['n']}/{reg['total']}] {_rel(reg['imagen'])}")
    if reg["datos"].get("notas"):
        print(f"  notas         {_corta(reg['datos']['notas'], ANCHO - 18)}")

    marca = M["ok"] if reg["t_ok"] else M["mal"]
    print(f"  tiempo        leído {_seg(reg['t_leido'])}   "
          f"esperado {_seg(reg['t_esp'])}   {marca}")
    if reg["error"]:
        print(f"  excepción     {reg['error']}")
    elif not isinstance(reg["res"], dict):
        print(f"  devolvió      {type(reg['res']).__name__} (se esperaba un dict)")
    else:
        res = reg["res"]
        print(f"  lector        ok={_txt(res.get('ok'))} "
              f"confianza={_txt(res.get('confianza'))} "
              f"motivo={_corta(_txt(res.get('motivo')), ANCHO - 45)}")
    for aviso in reg["avisos"]:
        print(f"  aviso         {aviso}")

    for lado in ("aliados", "enemigos"):
        celdas = [c for c in reg["celdas"] if c["lado"] == lado]
        w = _ancho(celdas)
        print(f"  {lado}")
        print(_fila("col", [c["i"] for c in celdas], w))
        print(_fila("leído", [M["na"] if c["leido"] is None else c["leido"] for c in celdas], w))
        print(_fila("espera", ["?" if c["esperado"] is SIN_VERDAD else
                               (M["na"] if c["esperado"] is None else c["esperado"])
                               for c in celdas], w))
        print(_fila("estado", [M["na"] if c["ok"] is None else
                               (M["ok"] if c["ok"] else M["mal"]) for c in celdas], w))


def imprimir_resumen(registros):
    print()
    print("RESUMEN POR CAPTURA")
    print(f"  {'captura':<44} {'tiempo l/e':>10} {'':2}  {'almas':>7} {'acierto':>8}")
    print("  " + "-" * (ANCHO - 2))
    for r in registros:
        t_txt = f"{_txt(r['t_leido'])}/{_txt(r['t_esp'])}"
        marca = M["ok"] if r["t_ok"] else M["mal"]
        ev = sum(1 for c in r["celdas"] if c["ok"] is not None)
        ac = sum(1 for c in r["celdas"] if c["ok"] is True)
        pct = f"{100.0 * ac / ev:.1f}%" if ev else M["na"]
        print(f"  {_corta(_rel(r['imagen']), 43):<44} {t_txt:>10} {marca:2}  "
              f"{f'{ac}/{ev}':>7} {pct:>8}")


def totales(registros):
    ev = sum(1 for r in registros for c in r["celdas"] if c["ok"] is not None)
    ac = sum(1 for r in registros for c in r["celdas"] if c["ok"] is True)
    t_ok = sum(1 for r in registros if r["t_ok"])
    seg = sum(r["seg"] for r in registros)
    pct = 100.0 * ac / ev if ev else 0.0
    return {"ev": ev, "ac": ac, "pct": pct, "t_ok": t_ok,
            "n": len(registros), "seg": seg}


def main():
    t_inicio = time.perf_counter()
    print("=" * ANCHO)
    print("SUITE DE LECTURA DE MARCADOR  \u00b7  tests/test_lectura.py")
    print(f"  proyecto   {RAIZ}")
    print(f"  verdad     {DIR_VERDAD}")
    print(f"  umbrales   almas >= {UMBRAL_ALMAS:.1f}%  \u00b7  tiempo exacto (0 s)  "
          f"\u00b7  lector <= {LIMITE_SEG:.2f} s")
    print("=" * ANCHO)

    problemas = []

    lector, err_lector = cargar_lector()
    entradas, errs_verdad, ignorados = cargar_verdad()

    if err_lector:
        problemas.append(err_lector)
        print(f"\nLECTOR NO DISPONIBLE\n  {err_lector}")
    if ignorados:
        print(f"  (ignorados por no tener 'archivo': {', '.join(ignorados)})")
    for p in errs_verdad:
        problemas.append(f"verdad terreno: {p}")
        print(f"\nVERDAD TERRENO\n  {p}")

    if err_lector:
        print("\nNo se puede evaluar nada: el contrato no está implementado todavía.")
        print("  Se espera: def leer_captura(ruta) -> dict  en coach/marcador.py")
        print("  Ejemplo de verdad: verdad/partida.json =")
        print('    {"archivo": "salida/calibracion/001.png", "tiempo_s": 460,')
        print('     "aliados": [0,0,0,0,0,0], "enemigos": [0,0,0,0,0,0], "notas": "..."}')
        return terminar([], problemas, t_inicio)

    if not entradas:
        print("\nNada que evaluar: falta la verdad terreno (no la genero yo).")
        print(f"  Deja al menos un *.json en {DIR_VERDAD} con la forma:")
        print('    {"archivo": "salida/calibracion/001.png", "tiempo_s": 460,')
        print('     "aliados": [0,0,0,0,0,0], "enemigos": [0,0,0,0,0,0], "notas": "..."}')
        return terminar([], problemas, t_inicio)

    print(f"\n{len(entradas)} captura(s) a evaluar")
    registros = evaluar(entradas, lector)
    imprimir_resumen(registros)
    return terminar(registros, problemas, t_inicio)


def terminar(registros, problemas, t_inicio):
    tot = totales(registros)
    print()
    print("=" * ANCHO)
    print("VEREDICTO")
    print("-" * ANCHO)

    if registros:
        almas_ok = tot["ev"] > 0 and (tot["ac"] * 100.0) >= (tot["ev"] * UMBRAL_ALMAS)
        tiempos_ok = tot["t_ok"] == tot["n"]
        ritmo_ok = tot["seg"] <= LIMITE_SEG
        print(f"  almas        {tot['ac']}/{tot['ev']} = {tot['pct']:.1f}%   "
              f"(umbral >= {UMBRAL_ALMAS:.1f}%)   {M['ok'] if almas_ok else M['mal']}")
        print(f"  tiempos      {tot['t_ok']}/{tot['n']} exactos   "
              f"(tolerancia 0 s)   {M['ok'] if tiempos_ok else M['mal']}")
        print(f"  duración     {tot['seg']:.2f} s de lector   "
              f"(presupuesto {LIMITE_SEG:.2f} s)   {M['ok'] if ritmo_ok else M['mal']}")
        print(f"  reloj total  {time.perf_counter() - t_inicio:.2f} s (informativo)")

        if not almas_ok:
            problemas.append(f"acierto de almas {tot['pct']:.1f}% por debajo del "
                             f"{UMBRAL_ALMAS:.1f}%")
        if not tiempos_ok:
            malos = [r for r in registros if not r["t_ok"]]
            det = "; ".join(f"{_rel(r['imagen'])}: leído {_txt(r['t_leido'])}, "
                            f"esperado {_txt(r['t_esp'])}" for r in malos[:3])
            resto = f" (+{len(malos) - 3} más)" if len(malos) > 3 else ""
            problemas.append(f"tiempo de partida incorrecto en {len(malos)} de "
                             f"{tot['n']} capturas: {det}{resto}")
        if not ritmo_ok:
            problemas.append(f"la evaluación tardó {tot['seg']:.2f} s, "
                             f"más de {LIMITE_SEG:.2f} s")
    else:
        print("  sin capturas evaluadas")

    if problemas:
        print()
        print("  fallos:")
        for p in problemas:
            print(f"   {M['mal']} {p}")
        print()
        print("  RESULTADO: FALLA  (exit 1)")
        print("=" * ANCHO)
        return 1

    print()
    print("  RESULTADO: PASA  (exit 0)")
    print("=" * ANCHO)
    return 0


if __name__ == "__main__":
    sys.exit(main())
