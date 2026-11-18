#!/usr/bin/env python3
"""Inyección de un efecto conocido: ¿la maquinaria ve lo que dice no ver?

Por qué existe
--------------
El informe concluye «ningún ítem con efecto demostrado». Antes de firmar eso hay que
probar que el estimador **sí** detecta un efecto cuando existe, a este tamaño de muestra.
Si no lo detectara, «no hay efecto» sería una frase sobre el estimador, no sobre el juego.

Qué hace
--------
Toma el corpus real (mismas compras, mismos estados, mismos parches) y **reemplaza el
resultado** por uno simulado, con un valor por partida (como en la realidad):

    p_m = taza_ganadora_del_parche + δ · 1{Abrams compró el ítem sembrado}
    Y*_m ~ Bernoulli(p_m)

Se corre el mismo estimador, con la misma especificación y los mismos errores agrupados por
partida, y se mide:

1. **Recuperación**: τ̂ medio del ítem sembrado contra δ (si sale la mitad, el contraste
   contra la banda está atenuando: un efecto de partida se reparte entre las ~16 compras
   del build, el hueco de identificación que el v3 ya había declarado).
2. **Cobertura**: fracción de IC95 que contienen δ.
3. **Falsos positivos**: fracción de ítems **no** sembrados con |z| > 1,96.
4. **Fuga**: τ̂ medio de los ítems que suelen comprarse junto con el sembrado.

Uso:
    python3 herramientas/lab/inyeccion_parches.py --items "Spirit Snatch,Crushing Fists" \
        --deltas 0.06,0.10 --replicas 30
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from modelo_parches import (Diseno, ajustar_corte, cargar_catalogo, cargar_corpus,  # noqa: E402
                            CORPUS, MIN_N_AGREGADO)


def correr(d, dis, idx, uniq, inv, base, p_m, a_sem, delta, coste, nombre, args):
    taus, cubre, fp, co_taus = [], 0, [], collections.defaultdict(list)
    partidas_sem = set(d["match_id"][d["item"] == a_sem].tolist())
    junto = collections.Counter(
        int(a) for a, m in zip(d["item"].tolist(), d["match_id"].tolist())
        if m in partidas_sem and int(a) != a_sem)
    co = [a for a, _ in junto.most_common(5) if a in dis.pos]
    for rep in range(args.replicas):
        rng = np.random.default_rng(args.semilla + rep)
        y_m = (rng.random(len(uniq)) < p_m).astype(float)
        dis.y = y_m[inv]
        t = ajustar_corte(dis, idx, MIN_N_AGREGADO, coste)
        if a_sem not in t:
            continue
        v = t[a_sem]
        taus.append(100 * v["tau"])
        ic = (100 * (v["tau"] - 1.959964 * v["se"]), 100 * (v["tau"] + 1.959964 * v["se"]))
        cubre += int(ic[0] <= 100 * delta <= ic[1])
        for b, w in t.items():
            if b != a_sem:
                fp.append(abs(w["tau"] / w["se"]) > 1.96 if w["se"] > 0 else False)
        for b in co:
            if b in t:
                co_taus[b].append(100 * t[b]["tau"])
    return {
        "n_replicas": len(taus),
        "tau_medio_pp": round(float(np.mean(taus)), 3),
        "tau_sd_pp": round(float(np.std(taus, ddof=1)), 3),
        "recuperacion_pct": round(100 * float(np.mean(taus)) / (100 * delta), 1),
        "sesgo_pp": round(float(np.mean(taus)) - 100 * delta, 3),
        "cobertura_ic95": round(100 * cubre / len(taus), 1),
        "falsos_positivos_pct": round(100 * float(np.mean(fp)), 2),
        "fuga_pp": {nombre.get(b, str(b)): round(float(np.mean(v)), 2)
                    for b, v in co_taus.items()},
    }


def main():
    ap = argparse.ArgumentParser(description="Inyección de efecto conocido")
    ap.add_argument("--corpus", default=CORPUS)
    ap.add_argument("--items", default="Spirit Snatch,Crushing Fists,Extra Regen")
    ap.add_argument("--deltas", default="0.06")
    ap.add_argument("--replicas", type=int, default=30)
    ap.add_argument("--ridge", type=float, default=1.0)
    ap.add_argument("--semilla", type=int, default=11)
    ap.add_argument("--salida", default="/tmp/inyeccion_parches.json")
    args = ap.parse_args()

    d = cargar_corpus(args.corpus)
    nombre, coste = cargar_catalogo()
    nombre_a_id = {v: k for k, v in nombre.items()}
    dis = Diseno(d, 30, "bins")
    dis.pen[:dis.P] = args.ridge
    idx = np.arange(len(d["item"]))
    n_it = dis.n_por_item(idx)

    mid = d["match_id"]
    uniq, inv = np.unique(mid, return_inverse=True)
    parche_de = {}
    for m, p in zip(mid.tolist(), d["parche"].tolist()):
        parche_de.setdefault(m, p)
    parche_m = np.array([parche_de[int(m)] for m in uniq])
    taza = {}
    for p in set(parche_m.tolist()):
        taza[p] = float(d["y"][np.isin(mid, uniq[parche_m == p])].mean())
    base = np.array([taza[p] for p in parche_m])

    resultados, tabla = {}, []
    for it_nombre in args.items.split(","):
        a_sem = nombre_a_id[it_nombre.strip()]
        compro_m = np.zeros(len(uniq), bool)
        compro_m[np.unique(inv[d["item"] == a_sem])] = True
        for delta in [float(x) for x in args.deltas.split(",")]:
            p_m = np.clip(base + delta * compro_m, 0.02, 0.98)
            r = correr(d, dis, idx, uniq, inv, base, p_m, a_sem, delta,
                       coste, nombre, args)
            r.update({"item": it_nombre.strip(), "item_id": a_sem,
                      "delta_pp": 100 * delta, "n_compras": int(n_it.get(a_sem, 0))})
            resultados["%s|%.2f" % (it_nombre.strip(), delta)] = r
            tabla.append(r)
    dis.y = d["y"]
    with open(args.salida, "w", encoding="utf-8") as f:
        json.dump({"ridge": args.ridge, "replicas": args.replicas,
                   "resultados": resultados}, f, ensure_ascii=False, indent=1)

    print("%-16s %5s %6s %9s %8s %8s %8s" %
          ("item", "n", "delta", "tau_pp", "recup.%", "cob.%", "FP%"))
    for r in tabla:
        print("%-16s %5d %6.2f %+9.2f %8.1f %8.1f %8.1f"
              % (r["item"], r["n_compras"], r["delta_pp"], r["tau_medio_pp"],
                 r["recuperacion_pct"], r["cobertura_ic95"], r["falsos_positivos_pct"]))
    for r in tabla:
        if r["fuga_pp"]:
            print("  fuga %-16s δ=%.2f: %s" % (r["item"], r["delta_pp"], r["fuga_pp"]))
    print("-> %s" % args.salida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
