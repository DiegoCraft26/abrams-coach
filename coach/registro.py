"""Registro de decisiones para aprendizaje posterior."""
import json, os, time

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA = os.path.join(DIR, "salida", "decisiones.jsonl")


def anotar(resultado, estado_dict):
    os.makedirs(os.path.dirname(RUTA), exist_ok=True)
    fila = {
        "ts": time.time(),
        "t": estado_dict.get("t"),
        "heroe": estado_dict.get("heroe"),
        "almas": estado_dict.get("almas"),
        "estado": (estado_dict.get("estado") or {}).get("estado"),
        "recomendado": [r["nombre"] for r in (estado_dict.get("recomendaciones") or [])][:3],
        "venta": (estado_dict.get("venta") or {}).get("nombre"),
        "ms": estado_dict.get("ms"),
    }
    with open(RUTA, "a") as f:
        f.write(json.dumps(fila, ensure_ascii=False) + "\n")
    return fila


def leer_todas():
    if not os.path.exists(RUTA):
        return []
    return [json.loads(l) for l in open(RUTA) if l.strip()]
