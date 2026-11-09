"""La visión tiene que ser honesta incluso cuando el modelo no lo es.

Lo que se prueba aquí es lo que protege la decisión de compra: ids que no existen se
descartan, los campos que no se ven van a null, el mismo cuadro no se paga dos veces y
el tope por partida corta antes de vaciar el presupuesto.
"""
import io
import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from coach.agente import vision  # noqa: E402

ITEM_REAL = "1548066885"   # Extended Magazine, está en data/catalogo.json


def test_normaliza_una_respuesta_buena():
    datos = vision.normalizar({
        "fase": "en_partida", "en_partida": True, "espectando": False,
        "heroe": "Abrams", "reloj_s": 423.7, "oro": 1200, "almas": 7600,
        "tienda_abierta": True, "marcador_abierto": False,
        "items": [ITEM_REAL], "slots": {"weapon": 3, "vitality": 4, "spirit": 2},
        "enemigos": [{"heroe": "haze", "almas": 8000, "bajadas": 2, "muertes": 1}],
        "confianza": 0.82, "notas": "tienda abierta",
    })
    assert datos["fase"] == "en_partida"
    assert datos["heroe"] == "abrams"
    assert datos["reloj_s"] == 423
    assert datos["items"] == [ITEM_REAL]
    assert datos["slots"] == {"weapon": 3, "vitality": 4, "spirit": 2}
    assert datos["enemigos"][0]["heroe"] == "haze"
    assert datos["confianza"] == 0.82


def test_descarta_ids_que_no_existen_en_el_catalogo():
    datos = vision.normalizar({"items": ["123", ITEM_REAL, "inventado", None, 999]})
    assert datos["items"] == [ITEM_REAL]


def test_no_repite_items():
    datos = vision.normalizar({"items": [ITEM_REAL, ITEM_REAL]})
    assert datos["items"] == [ITEM_REAL]


def test_lo_que_no_se_ve_queda_en_null():
    datos = vision.normalizar({"fase": "??", "reloj_s": -4, "oro": "mucho",
                               "almas": None, "confianza": 5, "heroe": 7})
    assert datos["fase"] == "desconocida"
    assert datos["reloj_s"] is None
    assert datos["oro"] is None
    assert datos["almas"] is None
    assert datos["heroe"] is None
    assert datos["confianza"] == 0.0


def test_huevo_solo_cuando_dice_que_lo_tiene():
    assert vision.normalizar({"huevo": {"tiene": False}})["huevo"] is None
    assert vision.normalizar({})["huevo"] is None
    huevo = vision.normalizar({"huevo": {"tiene": True, "desde_s": 300,
                                         "almas_estimadas": 400}})["huevo"]
    assert huevo == {"tiene": True, "desde_s": 300, "almas_estimadas": 400}


def test_slots_fuera_de_rango_se_ignoran():
    datos = vision.normalizar({"slots": {"weapon": 9, "vitality": 2, "espiritu": 4}})
    assert datos["slots"] == {"vitality": 2}


def test_una_respuesta_que_no_es_objeto_revienta():
    with pytest.raises(ValueError):
        vision.normalizar(["no", "es", "un", "dict"])


def test_extrae_json_con_cercas_y_con_prosa():
    assert vision._extraer_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert vision._extraer_json('Claro: {"a": 1} y nada más') == {"a": 1}
    with pytest.raises(ValueError):
        vision._extraer_json("no hay nada")


def test_el_jpeg_se_baja_a_lo_que_aguanta_la_api():
    from PIL import Image

    cuadro = Image.new("RGB", (4480, 1440), (10, 12, 16))
    jpeg = vision.cuadro_a_jpeg(cuadro)
    assert jpeg[:2] == b"\xff\xd8"          # cabecera JPEG
    abierto = Image.open(io.BytesIO(jpeg))
    assert max(abierto.size) == vision.LADO_MAX == 640
    # Por encima de ~40 kB la API no contesta a tiempo (medido el 2026-11-09).
    assert len(jpeg) < 40_000


def test_el_recorte_del_juego_deja_fuera_el_escritorio():
    from PIL import Image

    escritorio = Image.new("RGB", (4480, 1440), (0, 0, 0))
    recorte = vision.recorte_juego(escritorio, (1920, 0, 2560, 1440))
    assert recorte.size == (2560, 1440)


