#!/usr/bin/env python3
"""Verifica que las cifras citadas en el informe salgan del JSON del análisis.

No calcula nada nuevo: recalcula las medianas y pruebas desde
`informes/macro/analisis_final.json` y compara contra los valores escritos en el
informe. Si algo no coincide, sale distinto de cero (para que se note).

Uso (desde la raíz del repo, en el escritorio):
    python3 herramientas/macro/verificar_informe.py
"""
from __future__ import annotations

import json
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

from common import mann_whitney, mediana  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(AQUI))
JSON = os.path.join(RAIZ, "informes", "macro", "analisis_final.json")


def main():
    d = json.load(open(JSON, encoding="utf-8"))
    v = [c for c in d["cuentas"] if c.get("n_ranked_s2", 0) >= 30 and not c.get("sin_serie")]
    rap = [c for c in v if c["sub_neto"] >= 6]
    res = [c for c in v if c["sub_neto"] < 6]
    fallos = []

    def chk(nombre, citado, calculado, tol=0.005):
        if isinstance(citado, float) and isinstance(calculado, float):
            bien = abs(citado - calculado) <= tol
        else:
            bien = citado == calculado
        print(("OK   " if bien else "FALLA") + f" {nombre}: informe={citado} calculado={calculado}")
        if not bien:
            fallos.append(nombre)

    def h10(c):
        return 10.0 * c["n_heroes"] / max(1, c["n_serie_badge"])

    chk("cuentas con historial", 540, len(d["cuentas"]))
    chk("válidas (≥30 rankeadas)", 147, len(v))
    chk("rápidas", 18, len(rap))
    chk("resto", 129, len(res))
    chk("literal ≥3 div / ≥40 partidas", 0, d["criterio"]["literal_3div_40p"])
    chk("literal ≥2 div / ≥40 partidas", 6, d["criterio"]["literal_2div_40p"])

    chk("héroes/10 rápidas", 0.63, round(mediana([h10(c) for c in rap]), 2))
    chk("héroes/10 resto", 1.43, round(mediana([h10(c) for c in res]), 2))
    r = mann_whitney([h10(c) for c in rap], [h10(c) for c in res])
    chk("p héroes/10", 0.0001, round(r["p"], 4), tol=0.0002)
    chk("δ héroes/10", -0.56, round(r["delta"], 2))
    chk("héroes distintos (mediana)", (4.5, 7.0),
        (mediana([c["n_heroes"] for c in rap]), mediana([c["n_heroes"] for c in res])))

    chk("días activos (mediana)", (12.5, 11.0),
        (mediana([c["dias_activos"] for c in rap]), mediana([c["dias_activos"] for c in res])))
    r = mann_whitney([c["dias_activos"] for c in rap], [c["dias_activos"] for c in res])
    chk("p días activos", 0.0016, round(r["p"], 4), tol=0.0002)

    chk("partidas/día rápidas", 5.125, round(mediana([c["partidas_por_dia"] for c in rap]), 3))
    chk("partidas/día resto", 4.0, round(mediana([c["partidas_por_dia"] for c in res]), 2))
    r = mann_whitney([c["partidas_por_dia"] for c in rap], [c["partidas_por_dia"] for c in res])
    chk("p partidas/día", 0.187, round(r["p"], 3), tol=0.002)

    chk("badge de partida (mediana)", (52.0, 61.0),
        (mediana([c["badge_inicio"] for c in rap]), mediana([c["badge_inicio"] for c in res])))
    r = mann_whitney([c["pct_noche_22_04"] for c in rap], [c["pct_noche_22_04"] for c in res])
    chk("p % noche 22–04", 0.12, round(r["p"], 2), tol=0.01)
    chk("sesión media (mediana)", (2.96, 3.08),
        (round(mediana([c["sesion_media"] for c in rap]), 2),
         round(mediana([c["sesion_media"] for c in res]), 2)))

    print()
    if fallos:
        print(f"{len(fallos)} cifra(s) no coinciden: {', '.join(fallos)}")
        return 1
    print("todas las cifras citadas coinciden con analisis_final.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
