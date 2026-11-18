"""Pruebas del estimador v3: la banda, el inventario y la matemática del AIPW.

No tocan la red ni la base: construyen catálogos y tablas mínimos en memoria. El corpus
sintético completo (con verdad conocida) se corre aparte, en `sintetico_v3.py`, porque
cuesta minutos.
"""
from __future__ import annotations

import os
import sys

import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from herramientas.lab import estimador_v3 as ev  # noqa: E402

# Catálogo mínimo: dos 800, un 1 600, un 3 200 y uno con grafo (mejora de dos 800).
CAT = {
    "a800": {"nombre": "A800", "costo": 800, "slot": "weapon", "tier": 1,
             "comprable": True, "activo": False},
    "b800": {"nombre": "B800", "costo": 800, "slot": "vitality", "tier": 1,
             "comprable": True, "activo": False},
    "c800": {"nombre": "C800", "costo": 800, "slot": "spirit", "tier": 1,
             "comprable": True, "activo": False},
    "d1600": {"nombre": "D1600", "costo": 1600, "slot": "weapon", "tier": 2,
              "comprable": True, "activo": False},
    "e3200": {"nombre": "E3200", "costo": 3200, "slot": "spirit", "tier": 3,
              "comprable": True, "activo": False},
    "f6400": {"nombre": "F6400", "costo": 6400, "slot": "weapon", "tier": 4,
              "comprable": True, "activo": False},
    "g800": {"nombre": "G800", "costo": 800, "slot": "weapon", "tier": 1,
             "comprable": False, "activo": False},
}
COMP = {"f6400": ["a800", "b800"]}
COMPRABLES = ["a800", "b800", "c800", "d1600", "e3200", "f6400"]


def _tabla(items, oros, franjas=None, partidas=None, ticks=None):
    n = len(items)
    return {
        "match": np.asarray(partidas if partidas is not None else [1] * n, dtype=np.int64),
        "slot": np.zeros(n, dtype=np.int64),
        "hero": np.zeros(n, dtype=np.int64),
        "tick": np.asarray(ticks if ticks is not None else range(n), dtype=np.int64),
        "t": np.asarray([100.0 * i for i in range(n)], dtype=np.float64),
        "franja": np.asarray(franjas if franjas is not None else [0] * n, dtype=np.int64),
        "item": list(items),
        "coste": np.asarray([CAT[i]["costo"] for i in items], dtype=np.int64),
        "oro": np.asarray(oros, dtype=np.int64),
        "y": np.ones(n, dtype=np.int8),
        "n_alt_50pct": np.full(n, -1, dtype=np.int64),
        "comprado_es_max": np.zeros(n, dtype=np.int64),
        "slot_confianza": np.ones(n, dtype=np.int64),
    }


def test_banda_respeta_precio_y_excluye_lo_comprado():
    """Con 800 de oro y compra de un 800, la banda solo trae 800 que se paguen."""
    arr = _tabla(["a800"], [800])
    m = ev.construir_menus(arr, CAT, COMP, COMPRABLES, verbose=False)
    ini, fin = m["ini"][0], m["ini"][1]
    acc = m["acc"][ini:fin]
    banda = m["banda"][ini:fin]
    ids = {COMPRABLES[j] for j in acc}
    assert ids == {"a800", "b800", "c800"}          # 1 600 no alcanza
    assert "a800" in ids
    assert m["elegido"][0] == ini + list(acc).index(COMPRABLES.index("a800"))
    assert not m["banda"][m["elegido"][0]]           # lo comprado no es su alternativa
    assert sum(banda) == 2                           # b800 y c800


def test_banda_superior_corta_lo_caro_asequible():
    """Con 4 000 de oro, comprar un 800 no debe meter 1 600 en la comparación."""
    arr = _tabla(["a800"], [4000])
    m = ev.construir_menus(arr, CAT, COMP, COMPRABLES, verbose=False)
    acc = m["acc"][m["ini"][0]:m["ini"][1]]
    banda = m["banda"][m["ini"][0]:m["ini"][1]]
    dentro = {COMPRABLES[j] for j, b in zip(acc, banda) if b}
    assert dentro == {"b800", "c800"}
    assert "d1600" in {COMPRABLES[j] for j in acc}    # asequible, pero fuera de banda


