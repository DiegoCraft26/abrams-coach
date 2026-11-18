"""El estimador de valor: forma del artefacto y recuperación de un efecto conocido.

La validación estadística completa (sesgo, cobertura, falsos positivos sobre 200
réplicas) vive en `herramientas/lab/validar.py` porque tarda minutos. Aquí se fija lo
que un test tiene que poder correr siempre:

- el artefacto tiene los campos que el panel exige (efecto, IC90, n, etiqueta);
- con un corpus donde el efecto SE CONOCE, el ítem tratado sale arriba y con el signo
  correcto;
- la etiqueta de evidencia respeta los umbrales de la especificación;
- un ítem sin compras no aparece.
"""
import os

import pytest
import sys

import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from _datos import falta  # noqa: E402

pytestmark = pytest.mark.skipif(
    bool(falta("datos/lab.db")),
    reason="requiere datos/lab.db (corpus local, 359 MB), no versionado")
sys.path.insert(0, RAIZ)

from herramientas.lab import estimador, sintetico     # noqa: E402


def _corrida(partidas=6000, bootstrap=24):
    datos, verdad = sintetico.generar(n_partidas=partidas, semilla=99)
    doc = estimador.estimar(datos=datos, cat=sintetico.catalogo(),
                            bootstrap=bootstrap, semilla=5, verbose=False,
                            prob_verdad=verdad["prob"])
    return doc, verdad


def test_el_artefacto_trae_intervalo_muestra_y_etiqueta():
    doc, _ = _corrida()
    assert doc["items"], "sin ítems estimados"
    assert doc["metodo"]["comparables"] is False, "el flag no debe activarse por defecto"
    for item, datos in doc["items"].items():
        assert isinstance(datos["ic90"], list) and len(datos["ic90"]) == 2
        assert datos["ic90"][0] <= datos["ic90"][1]
        assert datos["n"] > 0
        assert datos["etiqueta"] in ("medido", "preliminar", "debil", "sin_senal")
        assert "evalue" in datos and "mde_pp" in datos


def test_las_etiquetas_respetan_los_umbrales():
    doc, _ = _corrida()
    for datos in doc["items"].values():
        n = datos["n"]
        if n >= estimador.N_MEDIDO:
            assert datos["etiqueta"] == "medido"
        elif n >= estimador.N_PRELIMINAR:
            assert datos["etiqueta"] == "preliminar"
        elif n >= 40:
            assert datos["etiqueta"] == "debil"
        else:
            assert datos["etiqueta"] == "sin_senal"


def test_el_item_tratado_sale_arriba_y_con_el_signo_correcto():
    """Con efecto +2 pp inyectado, el estimador tiene que verlo (no tiene que ser exacto)."""
    doc, verdad = _corrida(partidas=20000)
    items = doc["items"]
    orden = sorted(items.items(), key=lambda kv: kv[1]["efecto_pp"], reverse=True)
    mejor = orden[0][0]
    assert mejor == "s1", f"el mejor por efecto fue {mejor}"
    est = items["s1"]["efecto_pp"]
    real = doc["verdad_items"]["s1"]
    assert abs(est - real) < 4.0, (est, real)
    # El ítem con efecto negativo inyectado también tiene que quedar de ese lado.
    negativos = [i for i in items if doc["verdad_items"].get(i, 0) < 0]
    assert negativos, "no se estimó ninguno de los ítems con efecto negativo"
    assert min(items[i]["efecto_pp"] for i in negativos) < 0


def test_nunca_se_publica_una_cifra_sin_muestra():
    doc, _ = _corrida()
    for datos in doc["items"].values():
        assert datos["n"] > 0
        if datos["etiqueta"] == "sin_senal":
            # Por debajo de 40 compras no hay número: la especificación lo prohíbe.
            assert datos["n"] < 40


def test_los_tramos_no_parten_los_peldanos_de_la_tienda():
    """800/1600/3200/6400 caen cada uno en su tramo; los cortes van entre ellos."""
    assert [estimador.tramo_precio(c) for c in (800, 1600, 3200, 6400)] == [0, 1, 2, 3]
    assert estimador.tramo_precio(1200) == 0
    assert estimador.tramo_precio(1201) == 1
    assert estimador.tramo_precio(2500) == 1
    assert estimador.tramo_precio(2501) == 2
    assert estimador.tramo_precio(5000) == 2
    assert estimador.tramo_precio(5001) == 3


def test_comparables_quita_el_escalon_de_precio():
    """Dos ítems del mismo tramo se comparan entre sí, no contra el shortlist caro.

    Con μ = 0.48/0.52 (800) y 0.62/0.66 (6400), el contrafactual del shortlist
    completo hace que los caros parezcan +10 pp; dentro de su tramo, el efecto es
    solo la diferencia entre los dos ítems del tramo (±4 pp).
    """
    mu = np.array([[0.48, 0.52, 0.62, 0.66]], dtype=np.float64)
    frec = np.array([[0.4, 0.1, 0.4, 0.1]], dtype=np.float64)
    tramo = np.array([0, 0, 3, 3], dtype=np.int8)
    completo = estimador._tau(mu, frec)[0]
    restringido = estimador._tau_comparables(mu, frec, tramo)[0]
    assert completo[2] > 0.10, "el escalón de precio debería aparecer con el shortlist completo"
    np.testing.assert_allclose(restringido, [-0.04, 0.04, -0.04, 0.04], atol=1e-12)


def test_un_tramo_sin_alternativa_da_nan_y_el_agregado_lo_omite():
    mu = np.array([[0.50, 0.60]], dtype=np.float64)
    frec = np.array([[0.90, 0.10]], dtype=np.float64)
    tramo = np.array([0, 3], dtype=np.int8)
    tau = estimador._tau_comparables(mu, frec, tramo)
    assert np.isnan(tau[0, 0]) and np.isnan(tau[0, 1])
    n_ea = np.array([[90.0, 10.0]])
    assert np.isnan(estimador._agregar_tau(tau, n_ea)[0]).all()


def test_el_flag_comparables_deja_el_tramo_en_el_artefacto():
    """Integración mínima: el flag no rompe la forma y publica el tramo de cada ítem."""
    datos, _ = sintetico.generar(n_partidas=3000, semilla=99)
    doc = estimador.estimar(datos=datos, cat=sintetico.catalogo(), bootstrap=4,
                            semilla=5, verbose=False, comparables=True)
    assert doc["metodo"]["comparables"] is True
    assert doc["metodo"]["cortes_precio"] == list(estimador.CORTES_PRECIO)
    assert doc["metodo"]["tramos_precio"]
    for fila in doc["items"].values():
        assert "tramo_precio" in fila
        assert fila["tramo_precio"] in (0, 1, 2, 3)
        assert "n_por_franja" in fila
