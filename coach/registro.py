"""Registro de decisiones para aprendizaje posterior."""
import json, os, time

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA = os.path.join(DIR, "salida", "decisiones.jsonl")


def anotar(resultado, estado_dict):
    """Una línea por consulta: entrada (estado_dict) + salida (resultado).

    `resultado` es lo que devuelve analizar(); antes se leía el estado de entrada
    y por eso todas las filas salían con heroe/almas/estado en null.
    """
    os.makedirs(os.path.dirname(RUTA), exist_ok=True)
    est = resultado.get("estado")
    if isinstance(est, dict):
        est = est.get("estado")
    venta = resultado.get("venta")
    if isinstance(venta, dict):
        venta = venta.get("nombre")
    yo = estado_dict.get("yo") or {}
    fila = {
        "ts": time.time(),
        "t": estado_dict.get("t"),
        "heroe": yo.get("heroe"),
        "almas": yo.get("almas"),
        "estado": est,
        "recomendado": [r.get("nombre") for r in (resultado.get("recomendaciones") or [])][:3],
        "venta": venta,
        "ms": resultado.get("ms"),
        "fuente": estado_dict.get("fuente"),
    }
    with open(RUTA, "a") as f:
        f.write(json.dumps(fila, ensure_ascii=False) + "\n")
    return fila


def leer_todas():
    if not os.path.exists(RUTA):
        return []
    return [json.loads(l) for l in open(RUTA) if l.strip()]