def test_inventario_consume_componentes_y_descuenta():
    """Comprar dos 800 abarata el 6 400 con grafo: 6 400 − 1 600 = 4 800."""
    arr = _tabla(["a800", "b800", "f6400"], [800, 800, 4800])
    m = ev.construir_menus(arr, CAT, COMP, COMPRABLES, verbose=False)
    acc = m["acc"][m["ini"][2]:m["ini"][3]]
    ids = {COMPRABLES[j] for j in acc}
    assert "f6400" in ids                             # entra por el descuento
    arr2 = _tabla(["a800", "b800", "f6400"], [800, 800, 4799])
    m2 = ev.construir_menus(arr2, CAT, COMP, COMPRABLES, verbose=False)
    ids2 = {COMPRABLES[j] for j in m2["acc"][m2["ini"][2]:m2["ini"][3]]}
    assert "f6400" not in ids2                        # un oro menos y no entra
    # lo ya comprado no se vuelve a ofrecer mientras siga en inventario
    assert "a800" not in ids2 and "b800" not in ids2
    arr3 = _tabla(["a800", "b800", "f6400", "a800"], [800, 800, 4800, 5000])
    m3 = ev.construir_menus(arr3, CAT, COMP, COMPRABLES, verbose=False)
    acc3 = {COMPRABLES[j] for j in m3["acc"][m3["ini"][2]:m3["ini"][3]]}
    assert "a800" not in acc3                          # en la compra 3 sigue siendo propio
    acc4 = {COMPRABLES[j] for j in m3["acc"][m3["ini"][3]:m3["ini"][4]]}
    assert "a800" in acc4                              # consumido por el 6 400, vuelve al menú


def test_tau_hajek_matematica():
    """τ = media(m̂ − b̂) + Σw(Y−m̂)/Σw, con w = min(1/ê, PESO_MAX)."""
    n, n_acc = 4, 2
    a_obs = np.array([0, 0, 1, 1], dtype=np.int64)
    m_obs = np.array([0.6, 0.5, 0.4, 0.3])
    y = np.array([1.0, 0.0, 1.0, 0.0])
    e_obs = np.array([0.5, 0.25, 0.01, 0.5])
    fila = np.array([0, 0, 1, 1, 2, 2, 3, 3], dtype=np.int32)
    banda = np.array([True, True, True, True, True, True, True, True])
    m_banda = np.array([0.5, 0.55, 0.45, 0.42, 0.4, 0.38, 0.3, 0.28])
    valida = np.ones(n, dtype=bool)
    tau, n_acc_salida, truncados, neff, base_i, res_i, w = ev.tau_por_item(
        m_obs, m_banda, banda, fila, y, e_obs, a_obs, n_acc, valida)
    b = (m_banda.reshape(4, 2)).mean(axis=1)
    w_esp = np.minimum(1.0 / e_obs, ev.PESO_MAX)
    esperado = (m_obs - b) + (y - m_obs) * w_esp / 1.0
    # por ítem: media de base + Σw res/Σw
    for j in range(n_acc):
        sel = a_obs == j
        esp = ((m_obs[sel] - b[sel]).mean()
               + ((y[sel] - m_obs[sel]) * w_esp[sel]).sum() / w_esp[sel].sum())
        assert abs(tau["hajek"][j] - esp) < 1e-12, (tau["hajek"], esp)
    assert truncados == 1                              # la fila con ê = 0,01
    assert np.allclose(w, w_esp)
    assert n_acc_salida.tolist() == [2, 2]
    # el plug-in no lleva corrección
    for j in range(n_acc):
        sel = a_obs == j
        assert abs(tau["plugin"][j] - (m_obs[sel] - b[sel]).mean()) < 1e-12
    # sin normalizar sí la lleva y no coincide
    assert not np.allclose(tau["sin_normalizar"], tau["hajek"])
    _ = esperado


def test_logit_condicional_aprende_lo_mas_caro():
    """Si siempre se elige lo más caro del menú, el coeficiente de `es_max` es > 0."""
    menus = {"acc": np.array([0, 1, 2, 0, 1, 2], dtype=np.int16),
             "fila": np.array([0, 0, 0, 1, 1, 1], dtype=np.int32),
             "ini": np.array([0, 3, 6], dtype=np.int64),
             "coste_c": np.array([800, 1600, 3200]),
             "slot_acc": np.zeros((3, 3), dtype=np.float32)}
    rasgos = ev.rasgos_eleccion(menus)
    elegido = np.array([2, 2], dtype=np.int64)         # el de 3 200 en los dos menús
    beta, lse = ev.ajustar_eleccion(rasgos, menus["fila"], menus["ini"], elegido)
    assert beta[2] > 0                                 # es_max
    prob = np.exp(rasgos @ beta - lse[menus["fila"]])
    assert np.allclose(prob.sum() / 2.0, 1.0, atol=1e-6)
    assert prob[elegido].min() > 0.5
