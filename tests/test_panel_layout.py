"""Contrato de layout y tema del panel web.

Por qué existe: la auditoría de noviembre encontró que el panel se estiraba a 1 251 px
para ~450 px de texto, que tenía siete tamaños de letra y que el color del web no era el
del tema GTK. La auditoría de UI del 2026-11-18 cerró el contrato: **una columna de 640
y siete zonas**, cada una con una decisión detrás. Estos tests fijan lo que se mide, no
lo que se siente:

    layout   una sola columna de 640 px
    tipos    la rampa 12/14/20/30 (y ningún tamaño de la lista negra)
    paleta   los mismos tokens que `coach/ui/tema.css`
    estados  el aviso de «sin coach» con altura reservada

Si alguien los rompe, falla aquí antes de que se vea en la partida.
"""
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach.ui.web import PAGINA        # noqa: E402

TEMA = os.path.join(RAIZ, "coach", "ui", "tema.css")


def _css():
    return PAGINA.split("<style>", 1)[1].split("</style>", 1)[0]


def test_el_contenido_tiene_ancho_maximo():
    """Una columna de 640: el texto mide ~450 px y la tarjeta se estiraba a 1 251."""
    css = _css()
    assert "max-width:640px" in css
    # no quedan dos columnas: el panel dejó de ser un dashboard de escritorio
    assert "grid-template-columns:minmax(0,640px) minmax(280px,360px)" not in css
    assert re.search(r"main\s*\{[^}]*display:\s*grid", css)


def test_la_rampa_de_tipografia_es_la_del_sistema():
    css = _css()
    for token in ("--t-xs:12px", "--t-sm:14px", "--t-lg:20px", "--t-xl:30px"):
        assert token in css, token


def test_no_hay_tamanos_fuera_de_la_rampa():
    """La lista negra del informe: 9, 11, 13, 16, 17, 18, 22, 24, 28 px."""
    css = _css()
    usados = {int(n) for n in re.findall(r"font-size:\s*(\d+)px", css)}
    permitidos = {10, 12, 14, 20, 30}      # 10 px solo en la marca del slot
    assert not (usados - permitidos), f"tamaños fuera de la rampa: {sorted(usados - permitidos)}"


def test_el_item_a_comprar_es_lo_mas_grande():
    """El ítem que decide la partida manda sobre todo lo demás."""
    css = _css()
    nombre = re.search(r"\.rec \.nombre\s*\{[^}]*font-size:\s*var\((--t-xl)\)", css)
    assert nombre, "el nombre del ítem debe usar el paso xl"


def test_el_reloj_y_el_oro_ya_no_son_protagonistas():
    """El juego ya los muestra en pantalla: duplicarlos a 22 px gastaba la mirada."""
    assert 'id="reloj"' not in PAGINA
    assert 'id="oro"' not in PAGINA


def test_la_paleta_es_la_del_tema_gtk():
    """Un solo producto: los hex del web salen de tema.css, no de la imaginación."""
    with open(TEMA, encoding="utf-8") as f:
        tema = f.read().upper()
    css = _css().upper()
    for token in ("#0A0C10", "#141821", "#1B2029", "#E8ECF3", "#B7C0CE",
                  "#8B95A5", "#5FD08A", "#F2B544", "#EF6B6B", "#7FB6F2"):
        assert token in tema, f"{token} no está en tema.css"
        assert token in css, f"{token} no está en el panel web"


def test_avisa_cuando_no_hay_coach():
    """Sin datos no se finge: se atenúa y se dice qué pasa, con altura reservada."""
    css = _css()
    assert "sin-vivo" in PAGINA
    assert "esperando al coach" in PAGINA
    assert re.search(r"\.vacio\s*\{[^}]*min-height", css)


def test_los_iconos_se_cachean():
    """El icono de un id no cambia: 14 peticiones por segundo eran puro desperdicio."""
    from coach import servidor

    assert "immutable" in servidor.CACHE_ICONO
    with open(os.path.join(RAIZ, "coach", "servidor.py"), encoding="utf-8") as f:
        fuente = f.read()
    assert fuente.count("cache=CACHE_ICONO") >= 2      # ítems y héroes


def test_no_repinta_si_el_estado_no_cambio():
    """Reconstruir el DOM cada segundo impedía cualquier transición."""
    assert "_firma" in PAGINA
    assert "firma === _firma" in PAGINA


def test_repinta_por_nodo_no_por_inner_html_suelto():
    """Reconstruir listas enteras cada segundo impedía cualquier transición."""
    assert "function poner(el, html)" in PAGINA
    assert "_html.set(el.id, html)" in PAGINA
    assert 'poner($("rec")' in PAGINA
    assert "poner(caja," in PAGINA          # la caja de evidencia


def test_avisa_del_enemigo_que_no_se_busca_solo():
    """El motor calculaba `amenazas.peor` y el panel web no lo mostraba."""
    assert "amenazas" in PAGINA and "evitar_solo" in PAGINA
    assert "no busques a" in PAGINA
    assert 'id="amenaza"' in PAGINA