def test_sin_caja_el_recorte_es_el_cuadro():
    from PIL import Image

    escritorio = Image.new("RGB", (800, 600), (0, 0, 0))
    assert vision.recorte_juego(escritorio).size == (800, 600)
    assert vision.recorte_juego(escritorio, (1, 2)).size == (800, 600)


class ProveedorFalso:
    """Se hace pasar por el proveedor: cuenta llamadas y devuelve lo que se le diga."""

    def __init__(self, contenido_texto='{"fase": "en_partida", "reloj_s": 100}',
                 fallar=False):
        self.llamadas = 0
        self.texto = contenido_texto
        self.fallar = fallar
        self.ultimo_jpeg = None
        self.ultimo_sistema = None

    def hay_clave(self):
        return True

    def chat_vision(self, imagen, texto, sistema=None, timeout_s=8.0):
        self.llamadas += 1
        self.ultimo_jpeg = imagen
        self.ultimo_sistema = sistema
        if self.fallar:
            raise RuntimeError("la API se cayó")
        return {"choices": [{"message": {"content": self.texto}}],
                "usage": {"total_tokens": 1234}}


def _jpeg_distinto(tono):
    from PIL import Image

    return vision.cuadro_a_jpeg(Image.new("RGB", (640, 360), (tono, 20, 20)))


def test_interpretar_devuelve_estado_y_cobra_tokens():
    vision._CACHE.clear()
    falso = ProveedorFalso()
    tope = vision.TopePartida()
    datos = vision.interpretar(_jpeg_distinto(11), proveedor=falso, tope=tope)
    assert datos["fase"] == "en_partida"
    assert datos["_cache"] is False
    assert datos["_tokens"] == 1234
    assert falso.llamadas == 1
    assert falso.ultimo_jpeg[:2] == b"\xff\xd8"
    assert tope.estado()["cuadros"] == 1


def test_el_mismo_cuadro_no_se_paga_dos_veces():
    vision._CACHE.clear()
    falso = ProveedorFalso()
    jpeg = _jpeg_distinto(22)
    primera = vision.interpretar(jpeg, proveedor=falso)
    segunda = vision.interpretar(jpeg, proveedor=falso)
    assert falso.llamadas == 1
    assert primera["_cache"] is False
    assert segunda["_cache"] is True
    assert segunda["reloj_s"] == primera["reloj_s"]


def test_si_el_proveedor_falla_devuelve_none_y_lo_cuenta():
    vision._CACHE.clear()
    tope = vision.TopePartida()
    assert vision.interpretar(_jpeg_distinto(33), proveedor=ProveedorFalso(fallar=True),
                              tope=tope) is None
    estado = tope.estado()
    assert estado["cuadros"] == 1
    assert estado["fallos"] == 1


def test_el_tope_corta_la_gastadera():
    vision._CACHE.clear()
    falso = ProveedorFalso()
    tope = vision.TopePartida(tope=2)
    assert vision.interpretar(_jpeg_distinto(44), proveedor=falso, tope=tope) is not None
    assert vision.interpretar(_jpeg_distinto(55), proveedor=falso, tope=tope) is not None
    assert vision.interpretar(_jpeg_distinto(66), proveedor=falso, tope=tope) is None
    assert falso.llamadas == 2


def test_avisa_al_70_por_ciento_una_sola_vez():
    tope = vision.TopePartida(tope=10)
    avisos = [tope.gastar()["avisar_70"] for _ in range(10)]
    assert avisos.count(True) == 1
    assert avisos[6] is True     # el séptimo cuadro de diez


def test_sin_clave_no_llama_al_modelo():
    class SinClave(ProveedorFalso):
        def hay_clave(self):
            return False

    vision._CACHE.clear()
    falso = SinClave()
    assert vision.interpretar(_jpeg_distinto(77), proveedor=falso) is None
    assert falso.llamadas == 0


def test_el_contexto_ya_conocido_va_en_el_prompt():
    texto = vision.contexto_texto({"heroe": "abrams", "reloj_s": 300, "items": []})
    assert "heroe=abrams" in texto
    assert "reloj_s=300" in texto
    assert "items=" not in texto      # lista vacía no aporta
    assert vision.contexto_texto(None) == ""
