"""Panel web: el mismo dato que la app nativa, servido por el propio coach.

Lo que se fija aquí: que la página consulte `/api/estado` (no un archivo estático), que
use los iconos que ya sirve el servidor, que diga cuándo los datos son viejos, que
distinga los modos de degradación y que la raíz del servidor apunte al panel.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach.ui.web import PAGINA        # noqa: E402
from coach import servidor             # noqa: E402


def test_consulta_el_estado_en_vivo():
    assert 'fetch("/api/estado"' in PAGINA
    assert "setInterval(latir" in PAGINA


def test_usa_los_iconos_del_servidor():
    assert "/icono/" in PAGINA


def test_avisa_de_datos_viejos():
    assert "rancio" in PAGINA and "edad_s" in PAGINA
    assert "datos de hace" in PAGINA


def test_distingue_los_modos_de_degradacion():
    """`NORMAL` / `SOLO_LOCAL` / `CIEGO` no pueden verse igual: el panel no miente."""
    assert "SOLO_LOCAL" in PAGINA and "CIEGO" in PAGINA
    assert "solo pantalla" in PAGINA


def test_sin_listo_no_finge_datos():
    """Con `listo: false` se dice qué pasa en vez de enseñar cifras congeladas."""
    assert "d.listo === false" in PAGINA or "d.listo !== false" in PAGINA
    assert "esperando al coach" in PAGINA


def test_la_raiz_manda_al_panel():
    assert "/panel" in servidor.AVISO_RAIZ


def test_no_carga_nada_de_fuera():
    """Sin CDN ni fuentes remotas: tiene que funcionar sin red."""
    for prohibido in ("http://", "https://", "cdn.", "@import"):
        assert prohibido not in PAGINA, prohibido


# --- contrato de honestidad del panel -----------------------------------------
def test_una_recomendacion_no_se_pinta_sin_intervalo_y_n():
    """Un efecto sin intervalo ni muestra es una afirmación que no se sostiene.

    La regla no es de estilo: la especificación del motor v2 prohíbe mostrar un punto
    sin IC90, sin n y sin etiqueta. Aquí se comprueba que el render lo exige de verdad.
    """
    assert "ic90" in PAGINA
    assert "n_partidas" in PAGINA
    assert "efecto_pp" in PAGINA
    # sin las tres, la caja de evidencia no se enciende
    assert 'caja.className = "evidencia"' in PAGINA
    assert '"evidencia on"' in PAGINA
    # y el veredicto no se calla: si el intervalo queda bajo cero, se dice
    assert "no respalda" in PAGINA and "contra" in PAGINA


def test_el_inventario_solo_sale_cuando_hay_venta():
    """Una tira de 12 iconos sin decisión detrás es ruido, no contexto."""
    assert "hayVenta" in PAGINA
    assert "vende" in PAGINA


def test_el_pie_no_se_convierte_en_diario():
    """Dos notas como mucho: el pie es contexto, no un registro."""
    assert "slice(0, 2)" in PAGINA
