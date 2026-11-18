"""La tarjeta mínima: ruta, ítem del camino y estados vacíos que no revientan.

Lo que se fija aquí:

- `GET /tarjeta` existe y devuelve HTML con el estado ya renderizado (no una cáscara
  que dependa de que el JS alcance a pintar);
- el HTML contiene el ítem recomendado y los pasos del camino;
- los tiles solo llevan icono y estado: el nombre completo vive en la cabecera y no se
  recorta con puntos suspensivos;
- la cabecera prueba 22/20/18/16 px antes de partir el nombre en dos líneas;
- si falta el icono, el marcador de iniciales está en el HTML y la imagen se quita al
  fallar, así que nunca se ve un `<img>` roto;
- la tarjeta no enseña «faltan N», «te alcanza» ni ETA: el oro del momento llega con
  retraso y no es certeza (regla del dueño, 2026-11-18);
- sin datos (None, dict vacío, `listo: false`, payload con formas raras) la función de
  render no lanza y cae en un estado vacío legible.
"""
import os
import sys
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach import servidor as S            # noqa: E402
from coach.ui import tarjeta               # noqa: E402


ESTADO = {
    "listo": True,
    "t": 1200.0,
    "fuente": "prueba",
    "bolsillo": 2520,
    "decision": {
        "accion": "AHORRAR",
        "modo": "ahorro",
        "bolsillo": 2520,
        "faltan": 680,
        "eta_s": 136,
        "objetivo": {"id": "3791587546", "nombre": "Weighted Shots",
                     "costo": 1600, "costo_lista": 3200, "ahorro": 1600},
        "item": {"id": "3791587546", "nombre": "Weighted Shots",
                 "costo": 1600, "costo_lista": 3200, "ahorro": 1600},
        "motivo": "faltan 680 almas; a tu ritmo son 136 s",
    },
    "recomendaciones": [{
        "id": "3791587546", "nombre": "Weighted Shots", "costo": 1600,
        "costo_lista": 3200, "ahorro": 1600,
    }],
    "camino": [
        {"id": "3791587546", "nombre": "Weighted Shots", "costo": 3200,
         "estado": "ahora"},
        {"id": "465043967", "nombre": "Spirit Strike", "costo": 800,
         "estado": "despues"},
        {"id": "2971868509", "nombre": "Bullet Resist Shredder", "costo": 1600,
         "estado": "despues"},
        {"id": "1252627263", "nombre": "Lifestrike", "costo": 3200,
         "estado": "despues"},
        {"id": "2481177645", "nombre": "Hunter's Aura", "costo": 3200,
         "estado": "despues"},
    ],
}


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read().decode("utf-8")


def test_la_ruta_tarjeta_sirve_el_estado_ya_renderizado():
    """La ruta existe de verdad y la primera pintura trae el ítem, no un esqueleto."""
    S.EST.publicar(dict(ESTADO))
    srv = S.arrancar(puerto=0)
    try:
        puerto = srv.server_address[1]
        estado_http, tipo, cuerpo = _get(f"http://127.0.0.1:{puerto}/tarjeta")
    finally:
        srv.shutdown()
        srv.server_close()

    assert estado_http == 200
    assert "text/html" in tipo
    assert "Weighted Shots" in cuerpo
    assert "Spirit Strike" not in cuerpo      # los tiles no llevan nombres
    assert "3,200 oro" in cuerpo              # precio de lista, no el efectivo
    assert "AHORA" in cuerpo and "DESPUÉS" in cuerpo


def test_el_camino_pinta_los_tres_estados():
    html = tarjeta.pagina({
        "listo": True,
        "recomendaciones": [{"id": "1", "nombre": "Item", "costo": 800}],
        "camino": [
            {"id": "1", "nombre": "Comprado", "estado": "tienes"},
            {"id": "2", "nombre": "Ahora", "estado": "ahora"},
            {"id": "3", "nombre": "Después", "estado": "despues"},
        ],
    }, None)
    assert "COMPRADO" in html
    assert "AHORA" in html
    assert "DESPUÉS" in html


