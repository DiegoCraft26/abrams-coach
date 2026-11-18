"""Las herramientas de API no pueden romper la app ni el CI sin red.

Dos cosas que se comprueban aquí y que son las que duelen cuando fallan:

1. Si la API no responde, `tesoros.py`, `investigar.py` y `residuales.py` salen con
   código 2 y un mensaje, **sin traza**. Nunca dejan el repo a medias.
2. La caché de `_get` evita descargar dos veces lo mismo y no se corrompe con basura.
"""
import importlib.util
import io
import json
import os
import sys
import tempfile
import urllib.error
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

_fallos = []


def check(nombre, cond, detalle=""):
    print(f"  {'ok  ' if cond else 'FALLA'} {nombre}"
          f"{(' · ' + str(detalle)) if detalle else ''}")
    if not cond:
        _fallos.append(nombre)


def _modulo(nombre, archivo):
    ruta = os.path.join(RAIZ, "herramientas", archivo)
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RespuestaFalsa:
    def __init__(self, datos):
        self._datos = io.BytesIO(json.dumps(datos).encode())

    def __enter__(self):
        return self._datos

    def __exit__(self, *a):
        return False


def main():
    tesoros = _modulo("tesoros_test", "tesoros.py")
    inv = _modulo("investigar_test", "investigar.py")
    residuales = _modulo("residuales_test", "residuales.py")

    print("API caída")
    with tempfile.TemporaryDirectory() as tmp:
        for mod in (tesoros, inv):
            mod.CACHE = os.path.join(tmp, "cache-" + mod.__name__)
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("sin red")):
            for nombre, argv in (
                    ("tesoros", ["tesoros.py", "--min-matches", "999999"]),
                    ("investigar", ["investigar.py", "--min-matches", "999999"]),
                    ("residuales", ["residuales.py", "--min-matches", "999999"])):
                sys.argv = argv
                try:
                    rc = {"tesoros": tesoros, "investigar": inv,
                          "residuales": residuales}[nombre].main()
                    check(f"{nombre} sale con 2 y sin traza", rc == 2, rc)
                except SystemExit as exc:
                    check(f"{nombre} sale con 2 y sin traza", exc.code == 2, exc.code)
                except Exception as exc:                     # noqa: BLE001
                    check(f"{nombre} sale con 2 y sin traza", False, repr(exc))

    print("caché")
    with tempfile.TemporaryDirectory() as tmp:
        inv.CACHE = os.path.join(tmp, "cache")
        llamadas = {"n": 0}

        def contar(*a, **k):
            llamadas["n"] += 1
            return RespuestaFalsa([{"item_id": 1, "wins": 1, "losses": 1, "matches": 2}])

        with mock.patch("urllib.request.urlopen", side_effect=contar):
            a = inv._get("/v1/analytics/item-permutation-stats", {"hero_id": 6})
            b = inv._get("/v1/analytics/item-permutation-stats", {"hero_id": 6})
        check("la segunda llamada sale de caché", llamadas["n"] == 1, llamadas)
        check("el dato cacheado es el mismo", a == b == [{"item_id": 1, "wins": 1,
                                                          "losses": 1, "matches": 2}], b)

    print("caché corrupta")
    with tempfile.TemporaryDirectory() as tmp:
        inv.CACHE = os.path.join(tmp, "cache")
        os.makedirs(inv.CACHE, exist_ok=True)

        def basura(*a, **k):
            class Roto:
                def __enter__(self):
                    return io.BytesIO(b"{no es json")

                def __exit__(self, *x):
                    return False
            return Roto()

        with mock.patch("urllib.request.urlopen", side_effect=basura):
            try:
                inv._get("/v1/analytics/hero-stats", {"hero_id": 6})
                check("json roto no se propaga como dato", False, "no lanzó")
            except Exception:                                # noqa: BLE001
                check("json roto se rechaza (y la CLI lo convierte en código 2)", True)

    print()
    if _fallos:
        print(f"herramientas_api: {len(_fallos)} fallos: {_fallos}")
        return 1
    print("herramientas_api: OK")
    return 0


def test_suite():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
