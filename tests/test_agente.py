"""Suite del agente (sin red): credenciales, presupuesto, herramientas y respaldo.

Estilo script: `python3 tests/test_agente.py` sale con nº de fallos y
`pytest -q` la corre vía `test_suite()`. Todo con dobles de prueba.
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from coach.agente import herramientas, presupuesto, proveedor
from coach.agente.presupuesto import Presupuesto
from coach.agente.proveedor import (
    ErrorProveedor,
    ProveedorConRespaldo,
    ProveedorOpenAICompatible,
)


def _fallos_prueba(nombre, condicion, detalle=""):
    """Imprime el resultado y devuelve 0/1."""
    if condicion:
        print(f"  ok {nombre}")
        return 0
    print(f"  FALLA {nombre} {detalle}")
    return 1


# ------------------------------------------------------------------ dobles
class ProveedorFalla:
    def __init__(self, nombre="falla"):
        self.nombre = nombre

    def chat(self, mensajes, herramientas=None, timeout_s=45):
        raise ErrorProveedor(f"{self.nombre}: red caída")


class ProveedorOk:
    def __init__(self, nombre="bueno"):
        self.nombre = nombre

    def chat(self, mensajes, herramientas=None, timeout_s=45):
        return {"choices": [{"message": {"content": "listo"}}]}


class ProveedorErrorDict:
    def __init__(self, nombre="dict-error"):
        self.nombre = nombre

    def chat(self, mensajes, herramientas=None, timeout_s=45):
        return {"error": f"{self.nombre}: proveedor apagado"}


# ------------------------------------------------------------- credenciales
def probar_credenciales():
    fallos = 0
    original = proveedor.RUTA_CREDENCIALES
    try:
        # Archivo inexistente -> None, sin lanzar.
        with tempfile.TemporaryDirectory() as tmp:
            proveedor.RUTA_CREDENCIALES = os.path.join(tmp, "no-existe.yaml")
            fallos += _fallos_prueba(
                "credencial inexistente es None",
                proveedor.leer_credencial("X_API_KEY") is None,
            )

        # Archivo temporal con sección refs y otra sección que no debe leerse.
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".yaml") as f:
            f.write("# comentario\n")
            f.write("otra:\n")
            f.write("  COMMAND_CODE_API_KEY: valor-equivocado\n")
            f.write("refs:\n")
            f.write("  COMMAND_CODE_API_KEY: clave-de-prueba\n")
            f.write("  OTRA_CLAVE: \"con comillas\"\n")
            ruta_tmp = f.name
        try:
            proveedor.RUTA_CREDENCIALES = ruta_tmp
            valor = proveedor.leer_credencial("COMMAND_CODE_API_KEY")
            # Compare sin imprimir la clave: solo longitud y tramo inicial.
            fallos += _fallos_prueba(
                "lee de la sección refs",
                isinstance(valor, str) and len(valor) == len("clave-de-prueba") and valor.startswith("clave"),
            )
            fallos += _fallos_prueba(
                "clave ausente es None",
                proveedor.leer_credencial("NO_EXISTE_XYZ") is None,
            )
            fallos += _fallos_prueba(
                "comillas se retiran",
                proveedor.leer_credencial("OTRA_CLAVE") == "con comillas",
            )
        finally:
            os.unlink(ruta_tmp)
    finally:
        proveedor.RUTA_CREDENCIALES = original
    return fallos


# -------------------------------------------------------------- presupuesto
def probar_presupuesto():
    fallos = 0
    p = Presupuesto(llamadas_min=2, llamadas_sesion=10, cache_s=60, max_tokens=100)
    fallos += _fallos_prueba("recién creado puede llamar", p.puede_llamar() is True)
    p.registrar(50)
    fallos += _fallos_prueba("tras 1 puede llamar", p.puede_llamar() is True)
    p.registrar(30)
    fallos += _fallos_prueba("tras 2 en la ventana ya no puede", p.puede_llamar() is False)
    g = p.gastado
    fallos += _fallos_prueba(
        "gastado registra llamadas y tokens",
        g["llamadas"] == 2 and g["tokens"] == 80 and "desde" in g,
    )
    est = p.estado()
    fallos += _fallos_prueba(
        "estado legible para la UI",
        est["llamadas_minuto"] == 2 and est["limite_minuto"] == 2
        and est["puede_llamar"] is False,
    )

    # Ventana deslizante: si las marcas envejecen (>60 s), vuelve a poder.
    with p._lock:
        p._marca_minuto.clear()
        p._marca_minuto.append(time.time() - 61)
    fallos += _fallos_prueba("ventana deslizante libera a los 60 s", p.puede_llamar() is True)

    # Techo de sesión aunque la ventana esté libre.
    s = Presupuesto(llamadas_min=10, llamadas_sesion=2)
    s.registrar(1)
    s.registrar(1)
    fallos += _fallos_prueba("techo de sesión frena", s.puede_llamar() is False)

    # Caché con expiración.
    c = Presupuesto(cache_s=0.1)
    c.guardar_cache("k", {"v": 1})
    fallos += _fallos_prueba("caché devuelve valor fresco", c.cache("k") == {"v": 1})
    fallos += _fallos_prueba("caché ausente es None", c.cache("no-existe") is None)
    time.sleep(0.15)
    fallos += _fallos_prueba("caché expirada es None", c.cache("k") is None)
    return fallos


# -------------------------------------------------------------- herramientas
def probar_herramientas():
    fallos = 0

    # estado_actual con estado incompleto (nunca lanza, datos faltantes -> None).
    r = herramientas.estado_actual({})
    fallos += _fallos_prueba(
        "estado vacío no inventa",
        r.get("tiempo_s") is None and r.get("almas") is None and r.get("items") is None,
    )
    r = herramientas.estado_actual(None)
    fallos += _fallos_prueba("estado None no lanza", isinstance(r, dict))
    r = herramientas.estado_actual({"t": 600, "yo": {"almas": 3000}})
    fallos += _fallos_prueba(
        "estado parcial resume lo que hay",
        r.get("tiempo_s") == 600 and r.get("almas") == 3000 and r.get("heroe") is None,
    )
    completo = {
        "t": 1200,
        "almas": 5000,
        "yo": {"heroe": "Abrams", "almas": 5000, "oro": 800, "items": ["1", "2"]},
        "enemigos": [{"heroe": "Lash"}, {"heroe": None}, {"heroe": "Lash"}],
        "recomendaciones": [{"nombre": "A"}, {"nombre": "B"}],
    }
    r = herramientas.estado_actual(completo)
    fallos += _fallos_prueba(
        "estado completo resume",
        r.get("heroe") == "Abrams" and r.get("oro") == 800
        and r.get("enemigos") == ["Lash"] and r.get("compras") == ["A", "B"],
    )

    # explicar_recomendacion.
    r = herramientas.explicar_recomendacion({})
    fallos += _fallos_prueba(
        "sin recomendaciones devuelve error",
        r.get("error") == "sin recomendaciones",
    )
    rec = {
        "almas": 2000,
        "recomendaciones": [
            {"nombre": "A", "costo": 1500, "razones": ["r1"]},
            {"nombre": "B", "costo": 2500, "razones": ["r2"]},
            {"nombre": "C", "costo": 3000, "razones": ["r3"]},
            {"nombre": "D", "costo": 4000, "razones": ["r4"]},
        ],
    }
    r = herramientas.explicar_recomendacion(rec)
    fallos += _fallos_prueba(
        "explica la primera con alternativas",
        r.get("nombre") == "A" and r.get("costo") == 1500
        and r.get("razones") == ["r1"] and r.get("alternativas") == ["B", "C"]
        and r.get("alcanza") is True,
    )
    rec["almas"] = 1000
    r = herramientas.explicar_recomendacion(rec)
    fallos += _fallos_prueba("si no alcanza, alcanza es False", r.get("alcanza") is False)

    # historial sin BD.
    r = herramientas.historial(None)
    fallos += _fallos_prueba(
        "historial sin BD devuelve error",
        r.get("error") == "sin base de datos",
    )
    # historial con BD real en memoria.
    try:
        import sqlite3
        from coach.persistencia import db, repos
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        db.migrar(con)
        repos.guardar_partida(con, repos.Partida(match_id=123, heroe="Abrams"))
        con.commit()
        r = herramientas.historial(con, limite=5)
        fallos += _fallos_prueba(
            "historial resume partidas",
            isinstance(r.get("partidas"), list) and len(r["partidas"]) == 1,
        )
        r = herramientas.historial(con, match_id=123)
        fallos += _fallos_prueba(
            "historial resume una partida",
            isinstance(r.get("resumen"), dict) and r["resumen"]["match_id"] == 123,
        )
        con.close()
    except Exception as exc:  # si el entorno no trae sqlite, cuenta como fallo visible
        print(f"  FALLA historial con BD real ({type(exc).__name__})")
        fallos += 1

    # api_query: lista blanca. Para probar "sin salir a la red" se sustituye el
    # acceso a red por una trampa que fallaría si se llamara.
    llamadas_red = {"n": 0}

    def trampa_urlopen(*a, **k):
        llamadas_red["n"] += 1
        raise AssertionError("salió a la red")

    original_urlopen = herramientas.urllib.request.urlopen
    herramientas.urllib.request.urlopen = trampa_urlopen
    try:
        r = herramientas.api_query("/v1/secrets")
        fallos += _fallos_prueba(
            "ruta prohibida rechazada",
            r.get("error") == "ruta no permitida",
        )
        r = herramientas.api_query("/v1/matches/demo/live/query")
        fallos += _fallos_prueba(
            "ruta de stream rechazada",
            r.get("error") == "ruta no permitida",
        )
        fallos += _fallos_prueba(
            "prohibidas no salieron a la red",
            llamadas_red["n"] == 0,
            f"(llamadas={llamadas_red['n']})",
        )
    finally:
        herramientas.urllib.request.urlopen = original_urlopen

    # Ruta permitida sí usa red (aquí con doble que responde 200 simulado).
    class RespuestaFalsa:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ok": true}'

    herramientas.urllib.request.urlopen = lambda *a, **k: RespuestaFalsa()
    try:
        r = herramientas.api_query("/v1/items")
        fallos += _fallos_prueba(
            "ruta permitida consulta",
            r.get("datos") == {"ok": True},
        )
        r = herramientas.api_query("/v1/matches/999/metadata")
        fallos += _fallos_prueba(
            "metadata de partida permitida",
            r.get("datos") == {"ok": True},
        )
    finally:
        herramientas.urllib.request.urlopen = original_urlopen

    # Esquemas OpenAI de las 5 herramientas.
    nombres = sorted(e["function"]["name"] for e in herramientas.ESQUEMAS)
    fallos += _fallos_prueba(
        "esquemas cubren las 5 herramientas",
        nombres == ["api_query", "buscar_web", "estado_actual",
                    "explicar_recomendacion", "historial"],
    )
    fallos += _fallos_prueba(
        "esquemas en formato OpenAI",
        all(e["type"] == "function" and "parameters" in e["function"]
            for e in herramientas.ESQUEMAS),
    )
    return fallos


# -------------------------------------------------------- proveedor respaldo
def probar_respaldo():
    fallos = 0

    # Todos fallan con excepción tipada: no lanza, devuelve {"error": ...}.
    p = ProveedorConRespaldo([ProveedorFalla("a"), ProveedorFalla("b")])
    try:
        r = p.chat([{"role": "user", "content": "hola"}])
        fallos += _fallos_prueba(
            "todos fallan devuelve error, no lanza",
            isinstance(r, dict) and isinstance(r.get("error"), str) and r["error"] != "",
        )
    except Exception as exc:
        print(f"  FALLA respaldo lanzó {type(exc).__name__}")
        fallos += 1
    fallos += _fallos_prueba(
        "guarda el último error",
        p.ultimo_error is not None and "red caída" in p.ultimo_error,
    )

    # Todos devuelven dict con error: tampoco lanza.
    p = ProveedorConRespaldo([ProveedorErrorDict("a"), ProveedorErrorDict("b")])
    r = p.chat([{"role": "user", "content": "hola"}])
    fallos += _fallos_prueba(
        "errores-dict también devuelven error",
        isinstance(r.get("error"), str) and r["error"] != "",
    )

    # El segundo responde: se usa a él.
    p = ProveedorConRespaldo([ProveedorFalla("a"), ProveedorOk("bueno")])
    r = p.chat([{"role": "user", "content": "hola"}])
    fallos += _fallos_prueba(
        "usa el primero que responde",
        isinstance(r.get("choices"), list) and p.ultimo_proveedor == "bueno",
    )

    # Cadena por defecto con los datos exactos pedidos.
    cadena = proveedor.cadena_por_defecto()
    fallos += _fallos_prueba(
        "cadena por defecto en orden",
        [x.nombre for x in cadena] == ["commandcode", "huggingface"]
        and cadena[0].base_url == "https://api.commandcode.ai/provider/v1"
        and cadena[1].modelo == "deepseek-ai/DeepSeek-V4.1-Flash",
    )
    fallos += _fallos_prueba(
        "protocolo ProveedorLLM es estructural",
        isinstance(ProveedorOk(), proveedor.ProveedorLLM),
    )
    fallos += _fallos_prueba(
        "api-compatible satisface el protocolo",
        isinstance(ProveedorOpenAICompatible("https://x", "m", "X", "n"),
                   proveedor.ProveedorLLM),
    )
    return fallos


def main():
    print("agente: credenciales")
    fallos = probar_credenciales()
    print("agente: presupuesto")
    fallos += probar_presupuesto()
    print("agente: herramientas")
    fallos += probar_herramientas()
    print("agente: respaldo")
    fallos += probar_respaldo()
    print("agente:", "OK" if fallos == 0 else f"{fallos} fallos")
    return fallos


def test_suite():
    """Entrada para `pytest -q` (las suites corren también como script)."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
