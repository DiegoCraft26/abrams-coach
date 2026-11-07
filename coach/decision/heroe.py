"""Datos por héroe, en archivos y no en el código.

Hoy solo hay Abrams: los hitos de almas, las fases por coste y la apertura vivían escritos
dentro de `coach/decision/patrones.py` y `coach/motor.py`, así que añadir un héroe obligaba
a tocar el motor. Ahora cada héroe es un JSON en `data/heroes/` con su fuente y su fecha.

Si el archivo falta o está roto, se usan los valores de Abrams: la app nunca se queda sin
funcionar por un dato opcional.
"""
import json
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIR = os.path.join(RAIZ, "data", "heroes")

# Respaldo: lo que estaba escrito en el código antes de este cambio.
ABRAMS = {
    "id": 6,
    "nombre": "Abrams",
    "clave": "abrams",
    "apertura": {"items": [], "fuente": "", "fecha": ""},
    "hitos_almas": [[600, 7600], [1500, 25000]],
    "fases": [["EARLY", 8000], ["MID", 13600], ["LATE", 22400]],
    "ritmo_esperado_por_min": 1000,
}

_cache = {}


class Heroe:
    def __init__(self, datos):
        self.datos = datos

    def __getattr__(self, nombre):
        try:
            return self.datos[nombre]
        except KeyError as exc:
            raise AttributeError(nombre) from exc

    @property
    def hitos(self):
        return tuple((float(t), float(a)) for t, a in self.datos.get("hitos_almas")
                     or ABRAMS["hitos_almas"])

    @property
    def fases(self):
        return tuple((str(n), float(v)) for n, v in self.datos.get("fases") or ABRAMS["fases"])

    @property
    def apertura(self):
        return list((self.datos.get("apertura") or {}).get("items") or [])

    def __repr__(self):
        return f"Heroe({self.datos.get('nombre')})"


def cargar(clave="abrams"):
    """Héroe por clave ('abrams'), nombre ('Abrams') o id. Nunca lanza."""
    clave = str(clave or "abrams").strip().lower()
    if clave in _cache:
        return _cache[clave]
    datos = dict(ABRAMS)
    try:
        for nombre_archivo in sorted(os.listdir(DIR)):
            if not nombre_archivo.endswith(".json"):
                continue
            ruta = os.path.join(DIR, nombre_archivo)
            with open(ruta, encoding="utf-8") as f:
                candidato = json.load(f)
            nombre = str(candidato.get("nombre", "")).strip().lower()
            archivo = nombre_archivo[:-5].lower()
            if clave in (nombre, archivo, str(candidato.get("id", ""))):
                datos = {**ABRAMS, **candidato}
                break
    except (OSError, ValueError):
        pass
    heroe = Heroe(datos)
    _cache[clave] = heroe
    return heroe


def disponibles():
    """Claves de los héroes con datos completos."""
    salida = []
    try:
        for nombre_archivo in sorted(os.listdir(DIR)):
            if nombre_archivo.endswith(".json"):
                salida.append(nombre_archivo[:-5])
    except OSError:
        pass
    return salida