def test_falta_icono_muestra_iniciales_y_no_deja_img_roto():
    html = tarjeta.pagina({
        "listo": True,
        "bolsillo": 800,
        "recomendaciones": [{"id": "999999999", "nombre": "Ghost Item", "costo": 800}],
        "camino": [],
    }, None)
    assert ">GI<" in html or "GI</span>" in html
    assert 'onerror="this.remove()"' in html
    assert '<img src="/icono/999999999"' in html


def test_estado_vacio_no_lanza_y_es_legible():
    for datos in (None, {}, {"listo": False, "mensaje": "esperando datos"},
                  {"recomendaciones": "roto", "camino": [None, 3], "decision": []}):
        html = tarjeta.pagina(datos, None)
        assert "<!DOCTYPE html>" in html
        assert "SIN COACH" in html or "SIN PARTIDA" in html or "SIN COMPRA" in html
        assert "spinner" not in html.lower()


def test_refresca_cada_segundo_y_no_carga_nada_de_fuera():
    html = tarjeta.pagina(ESTADO, None)
    assert 'fetch("/api/estado"' in html
    assert "setInterval(latir, 1000)" in html
    for prohibido in ("http://", "https://", "cdn.", "@import"):
        assert prohibido not in html, prohibido


def test_solo_certeza_no_muestra_faltan_ni_te_alcanza():
    """Regla del dueño (2026-11-18): las almas llegan tarde; no se promete precisión.

    Si alguien vuelve a pintar «faltan 680», «te alcanza» o una ETA en la tarjeta,
    esta prueba falla. El precio que queda es el de lista, que no depende del momento.
    """
    html = tarjeta.pagina(ESTADO, None)
    assert "3,200 oro" in html
    assert "faltan" not in html.lower()
    assert "te alcanza" not in html.lower()
    assert "136 s" not in html
    assert "~" not in html


def test_rancio_dice_la_edad_y_no_finge_frescura():
    html = tarjeta.pagina({**ESTADO, "rancio": True, "edad_s": 23}, 23)
    assert "datos de hace 23 s" in html
    assert "faltan" not in html.lower()


def test_los_tiles_no_llevan_nombres_ni_ellipsis():
    """Los tiles son icono + estado; si vuelve un nombre recortado, esta prueba falla."""
    html = tarjeta.pagina(ESTADO, None)
    for nombre in ("Spirit Strike", "Bullet Resist Shredder",
                   "Lifestrike", "Hunter's Aura"):
        assert nombre not in html, nombre
    assert 'class="n"' not in html
    assert "text-overflow" not in html
    assert "…" not in html


def test_la_cabecera_no_trunca_con_un_nombre_largo():
    largo = "Bullet Resist Shredder"
    datos = {
        **ESTADO,
        "decision": {
            **ESTADO["decision"],
            "objetivo": {"id": "2971868509", "nombre": largo,
                         "costo": 1600, "costo_lista": 1600},
            "item": {"id": "2971868509", "nombre": largo,
                     "costo": 1600, "costo_lista": 1600},
        },
    }
    html = tarjeta.pagina(datos, None)
    assert largo in html
    assert "text-overflow" not in html
    assert "…" not in html
    assert "ajustarNombre" in html
    assert "22, 20, 18, 16" in html


def test_tipografia_explicita_y_versalitas():
    html = tarjeta.pagina(ESTADO, None)
    assert ('"Inter", "Segoe UI Variable", "Segoe UI", system-ui, Roboto, '
            'sans-serif') in html
    assert "font-optical-sizing:auto" in html
    assert "font-variant-numeric:tabular-nums" in html
    assert "letter-spacing" in html


def _luminancia(color):
    canales = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]

    def lineal(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lineal(c) for c in canales)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contraste(a, b):
    l1, l2 = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def test_el_precio_dorado_pasa_aa():
    """El dorado se lee sobre el fondo y sobre la superficie de la tarjeta."""
    assert _contraste("#E9C46A", "#0A0C10") >= 4.5
    assert _contraste("#E9C46A", "#141821") >= 4.5
