#!/usr/bin/env python3
"""¿La riqueza relativa explica el efecto de los ítems caros en franjas tempranas?

Existe para contestar una pregunta concreta con números, no con opinión: si Crushing
Fists sale en +14 pp en los primeros 15 minutos, ¿es porque quien lo compra tan pronto
**ya iba ganando** (iba por delante de los otros 11 en net worth) o el efecto aguanta
incluso entre jugadores igual de ricos?

Tres lecturas, de menos a más exigente:

1. **Descriptiva.** Quien compra el ítem en la franja 0, ¿es más rico que el comprador
   medio de la franja? `nw_rel` mediana, % de «ricos» (≥1.15× la mediana de los 12) y
   winrate crudo. Si no hay selección por riqueza, no hay confusión que corregir.
2. **Contraste crudo dentro del estrato.** Winrate de quien compra el ítem contra el de
   quien compra cualquier otra cosa del shortlist **en la misma franja y la misma cubeta
   de riqueza**. Es la comparación que cualquiera puede reproducir con un `GROUP BY`.
3. **τ estratificado por riqueza.** El mismo AIPW del artefacto, estimado en 9 estratos
   (franja × cubeta) en vez de 3, y reagregado con los pesos de cada franja. Si la
   hipótesis fuera cierta, el τ de la franja 0 tendría que caer hacia el del contraste
   crudo al condicionar.

Además publica el diagnóstico de la propensión: qué fracción de las compras del ítem en
la franja 0 cae en el piso de `ê` (`--piso-e`), porque con un `ê` recortado el peso
1/ê vale 50 y el AIPW deja de ser una comparación entre iguales.

Uso:
    python3 herramientas/lab/diagnostico_riqueza.py
    python3 herramientas/lab/diagnostico_riqueza.py --piso-e 0.05 --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)

from herramientas.lab import corpus, estimador  # noqa: E402

INTERES = ["800008313", "3862866912", "2829638276", "1252627263", "2407781327"]


def _contexto(cat, piso_e):
    """Corpus con inventario y riqueza, shortlist y ê/m̂ ajustados una sola vez."""
    datos = corpus.con_inventario(corpus.cargar(), cat)
    fr = corpus.franja(datos["t"])
    corto = corpus.shortlist(datos)
    corto_global = sorted({i for e in corto for i in corto[e]})
    pos = {item: j for j, item in enumerate(corto_global)}
    accion_idx = np.full(len(datos["item"]), -1, dtype=np.int16)
    dentro = np.isin(datos["item"], corto_global)
    accion_idx[dentro] = [pos[int(i)] for i in datos["item"][dentro]]
    n = len(datos["item"])
    datos = {k: (v[dentro] if isinstance(v, np.ndarray) and len(v) == n else v)
             for k, v in datos.items()}
    fr = fr[dentro]
    accion_idx = accion_idx[dentro]

    if piso_e is not None:
        estimador.E_MIN = float(piso_e)
    e_hat, _ = estimador.propensiones(datos, corto, fr, accion_idx)
    base = estimador._base(datos)
    estaticas = estimador._accion(cat, [datos["ids"][i] for i in corto_global])
    acc = np.hstack([estaticas, np.eye(len(corto_global), dtype=np.float32)])
    validas = accion_idx >= 0
    Xobs = np.hstack([base, acc[accion_idx.clip(0)]])
    beta = estimador.ajustar_logistico(Xobs[validas], datos["y"][validas])
    M = np.empty((len(datos["item"]), len(corto_global)), dtype=np.float32)
    for a in range(len(corto_global)):
        M[:, a] = estimador.predecir(beta, np.hstack([
            base, np.broadcast_to(acc[a], (len(base), len(acc[a])))]))
    return {"datos": datos, "fr": fr, "accion_idx": accion_idx, "e_hat": e_hat,
            "M": M, "beta": beta, "corto_global": corto_global, "pos": pos}


def _tau_por_estrato(ctx, estratos, n_estratos):
    """τ̂ por (estrato, acción) con la parte AIPW de siempre, sin bootstrap.

    Devuelve además el desglose `m̂` (media del modelo) y `corrección` (el término
    (y−m̂)/ê de quien compró), para poder decir de dónde sale cada número.
    """
    datos, M, e_hat, accion_idx = ctx["datos"], ctx["M"], ctx["e_hat"], ctx["accion_idx"]
    k = M.shape[1]
    mu = np.zeros((n_estratos, k), dtype=np.float64)
    frec = np.zeros((n_estratos, k), dtype=np.float64)
    n_ea = np.zeros((n_estratos, k), dtype=np.float64)
    solo_modelo = np.zeros((n_estratos, k), dtype=np.float64)
    correccion = np.zeros((n_estratos, k), dtype=np.float64)
    y = datos["y"].astype(np.float64)
    for e in range(n_estratos):
        sel = estratos == e
        if not np.any(sel):
            continue
        Ms = M[sel].astype(np.float64)
        ys, es, as_ = y[sel], e_hat[sel], accion_idx[sel]
        corr = np.zeros_like(Ms)
        valido = as_ >= 0
        filas = np.nonzero(valido)[0]
        corr[filas, as_[valido]] = (ys[valido] - Ms[filas, as_[valido]]) / es[
            filas, as_[valido]]
        solo_modelo[e] = Ms.mean(axis=0)
        correccion[e] = corr.mean(axis=0)
        mu[e] = solo_modelo[e] + correccion[e]
        cuenta = np.bincount(as_[valido], minlength=k)
        n_ea[e] = cuenta
        frec[e] = cuenta / max(1, cuenta.sum())
    return (estimador._tau(mu, frec), n_ea, frec, mu, solo_modelo, correccion)


def correr(piso_e=None):
    cat = corpus.catalogo()
    ctx = _contexto(cat, piso_e)
    datos, fr, accion_idx, e_hat = (ctx["datos"], ctx["fr"], ctx["accion_idx"],
                                    ctx["e_hat"])
    pos, cg = ctx["pos"], ctx["corto_global"]
    ids = datos["ids"]
    idx_id = {str(ids[i]): i for i in cg}
    riqueza = np.nan_to_num(datos.get("nw_rel"), nan=1.0)
    cub = estimador.cubeta_riqueza(datos)

    # --- 3. τ estratificado: franja×cubeta (9 estratos) y franja sola (3)
    tau9, n9, _, mu9, mod9, cor9 = _tau_por_estrato(ctx, (fr.astype(np.int64) * 3 + cub), 9)
    tau3, n3, frec3, mu3, mod3, cor3 = _tau_por_estrato(ctx, fr.astype(np.int64), 3)

    salida = {"piso_e": float(estimador.E_MIN), "items": {}}
    for item in INTERES:
        if item not in idx_id:
            salida["items"][item] = {"nombre": cat[item]["nombre"],
                                     "nota": "fuera del shortlist"}
            continue
        a = pos[idx_id[item]]
        f0_sel = (fr == 0) & (accion_idx == a)
        por_cubeta = {}
        for c in range(3):
            ee = c                                  # pseudo-estrato de franja 0
            if n9[ee, a] > 0:
                por_cubeta[str(c)] = round(float(tau9[ee, a] * 100.0), 2)
        # marginal de franja 0 con los pesos de la propia franja
        with np.errstate(all="ignore"):
            f0_marg = float((n9[0:3, a] * tau9[0:3, a]).sum() / max(1.0, n9[0:3, a].sum()))
        crudo = {}
        for c in range(3):
            base = (fr == 0) & (cub == c) & (accion_idx >= 0)
            cf = base & (accion_idx == a)
            otro = base & (accion_idx != a)
            if not np.any(cf) or not np.any(otro):
                crudo[str(c)] = None
                continue
            crudo[str(c)] = {
                "n": int(cf.sum()),
                "wr_item": round(float(datos["y"][cf].mean()), 3),
                "wr_otros": round(float(datos["y"][otro].mean()), 3),
                "dif_pp": round(float(100.0 * (datos["y"][cf].mean()
                                               - datos["y"][otro].mean())), 2),
                "rr_mediana_item": round(float(np.median(riqueza[cf])), 3),
                "rr_mediana_otros": round(float(np.median(riqueza[otro])), 3),
            }
        base0 = (fr == 0) & (accion_idx >= 0)
        cf0, otro0 = base0 & (accion_idx == a), base0 & (accion_idx != a)
        e_item = e_hat[f0_sel, a] if np.any(f0_sel) else np.array([np.nan])
        salida["items"][item] = {
            "nombre": cat[item]["nombre"],
            "coste": int(cat[item]["coste"]),
            "franjas": {str(e): int(n3[e, a]) for e in range(3)},
            "tau3_franja0_pp": round(float(tau3[0, a] * 100.0), 2),
            "tau_por_cubeta_franja0_pp": por_cubeta,
            "tau_franja0_marginal_pp": round(f0_marg * 100.0, 2),
            "crudo_franja0": crudo,
            "crudo_franja0_entera": {
                "n": int(cf0.sum()),
                "wr_item": round(float(datos["y"][cf0].mean()), 3),
                "wr_otros": round(float(datos["y"][otro0].mean()), 3),
                "dif_pp": round(float(100.0 * (datos["y"][cf0].mean()
                                               - datos["y"][otro0].mean())), 2),
            },
            "seleccion_franja0": {
                "frac_rico_item": round(float(np.mean(riqueza[f0_sel] >= 1.15)), 3)
                if np.any(f0_sel) else None,
                "frac_rico_franja": round(float(np.mean(riqueza[fr == 0] >= 1.15)), 3),
                "rr_mediana_item": round(float(np.median(riqueza[f0_sel])), 3)
                if np.any(f0_sel) else None,
                "rr_mediana_franja": round(float(np.median(riqueza[fr == 0])), 3),
                "wr_item": round(float(datos["y"][f0_sel].mean()), 3)
                if np.any(f0_sel) else None,
                "wr_franja": round(float(datos["y"][fr == 0].mean()), 3),
            },
            "desglose_franja0_pp": {
                "tau": round(float(tau3[0, a] * 100.0), 2),
                "solo_modelo": round(float(mod3[0, a] * 100.0), 2),
                "correccion": round(float(cor3[0, a] * 100.0), 2),
                "alternative": round(float(
                    ((frec3[0] @ mu3[0] - frec3[0, a] * mu3[0, a])
                     / max(1e-9, 1.0 - frec3[0, a])) * 100.0), 2),
            },
            "propension_franja0": {
                "e_mediana": round(float(np.nanmedian(e_item)), 4),
                "frac_en_piso": round(float(np.mean(e_item <= estimador.E_MIN + 1e-9)), 3),
                "inv_peso_mediano": round(float(1.0 / max(1e-9, np.nanmedian(e_item))), 2),
            },
        }
    composicion = []
    for a in range(len(cg)):
        if n3[0, a] <= 0:
            continue
        composicion.append({
            "item": str(ids[cg[a]]),
            "nombre": cat[ids[cg[a]]]["nombre"],
            "coste": int(cat[ids[cg[a]]]["coste"]),
            "n_franja0": int(n3[0, a]),
            "cuota_en_franja0": round(float(frec3[0, a]), 4),
            "tau_franja0_pp": round(float(tau3[0, a] * 100.0), 2),
            "solo_modelo_pp": round(float(mod3[0, a] * 100.0), 2),
            "correccion_pp": round(float(cor3[0, a] * 100.0), 2),
        })
    salida["composicion_franja0"] = sorted(composicion, key=lambda d: -d["cuota_en_franja0"])
    salida["beta_riqueza"] = round(float(ctx["beta"][8]), 3)
    salida["beta_nw_absoluto"] = round(float(ctx["beta"][3]), 4)
    salida["wr_por_cubeta"] = {
        str(c): round(float(datos["y"][cub == c].mean()), 3) for c in range(3)}
    salida["corr"] = {
        "nw_rel_nw": round(float(np.corrcoef(riqueza, datos["nw"])[0, 1]), 3),
        "nw_rel_y": round(float(np.corrcoef(riqueza, datos["y"])[0, 1]), 3),
        "nw_y": round(float(np.corrcoef(datos["nw"], datos["y"])[0, 1]), 3),
    }
    salida["filas"] = int(len(datos["item"]))
    return salida


def variantes(piso_e=None):
    """τ de franja 0 del ítem caro con tres diseños de riqueza, mismo código y muestra.

    Es la prueba de la hipótesis en su forma más cruda: si la riqueza fuera la confusión,
    quitar TODA la riqueza del modelo tendría que disparar el efecto y ponerla tendría que
    hundirlo. Se mide con la corrección AIPW incluida (el mismo camino del artefacto, sin
    bootstrap) y se informa además el coeficiente del ítem en el logístico, que es donde
    vive el número cuando la corrección es pequeña.
    """
    cat = corpus.catalogo()
    datos = corpus.con_inventario(corpus.cargar(), cat)
    fr = corpus.franja(datos["t"])
    corto = corpus.shortlist(datos)
    cg = sorted({i for e in corto for i in corto[e]})
    pos = {i: j for j, i in enumerate(cg)}
    accion_idx = np.full(len(datos["item"]), -1, dtype=np.int16)
    dentro = np.isin(datos["item"], cg)
    accion_idx[dentro] = [pos[int(i)] for i in datos["item"][dentro]]
    n = len(datos["item"])
    datos = {k: (v[dentro] if isinstance(v, np.ndarray) and len(v) == n else v)
             for k, v in datos.items()}
    fr = fr[dentro]
    accion_idx = accion_idx[dentro]
    ids = datos["ids"]
    idx_id = {str(ids[i]): i for i in cg}
    a_item = pos[idx_id["800008313"]]
    estaticas = estimador._accion(cat, [ids[i] for i in cg])
    acc = np.hstack([estaticas, np.eye(len(cg), dtype=np.float32)])
    validas = accion_idx >= 0
    if piso_e is not None:
        estimador.E_MIN = float(piso_e)

    salida = []
    for nombre, mutar in (
            ("sin ninguna riqueza (nw=0, sin nw_rel)", _sin_riqueza),
            ("solo riqueza absoluta (diseño previo)", _sin_relativa),
            ("absoluta + relativa (diseño nuevo)", _sin_nada)):
        dd = dict(datos)
        mutar(dd)
        e_hat, _ = estimador.propensiones(dd, corto, fr, accion_idx)
        base = estimador._base(dd)
        Xobs = np.hstack([base, acc[accion_idx.clip(0)]])
        beta = estimador.ajustar_logistico(Xobs[validas], dd["y"][validas])
        M = np.empty((len(dd["item"]), len(cg)), dtype=np.float32)
        for a in range(len(cg)):
            M[:, a] = estimador.predecir(beta, np.hstack([
                base, np.broadcast_to(acc[a], (len(base), len(acc[a])))]))
        tau3, n3, _, _, _, _ = _tau_por_estrato(
            {"datos": dd, "M": M, "e_hat": e_hat, "accion_idx": accion_idx},
            fr.astype(np.int64), 3)
        salida.append({
            "diseno": nombre,
            "coef_item_logit": round(float(beta[base.shape[1] + estaticas.shape[1]
                                                 + a_item]), 4),
            "nivel_franja0_pp": round(float(M[fr == 0][:, a_item].mean() * 100.0), 2),
            "tau_franja0_pp": round(float(tau3[0, a_item] * 100.0), 2),
            "n_franja0": int(n3[0, a_item]),
        })
    return {"piso_e": float(estimador.E_MIN), "item": "Crushing Fists",
            "variantes": salida}


def _sin_riqueza(dd):
    for k in ("nw_rel", "nw_med", "nw_pct", "nw_n"):
        dd.pop(k, None)
    dd["nw"] = np.zeros_like(dd["nw"])


def _sin_relativa(dd):
    for k in ("nw_rel", "nw_med", "nw_pct", "nw_n"):
        dd.pop(k, None)


def _sin_nada(dd):
    return dd


def imprimir_variantes(doc):
    print(f"\n{doc['item']}: efecto de franja 0 según qué riqueza entra al modelo")
    print(f"{'diseño':42s} {'coef':>7s} {'nivel':>7s} {'τ f0':>7s} {'n':>5s}")
    for v in doc["variantes"]:
        print(f"{v['diseno']:42s} {v['coef_item_logit']:7.3f} "
              f"{v['nivel_franja0_pp']:7.2f} {v['tau_franja0_pp']:7.2f} "
              f"{v['n_franja0']:5d}")


def imprimir(doc):
    print(f"filas en shortlist: {doc['filas']:,} · piso de ê: {doc['piso_e']}")
    print(f"beta riqueza relativa: {doc['beta_riqueza']} · beta nw absoluto: "
          f"{doc['beta_nw_absoluto']}")
    print(f"correlaciones: {doc['corr']}")
    print(f"winrate por cubeta de riqueza (0 pobre, 1 normal, 2 rico): "
          f"{doc['wr_por_cubeta']}")
    print()
    encabezado = (f"{'ítem':22s} {'τ f0':>7s} {'pob':>7s} {'nor':>7s} {'ric':>7s}"
                  f" {'crudo f0':>9s} {'%rico':>7s} {'ê med':>7s} {'%piso':>6s}")
    print(encabezado)
    print("-" * len(encabezado))
    for item, d in doc["items"].items():
        if "nota" in d:
            print(f"{d['nombre']:22s} {d['nota']}")
            continue
        c = d["tau_por_cubeta_franja0_pp"]
        cr = d["crudo_franja0_entera"]["dif_pp"]
        print(f"{d['nombre']:22s} {d['tau3_franja0_pp']:7.2f} "
              f"{c.get('0', float('nan')):7.2f} {c.get('1', float('nan')):7.2f} "
              f"{c.get('2', float('nan')):7.2f} {cr:9.2f} "
              f"{d['seleccion_franja0']['frac_rico_item']:7.2f} "
              f"{d['propension_franja0']['e_mediana']:7.4f} "
              f"{d['propension_franja0']['frac_en_piso']:6.2f}")


def imprimir_composicion(doc):
    print("\nfranja 0: composición de la alternativa que define τ de cada ítem")
    print(f"{'ítem':22s} {'n':>6s} {'cuota':>6s} {'τ pp':>7s} {'modelo':>7s} {'corr':>6s}")
    for d in doc["composicion_franja0"]:
        print(f"{d['nombre']:22s} {d['n_franja0']:6d} {d['cuota_en_franja0']:6.3f} "
              f"{d['tau_franja0_pp']:7.2f} {d['solo_modelo_pp']:7.2f} "
              f"{d['correccion_pp']:6.2f}")


def main():
    ap = argparse.ArgumentParser(description="Riqueza relativa contra el efecto temprano")
    ap.add_argument("--piso-e", type=float, default=None,
                    help="recorte inferior de ê (por defecto el del estimador)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--composicion", action="store_true",
                    help="tabla de la alternativa de la franja 0 (de dónde sale τ)")
    ap.add_argument("--variantes", action="store_true",
                    help="τ de franja 0 con y sin riqueza en el modelo")
    ap.add_argument("--salida", default="")
    a = ap.parse_args()
    if a.variantes:
        imprimir_variantes(variantes(a.piso_e))
        return 0
    doc = correr(a.piso_e)
    imprimir(doc)
    if a.composicion:
        imprimir_composicion(doc)
    if a.salida:
        with open(a.salida, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)
        print(f"\nescrito {a.salida}")
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
