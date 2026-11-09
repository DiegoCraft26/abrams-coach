"""De nombres a ids: la traducción que evita que el modelo se invente ítems.

El modelo lee «Restorative Shot»; el motor necesita `1548066885`. Si esa traducción se la
pidiéramos al modelo, se inventaría ids. Se hace en local contra el catálogo, y cuando no
hay coincidencia clara se descarta en vez de adivinar.
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from coach.agente import vision_tienda as VT  # noqa: E402

EXTENDED = "1548066885"      # Extended Magazine


def test_normaliza_acentos_y_signos():
    assert VT.normalizar("Espíritu  Ácido!") == "espiritu acido"
    assert VT.normalizar(None) == ""
    assert VT.normalizar("Restorative Shot.") == "restorative shot"


def test_el_nombre_exacto_resuelve():
    tabla = VT.indice()
    assert VT.resolver("Extended Magazine", tabla) == EXTENDED


def test_mayusculas_y_espacios_de_mas_no_estorban():
    tabla = VT.indice()
    assert VT.resolver("  extended   MAGAZINE ", tabla) == EXTENDED


def test_un_nombre_inventado_no_resuelve():
    tabla = VT.indice()
    assert VT.resolver("Sword of the Ancients", tabla) is None


def test_una_letra_cambiada_sigue_resolviendo():
    tabla = VT.indice()
    assert VT.resolver("Extended Magazne", tabla) == EXTENDED


def test_resolver_lista_quita_repetidos_y_apunta_los_que_sobran():
    tabla = VT.indice()
    ids, sobran = VT.resolver_lista(["Extended Magazine", "extended magazine",
                                     "Inventado Total"], tabla)
    assert ids == [EXTENDED]
    assert sobran == ["Inventado Total"]


def test_acepta_items_con_dict():
    ids, _ = VT.resolver_lista([{"nombre": "Extended Magazine"}])
    assert ids == [EXTENDED]


def test_prefiere_comprables():
    catalogo = {
        "1": {"nombre": "Prueba Rara", "comprable": False},
        "2": {"nombre": "Prueba Rara", "comprable": True},
    }
    assert VT.resolver("Prueba Rara", VT.indice(catalogo)) == "2"


def test_la_respuesta_se_traduce_a_ids():
    datos = VT.normalizar_respuesta({
        "tienda_abierta": True,
        "mios": ["Extended Magazine", "Invntado"],
        "se_venden": ["Monster Rounds"],
        "categoria": "arma",
    })
    assert datos["tienda_abierta"] is True
    assert datos["items"] == [EXTENDED]
    assert datos["no_resueltos"] == ["Invntado"]
    assert datos["categoria"] == "arma"
    # Lo que se vende se guarda aparte: no es el inventario de Diego.
    assert "Monster Rounds" not in datos["items"]
    assert len(datos["se_venden"]) == 1


def test_lo_que_se_vende_no_se_confunde_con_lo_tuyo():
    """Regresión del 2026-11-09: el modelo devolvió los 10 componentes en venta como si
    fueran el inventario propio."""
    datos = VT.normalizar_respuesta({
        "tienda_abierta": True,
        "mios": [],
        "se_venden": ["Extra Stamina", "Extra Regen", "Extra Charge"],
    })
    assert datos["items"] == []
    assert len(datos["se_venden"]) == 3
    assert datos["tienda_abierta"] is True


def test_sin_tienda_abierta_no_hay_items():
    datos = VT.normalizar_respuesta({"tienda_abierta": False,
                                     "items": ["Extended Magazine"]})
    assert datos["tienda_abierta"] is False
    assert datos["items"] == [EXTENDED]      # lo leído se conserva, pero no se afirma


def test_respuesta_basura_no_revienta():
    assert VT.normalizar_respuesta(["no", "es", "dict"])["items"] == []
    assert VT.normalizar_respuesta(None)["tienda_abierta"] is False


def test_el_recorte_de_tienda_cabe_en_lo_que_contesta_la_api():
    from PIL import Image

    cuadro = Image.new("RGB", (4480, 1440), (40, 50, 60))
    jpeg = VT.imagen_tienda(cuadro, (1920, 0, 2560, 1440))
    assert jpeg[:2] == b"\xff\xd8"
    abierto = Image.open(__import__("io").BytesIO(jpeg))
    assert abierto.width == 640
    assert len(jpeg) < 40_000      # por encima de ~40 kB la API no contesta


class ProveedorFalso:
    def __init__(self, contenido):
        self.contenido = contenido
        self.llamadas = 0

    def chat_vision(self, imagen, texto, sistema=None, timeout_s=8.0):
        self.llamadas += 1
        return {"choices": [{"message": {"content": self.contenido}}],
                "usage": {"total_tokens": 777}}


def test_leer_jpeg_devuelve_ids_y_tokens():
    falso = ProveedorFalso('{"tienda_abierta": true, "items": ["Extended Magazine"]}')
    datos = VT.leer_jpeg(b"\xff\xd8", falso)
    assert datos["items"] == [EXTENDED]
    assert datos["_tokens"] == 777
    assert datos["fase"] == "en_partida"


def test_leer_jpeg_sin_respuesta_devuelve_none():
    class Caido:
        def chat_vision(self, *a, **k):
            raise RuntimeError("sin red")

    assert VT.leer_jpeg(b"\xff\xd8", Caido()) is None
