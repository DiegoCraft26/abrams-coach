#!/usr/bin/env python3
"""Efecto de un ítem **por parche** y agregado, réplica entre parches y banda de badge.

Pregunta que responde
---------------------
¿El efecto de un ítem se sostiene entre parches o es de un parche concreto? Con una sola
ventana de 2.5 h (lab.db) no se podía ni plantear. `datos/historico.db` da 20 parches
(ago-2025 → nov-2026) y 3 988 partidas de Abrams en modo Normal.

Estimando (el del v3, con una simplificación declarada)
-------------------------------------------------------
    τ(a) = media_{i: A_i = a} [ Y_i(a) − (1/|S_i|) Σ_{a'∈S_i} Y_i(a') ]

`S_i` = alternativas **del mismo tramo de precio** que la compra observada: coste de
catálogo entre 0,5× y 1,5× el coste del ítem comprado, sin contar el propio ítem, y
restringidas a los ítems con al menos `min_n` compras en el corte (el shortlist observado).

**La simplificación, y por qué:** `historico.db` no guarda oro líquido. `compras.net_worth`
es el *net worth* en el instante de la compra, cuantizado (muchas compras comparten 10 298
o 47 569), no «lo que podía pagar»: no permite reconstruir el conjunto asequible del v3. Se
cae el filtro de asequibilidad y queda el de **franja de precio**, que es el que evita
reintroducir el precio. Consecuencia declarada: el contrafactual es «otro ítem del mismo
tramo», no «otro ítem que podía pagar».

Se estima con la parte *plug-in* del AIPW del v3 (sin corrección IPW: con ~200 clusters por
parche la corrección pesa más que la señal, y el v3 ya lo midió). `m̂(a|x)` es un modelo
lineal de probabilidad:

    Y_i = α + Σ_a β_a·1{item_i=a} + f(t_i) + g(log net_worth_i) + ranked + parche + ε_i

- **f y g flexibles**: bins de 3 min para `t` y deciles fijos de `log net worth`. Se eligen
  así, y no con el atajo cuadrático, porque el cuadrático **fabrica** efectos (diagnóstico
  en §Sensibilidad: Extra Regen pasa de −5,3 pp a −1,2 pp al flexibilizar). La
  especificación flexible es la que se reporta; cuadrática y spline van aparte.
- `τ̂(a) = β̂_a − Σ_{a'∈Banda(a)} w_{a'} β̂_{a'}`, con `w` = peso por compras del corte.
- Errores estándar **agrupados por partida** (sandwich cluster-robust): cada partida aporta
  ~16 compras con un solo resultado, así que las compras no son independientes.

Prueba que faltaba: réplica entre parches
-----------------------------------------
1. **Split temporal 60/40** (12 parches viejos / 8 nuevos): Spearman entre rankings y
   acuerdo de signo, con n de ítems comunes.
2. **Placebo del mismo periodo**: splits aleatorios 60/40 **estratificados por parche y
   agrupados por partida**. Es el techo de ruido: cuánto se repite el ranking cuando el
   tiempo no cambia. Si el Spearman temporal cae dentro de esa distribución, la falta de
   réplica es tamaño de muestra, no deriva del meta.
3. **Cuatro bloques de 5 parches**: réplica con más muestra por corte (SE ~2,5 pp).
4. **Q de heterogeneidad** por ítem: ¿la dispersión de τ entre parches excede el error de
   muestreo? Es la prueba directa de «efecto de un parche concreto».

Uso:
    python3 herramientas/lab/corpus_parches.py           # primero: corpus
    python3 herramientas/lab/modelo_parches.py --placebo 300 --semilla 7
    python3 herramientas/lab/modelo_parches.py --rapido  # sin placebo, para probar
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import gzip
import json
import math
import os
import re
import sys
import time

import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CORPUS = os.path.join(RAIZ, "datos", "corpus_parches.csv.gz")
CATALOGO = os.path.join(RAIZ, "data", "catalogo.json")
SALIDA = os.path.join(RAIZ, "datos", "modelo_parches.json")

BANDA = (0.5, 1.5)              # franja del v3: ±50 % del coste del ítem comprado
BANDA_ESTRECHA = (0.75, 1.25)   # sensibilidad: solo el mismo tramo de precio
RIDGE_ITEM = 1.0                # cresta de las dummies de ítem (colinealidad de builds)
RIDGE_OTROS = 1e-6
MIN_N_PARCHE = 30               # compras mínimas para estimar un ítem dentro de un parche
MIN_N_AGREGADO = 50             # compras mínimas para el agregado y los splits
MIN_N_BANDA = 50                # compras mínimas por ítem dentro de una banda de badge
BINS_T = 3                      # minutos por bin de tiempo de juego
N_BINS_NW = 10                  # deciles de log net worth
Z95 = 1.959964


# --------------------------------------------------------------------- utilidades
def orden_parche(etiqueta):
    m = re.match(r"(\d{2})-(\d{2})-(\d{4})", etiqueta or "")
    return (int(m.group(3)), int(m.group(1)), int(m.group(2))) if m else (9999, 99, 99)


def cargar_catalogo():
    with open(CATALOGO, encoding="utf-8") as f:
        cat = json.load(f)
    nombre, coste = {}, {}
    for k, v in cat.items():
        i = int(k)
        nombre[i] = v.get("nombre") or str(i)
        if v.get("comprable") and (v.get("costo") or 0) > 0:
            coste[i] = int(v["costo"])
    return nombre, coste


def cargar_corpus(ruta):
    with gzip.open(ruta, "rt", encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    col = lambda k, t=float: np.array([t(x[k]) for x in filas])
    return {
        "match_id": col("match_id", np.int64),
        "slot": col("player_slot", np.int64),
        "parche": np.array([x["parche"] for x in filas]),
        "badge": np.array([-1 if x["badge"] == "" else int(x["badge"]) for x in filas],
                          dtype=np.int64),
        "ranked": np.array([1.0 if x["match_mode"] == "Ranked" else 0.0 for x in filas]),
        "nw": col("net_worth"),
        "t": col("t"),
        "item": col("item_id", np.int64),
        "y": col("ganador"),
    }


def rango_medio(v):
    v = np.asarray(v, float)
    orden = np.argsort(v, kind="mergesort")
    r = np.empty(len(v))
    r[orden] = np.arange(len(v), dtype=float)
    for val in np.unique(v):
        m = v == val
        if m.sum() > 1:
            r[m] = r[m].mean()
    return r


def spearman(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 3:
        return float("nan")
    ra, rb = rango_medio(a), rango_medio(b)
    ra -= ra.mean()
    rb -= rb.mean()
    den = math.sqrt((ra @ ra) * (rb @ rb))
    return float(ra @ rb / den) if den else float("nan")


def wilson(k, n, z=Z95):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, c - h), min(1.0, c + h))


def gammainc_upper(a, x):
    """Q(a,x): gamma incompleta regularizada superior (Numerical Recipes)."""
    if x <= 0:
        return 1.0
    if x < a + 1.0:
        s = 1.0 / a
        t = s
        n = 1
        while abs(t) > abs(s) * 1e-14 and n < 2000:
            t *= x / (a + n)
            s += t
            n += 1
        return 1.0 - s * math.exp(-x + a * math.log(x) - math.lgamma(a))
    b = x + 1.0 - a
    c = 1e300
    d = 1.0 / b
    h = d
    for i in range(1, 2000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < 1e-300:
            d = 1e-300
        c = b + an / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < 1e-14:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def chi2_sf(q, df):
    return gammainc_upper(df / 2.0, max(q, 0.0) / 2.0) if df > 0 else float("nan")


# ------------------------------------------------------------------------ diseño
class Diseno:
    """Matriz X: dummies de ítem + parche + f(t) + g(log net worth) + ranked.

    Se construye una vez por corte y cada ajuste indexa filas. Los ítems con n <
    `min_n_global` no tienen dummy: quedan en la base del modelo.
    """

    def __init__(self, c, min_n_global=30, spec="bins", nw_edges=None):
        self.spec = spec
        self.y = np.asarray(c["y"], float)
        self.cl = np.asarray(c["match_id"], np.int64)
        self.item = np.asarray(c["item"], np.int64)
        cuenta = collections.Counter(self.item.tolist())
        self.items = sorted(a for a, k in cuenta.items() if k >= min_n_global)
        self.pos = {a: k for k, a in enumerate(self.items)}
        self.parches = sorted(set(str(x) for x in c["parche"]), key=orden_parche)
        self.ppos = {p: k for k, p in enumerate(self.parches)}
        self.nw_edges = (np.quantile(np.log(c["nw"]), np.linspace(0, 1, N_BINS_NW + 1))[1:-1]
                         if nw_edges is None else nw_edges)

        n = len(self.item)
        P, Q = len(self.items), len(self.parches)
        base = np.zeros((n, P + Q))
        for r, a in enumerate(self.item):
            k = self.pos.get(int(a))
            if k is not None:
                base[r, k] = 1.0
            base[r, P + self.ppos[str(c["parche"][r])]] = 1.0
        lnw = np.log(np.asarray(c["nw"], float))
        x = np.asarray(c["t"], float) / 60.0
        if spec == "quad":
            ctl = np.column_stack([lnw, lnw ** 2, x, x * x, c["ranked"]])
        elif spec == "spline":
            def bs(v, kn):
                return np.column_stack([np.maximum(v - k, 0.0) for k in kn])
            ctl = np.column_stack([lnw, x,
                                   bs(lnw, [7, 7.5, 8, 8.5, 9, 9.5, 10]),
                                   bs(x, [2, 5, 8, 10, 13, 16, 20, 25]),
                                   c["ranked"]])
        else:
            bt = np.minimum((np.asarray(c["t"], float) // (BINS_T * 60)).astype(int), 20)
            bn = np.searchsorted(self.nw_edges, lnw)
            ctl = np.column_stack([np.eye(21)[bt][:, 1:],
                                   np.eye(N_BINS_NW)[bn][:, 1:],
                                   c["ranked"]])
        self.X = np.hstack([base, ctl])
        self.P = P
        self.n_cols = self.X.shape[1]
        self.pen = np.full(self.n_cols, RIDGE_OTROS)
        self.pen[:P] = RIDGE_ITEM

    def ajustar(self, idx):
        X = self.X[idx]
        yy = self.y[idx]
        cl = self.cl[idx]
        A = X.T @ X + np.diag(self.pen)
        beta = np.linalg.solve(A, X.T @ yy)
        res = yy - X @ beta
        Ainv = np.linalg.inv(A)
        uniq, inv = np.unique(cl, return_inverse=True)
        G = np.zeros((len(uniq), X.shape[1]))
        np.add.at(G, inv, X * res[:, None])
        V = Ainv @ (G.T @ G) @ Ainv
        return beta, V

    def n_por_item(self, idx):
        return collections.Counter(int(a) for a in self.item[idx] if int(a) in self.pos)


def tau_banda(dis, beta, V, n_por_item, coste, min_n, banda=BANDA, ponderado=True):
    """τ̂(a) = β_a − media ponderada de β en la franja; SE exacta del contraste."""
    P = len(dis.items)
    out = {}
    for k, a in enumerate(dis.items):
        ca = coste.get(a, 0)
        if ca <= 0:
            continue
        bj = [j for j in range(P) if j != k
              and banda[0] * ca <= coste.get(dis.items[j], 0) <= banda[1] * ca
              and n_por_item.get(dis.items[j], 0) >= min_n]
        if len(bj) < 2:
            continue
        w = np.array([n_por_item[dis.items[j]] for j in bj], float) if ponderado \
            else np.ones(len(bj))
        w /= w.sum()
        l = np.zeros(P)
        l[k] = 1.0
        l[bj] -= w
        tau = float(l @ beta[:P])
        var = float(l @ V[:P, :P] @ l)
        out[a] = {"tau": tau, "se": math.sqrt(max(var, 0.0)),
                  "banda": len(bj), "n": int(n_por_item.get(a, 0))}
    return out


def ajustar_corte(dis, idx, min_n, coste, banda=BANDA, ponderado=True):
    n_it = dis.n_por_item(idx)
    if not n_it:
        return {}
    beta, V = dis.ajustar(idx)
    t = tau_banda(dis, beta, V, n_it, coste, min_n, banda, ponderado)
    return {a: v for a, v in t.items() if n_it.get(a, 0) >= min_n}


def heterogeneidad(pp):
    est = [(v["tau"], v["se"]) for v in pp.values() if v["se"] > 0]
    if len(est) < 3:
        return None
    m = np.array([e[0] for e in est])
    s = np.array([e[1] for e in est])
    w = 1.0 / s ** 2
    ivw = float((w @ m) / w.sum())
    Q = float((w * (m - ivw) ** 2).sum())
    df = len(est) - 1
    return {"k": len(est), "ivw_pp": round(100 * ivw, 3), "Q": round(Q, 3), "df": df,
            "p": round(chi2_sf(Q, df), 4),
            "sd_tau_pp": round(100 * float(np.std(m, ddof=1)), 3),
            "se_mediana_pp": round(100 * float(np.median(s)), 3),
            "ivw_se_pp": round(100 * float(1 / math.sqrt(w.sum())), 3)}


# ----------------------------------------------------------------------- análisis
def main():
    ap = argparse.ArgumentParser(description="Efecto por ítem, parche, réplica y banda")
    ap.add_argument("--corpus", default=CORPUS)
    ap.add_argument("--salida", default=SALIDA)
    ap.add_argument("--placebo", type=int, default=300)
    ap.add_argument("--semilla", type=int, default=7)
    ap.add_argument("--rapido", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    d = cargar_corpus(args.corpus)
    nombre, coste = cargar_catalogo()
    n = len(d["item"])
    parches = sorted(set(d["parche"].tolist()), key=orden_parche)
    partidas_tot = len(set(d["match_id"].tolist()))
    print("corpus %d compras · %d partidas · %d parches" % (n, partidas_tot, len(parches)))

    dis = Diseno(d, 30, "bins")
    idx_todo = np.arange(n)
    nw_edges = dis.nw_edges
    print("diseño: %d ítems con n>=30 · %d columnas · %d parches"
          % (len(dis.items), dis.n_cols, len(dis.parches)))

    # ---- agregado (parche como efecto fijo)
    agregado = ajustar_corte(dis, idx_todo, MIN_N_AGREGADO, coste)
    n_it = dis.n_por_item(idx_todo)
    partidas_por_item = collections.defaultdict(set)
    for r in range(n):
        a = int(d["item"][r])
        if a in dis.pos:
            partidas_por_item[a].add(int(d["match_id"][r]))
    print("agregado: %d ítems estimados" % len(agregado))

    # ---- por parche
    por_parche = {}
    for p in parches:
        idx = np.where(d["parche"] == p)[0]
        dis_p = Diseno({k: v[idx] for k, v in d.items()}, MIN_N_PARCHE, "bins", nw_edges)
        por_parche[p] = {"n_filas": int(len(idx)),
                         "n_partidas": int(len(set(d["match_id"][idx].tolist()))),
                         "items": ajustar_corte(dis_p, np.arange(len(idx)),
                                                MIN_N_PARCHE, coste)}
    print("por parche: %s" % ", ".join("%s:%d" % (p.split(" ")[0],
                                                  len(por_parche[p]["items"]))
                                       for p in parches))

    # ---- tabla por ítem
    items_orden = sorted(agregado, key=lambda a: -n_it[a])
    filas_item = {}
    for a in items_orden:
        pp = {p: por_parche[p]["items"][a] for p in parches
              if a in por_parche[p]["items"]}
        tau = agregado[a]
        z = tau["tau"] / tau["se"] if tau["se"] > 0 else float("nan")
        filas_item[a] = {
            "item_id": a, "nombre": nombre.get(a, str(a)), "coste": coste.get(a, 0),
            "n": int(n_it[a]), "partidas": len(partidas_por_item[a]),
            "parches_con_muestra": len(pp),
            "tau_pp": round(100 * tau["tau"], 3),
            "se_pp": round(100 * tau["se"], 3),
            "ic95_pp": [round(100 * (tau["tau"] - Z95 * tau["se"]), 3),
                        round(100 * (tau["tau"] + Z95 * tau["se"]), 3)],
            "z": round(z, 3) if math.isfinite(z) else None,
            "banda_alternativas": tau["banda"],
            "Q": heterogeneidad(pp),
            "por_parche": {p: {"tau_pp": round(100 * v["tau"], 3),
                               "se_pp": round(100 * v["se"], 3),
                               "n": int(v["n"])} for p, v in pp.items()},
            "signos_positivos": sum(1 for v in pp.values() if v["tau"] > 0),
        }

    # ---- resumen de estabilidad (responde la pregunta de la entrega)
    def estable(v):
        k = v["parches_con_muestra"]
        if k < 10:
            return False
        frac = max(v["signos_positivos"], k - v["signos_positivos"]) / k
        ic = v["ic95_pp"]
        return frac >= 0.75 and (ic[0] > 0 or ic[1] < 0)

    con_k = [v for v in filas_item.values() if v["parches_con_muestra"] >= 10]
    estables = [v for v in filas_item.values() if estable(v)]
    sin_parche = [v for v in filas_item.values() if v["parches_con_muestra"] == 0]
    con_3 = [v for v in filas_item.values() if v["parches_con_muestra"] >= 3]
    al_menos_3 = [v for v in con_3 if max(v["signos_positivos"],
                                          v["parches_con_muestra"] - v["signos_positivos"]) >= 3]
    sin_flip = [v for v in con_3 if max(v["signos_positivos"],
                                        v["parches_con_muestra"] - v["signos_positivos"])
                == v["parches_con_muestra"]]
    estab = {
        "criterio": "signo igual en >=75 % de los parches con muestra (k>=10) y IC95 "
                    "agregado que excluye el cero",
        "n_items": len(filas_item),
        "n_con_k_ge_10": len(con_k),
        "n_items_estables": len(estables),
        "items_estables": [{"nombre": v["nombre"], "tau_pp": v["tau_pp"],
                            "ic95_pp": v["ic95_pp"], "k": v["parches_con_muestra"],
                            "signos_positivos": v["signos_positivos"]} for v in estables],
        "n_con_3_o_mas_parches": len(con_3),
        "n_items_mismo_signo_en_al_menos_3_parches": len(al_menos_3),
        "n_items_sin_un_solo_cambio_de_signo": len(sin_flip),
        "bar_3_parches_nota": "con 20 parches, 'mismo signo en >=3' lo cumple casi todo "
                              "por azar; no discrimina",
        "n_items_sin_parche": len(sin_parche),
        "items_sin_parche": [v["nombre"] for v in sin_parche],
    }

    # ---- réplica
    corte = 12
    viejo, nuevo = set(parches[:corte]), set(parches[corte:])
    idx_v = np.where(np.isin(d["parche"], list(viejo)))[0]
    idx_n = np.where(np.isin(d["parche"], list(nuevo)))[0]
    t_v = ajustar_corte(dis, idx_v, MIN_N_AGREGADO, coste)
    t_n = ajustar_corte(dis, idx_n, MIN_N_AGREGADO, coste)
    comunes = sorted(set(t_v) & set(t_n))
    esp = spearman([t_v[a]["tau"] for a in comunes], [t_n[a]["tau"] for a in comunes])
    signo = sum(1 for a in comunes if np.sign(t_v[a]["tau"]) == np.sign(t_n[a]["tau"]))
    top_v = sorted(comunes, key=lambda a: -t_v[a]["tau"])[:10]
    top_n = sorted(comunes, key=lambda a: -t_n[a]["tau"])[:10]
    replica = {
        "corte_parches": corte,
        "n_parches_viejo": len(viejo), "n_parches_nuevo": len(nuevo),
        "n_items_comunes": len(comunes),
        "n_items_viejo": len(t_v), "n_items_nuevo": len(t_n),
        "spearman": round(esp, 4),
        "signo_igual": signo, "signo_pct": round(100 * signo / len(comunes), 2),
        "signo_wilson95_pct": [round(100 * x, 2) for x in wilson(signo, len(comunes))],
        "top10_solape": len(set(top_v) & set(top_n)),
        "items": {a: {"tau_viejo_pp": round(100 * t_v[a]["tau"], 3),
                      "tau_nuevo_pp": round(100 * t_n[a]["tau"], 3)}
                  for a in comunes},
    }
    i2v = np.where(np.isin(d["parche"], parches[:10]))[0]
    i2n = np.where(np.isin(d["parche"], parches[10:]))[0]
    u2 = ajustar_corte(dis, i2v, MIN_N_AGREGADO, coste)
    w2 = ajustar_corte(dis, i2n, MIN_N_AGREGADO, coste)
    com2 = sorted(set(u2) & set(w2))
    replica["split_50_50"] = {
        "n_items": len(com2),
        "spearman": round(spearman([u2[a]["tau"] for a in com2],
                                   [w2[a]["tau"] for a in com2]), 4),
        "signo_pct": round(100 * sum(1 for a in com2
                                     if np.sign(u2[a]["tau"]) == np.sign(w2[a]["tau"]))
                           / len(com2), 2),
    }

    bloques = [parches[i:i + 5] for i in range(0, 20, 5)]
    tb = [ajustar_corte(dis, np.where(np.isin(d["parche"], b))[0], MIN_N_AGREGADO, coste)
          for b in bloques]
    pares = []
    for i in range(len(bloques)):
        for j in range(i + 1, len(bloques)):
            com = sorted(set(tb[i]) & set(tb[j]))
            pares.append({"i": i + 1, "j": j + 1, "n_items": len(com),
                          "spearman": round(spearman([tb[i][a]["tau"] for a in com],
                                                     [tb[j][a]["tau"] for a in com]), 4),
                          "signo_pct": round(100 * sum(1 for a in com
                                                       if np.sign(tb[i][a]["tau"]) ==
                                                       np.sign(tb[j][a]["tau"])) / len(com), 2)})
    replica["bloques_5"] = {
        "bloques": ["%s…%s" % (b[0].split(" ")[0], b[-1].split(" ")[0]) for b in bloques],
        "pares": pares,
        "spearman_medio": round(float(np.mean([x["spearman"] for x in pares])), 4),
        "signo_medio": round(float(np.mean([x["signo_pct"] for x in pares])), 2),
    }

    # ---- placebo: splits aleatorios estratificados por parche y agrupados por partida
    if args.placebo > 0 and not args.rapido:
        idx_pp = {p: np.where(d["parche"] == p)[0] for p in parches}
        mid = d["match_id"]
        sp_l, sg_l, nn_l = [], [], []
        for rep in range(args.placebo):
            rng = np.random.default_rng(args.semilla + rep)   # reproducible por réplica
            en_train = np.zeros(n, bool)
            for p in parches:
                ii = idx_pp[p]
                ms = np.unique(mid[ii])
                rng.shuffle(ms)
                k = int(round(len(ms) * 0.6))
                en_train[ii] = np.isin(mid[ii], ms[:k])
            ta = ajustar_corte(dis, np.where(en_train)[0], MIN_N_AGREGADO, coste)
            tbk = ajustar_corte(dis, np.where(~en_train)[0], MIN_N_AGREGADO, coste)
            com = sorted(set(ta) & set(tbk))
            sp_l.append(spearman([ta[x]["tau"] for x in com],
                                 [tbk[x]["tau"] for x in com]))
            sg_l.append(sum(1 for x in com
                            if np.sign(ta[x]["tau"]) == np.sign(tbk[x]["tau"])) / len(com))
            nn_l.append(len(com))
        sp = np.array(sp_l)
        sg = np.array(sg_l)
        replica["placebo"] = {
            "replicas": len(sp_l),
            "spearman_mediana": round(float(np.median(sp)), 4),
            "spearman_p10": round(float(np.percentile(sp, 10)), 4),
            "spearman_p90": round(float(np.percentile(sp, 90)), 4),
            "spearman_pct_temporal": round(float((sp < esp).mean() * 100), 1),
            "signo_mediana": round(float(np.median(sg)) * 100, 2),
            "signo_p10": round(float(np.percentile(sg, 10)) * 100, 2),
            "signo_p90": round(float(np.percentile(sg, 90)) * 100, 2),
            "n_items_mediana": int(np.median(nn_l)),
        }
        print("placebo %d réplicas: Spearman mediana %.3f [p10 %.3f, p90 %.3f]; "
              "temporal en percentil %.1f"
              % (len(sp_l), replica["placebo"]["spearman_mediana"],
                 replica["placebo"]["spearman_p10"], replica["placebo"]["spearman_p90"],
                 replica["placebo"]["spearman_pct_temporal"]))

    # ---- banda de badge
    bv = d["badge"][d["badge"] >= 0]
    q1, q2 = np.percentile(bv, [100 / 3, 200 / 3])
    cortes = [int(q1), int(q2)]
    mb = d["badge"] >= 0
    mascaras = {"bajo": mb & (d["badge"] <= cortes[0]),
                "medio": mb & (d["badge"] > cortes[0]) & (d["badge"] <= cortes[1]),
                "alto": mb & (d["badge"] > cortes[1])}
    bandas, bandas_n = {}, {}
    for etq, m in mascaras.items():
        ib = np.where(m)[0]
        db = Diseno({k: v[ib] for k, v in d.items()}, MIN_N_BANDA, "bins", nw_edges)
        bandas[etq] = ajustar_corte(db, np.arange(len(ib)), MIN_N_BANDA, coste)
        bandas_n[etq] = {"n_filas": int(len(ib)),
                         "n_partidas": int(len(set(d["match_id"][ib].tolist())))}
        print("banda %-5s n=%d partidas=%d ítems=%d"
              % (etq, len(ib), bandas_n[etq]["n_partidas"], len(bandas[etq])))
    com_b = sorted(set(bandas["bajo"]) & set(bandas["medio"]) & set(bandas["alto"]))
    pares_b = {}
    for x, y in (("bajo", "medio"), ("medio", "alto"), ("bajo", "alto")):
        pares_b["%s_%s" % (x, y)] = {
            "n_items": len(com_b),
            "spearman": round(spearman([bandas[x][a]["tau"] for a in com_b],
                                       [bandas[y][a]["tau"] for a in com_b]), 4),
            "signo_pct": round(100 * sum(1 for a in com_b
                                         if np.sign(bandas[x][a]["tau"]) ==
                                         np.sign(bandas[y][a]["tau"])) / len(com_b), 2),
        }
    cambios = [a for a in com_b
               if len({np.sign(bandas[b][a]["tau"]) for b in ("bajo", "medio", "alto")}) > 1]
    banda_res = {
        "cortes_badge": cortes,
        "n_sin_badge": int((~mb).sum()),
        "n_con_badge": int(mb.sum()),
        "n_partidas_sin_badge": len(set(d["match_id"][~mb].tolist())),
        "bandas": {k: {**bandas_n[k],
                       "items": {str(a): {"tau_pp": round(100 * v["tau"], 3),
                                          "se_pp": round(100 * v["se"], 3),
                                          "n": int(v["n"])}
                                 for a, v in bandas[k].items()}}
                   for k in bandas},
        "pares": pares_b,
        "n_items_comunes": len(com_b),
        "n_cambia_signo": len(cambios),
        "items_cambian": [nombre.get(a, str(a)) for a in cambios],
    }

    # ---- diagnósticos
    taus = np.array([agregado[a]["tau"] for a in agregado])
    ses = np.array([agregado[a]["se"] for a in agregado])
    costes = np.array([coste.get(a, 0) for a in agregado], float)
    ns = np.array([n_it[a] for a in agregado], float)
    zs = taus / ses
    diag = {
        "n_items": len(agregado),
        "tau_p10_p50_p90_pp": [round(100 * x, 3) for x in np.percentile(taus, [10, 50, 90])],
        "tau_min_max_pp": [round(100 * taus.min(), 3), round(100 * taus.max(), 3)],
        "z_gt_196": int((np.abs(zs) > 1.96).sum()),
        "z_gt_258": int((np.abs(zs) > 2.58).sum()),
        "esperado_z_gt_196_bajo_nulo": round(0.05 * len(agregado), 2),
        "corr_tau_coste": round(float(np.corrcoef(costes, taus)[0, 1]), 4),
        "corr_abs_tau_inv_n": round(float(np.corrcoef(1.0 / ns, np.abs(taus))[0, 1]), 4),
        "n_mediana": int(np.median(ns)),
    }
    qs = [filas_item[a]["Q"] for a in filas_item if filas_item[a]["Q"]]
    diag["Q"] = {
        "n_items_con_Q": len(qs),
        "p_menor_005": sum(1 for q in qs if q["p"] < 0.05),
        "p_menor_010": sum(1 for q in qs if q["p"] < 0.10),
        "p_mediana": round(float(np.median([q["p"] for q in qs])), 4),
        "sd_sobre_se_mediana": round(float(np.median(
            [q["sd_tau_pp"] / q["se_mediana_pp"] for q in qs])), 3),
    }

    # ---- sensibilidad
    sens = {}
    for spec in ("quad", "spline", "bins"):
        ds = Diseno(d, 30, spec, nw_edges)
        t_ = ajustar_corte(ds, idx_todo, MIN_N_AGREGADO, coste)
        sens[spec] = {a: round(100 * t_[a]["tau"], 3) for a in sorted(t_)}
    com_s = sorted(set(sens["bins"]) & set(sens["quad"]))
    t_e = ajustar_corte(dis, idx_todo, MIN_N_AGREGADO, coste, banda=BANDA_ESTRECHA)
    t_i = ajustar_corte(dis, idx_todo, MIN_N_AGREGADO, coste, ponderado=False)
    com_e = sorted(set(t_e) & set(agregado))
    sens_res = {
        "corr_quad_bins": round(spearman([sens["quad"][a] for a in com_s],
                                         [sens["bins"][a] for a in com_s]), 4),
        "corr_spline_bins": round(spearman([sens["spline"][a] for a in com_s],
                                           [sens["bins"][a] for a in com_s]), 4),
        "n_items": len(com_s),
        "tau_pp": {a: {"quad": sens["quad"].get(a), "spline": sens["spline"].get(a),
                       "bins": sens["bins"].get(a)} for a in com_s},
        "banda_estrecha": {a: {"tau_pp": round(100 * t_e[a]["tau"], 3),
                               "se_pp": round(100 * t_e[a]["se"], 3),
                               "n": int(t_e[a]["n"])} for a in sorted(t_e)},
        "pesos_iguales": {a: round(100 * t_i[a]["tau"], 3) for a in sorted(t_i)},
        "corr_banda50_banda25": round(spearman([agregado[a]["tau"] for a in com_e],
                                               [t_e[a]["tau"] for a in com_e]), 4),
        "n_items_banda_estrecha": len(t_e),
    }

    artefacto = {
        "generado_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "corpus": {"archivo": os.path.relpath(args.corpus, RAIZ), "filas": n,
                   "partidas": partidas_tot, "parches": len(parches)},
        "estimando": {
            "formula": "tau(a) = media_{i:A_i=a}[Y_i - media_{a' in S_i}Y_i(a')]",
            "contrafactual": "alternativas del mismo tramo de precio (0.5x-1.5x coste), "
                             "shortlist observado (n>=min_n), ponderadas por compras",
            "sin_asequibilidad": "historico.db no trae oro liquido; net_worth_at_buy no "
                                 "reconstruye el conjunto asequible del v3",
            "estimador": "plug-in del AIPW del v3 (sin correccion IPW): LPM con dummies "
                         "de item, bins de t y de log net worth, ranked y parche",
            "se": "sandwich agrupado por partida",
            "ridge_item": RIDGE_ITEM,
            "min_n_parche": MIN_N_PARCHE, "min_n_agregado": MIN_N_AGREGADO,
            "min_n_banda": MIN_N_BANDA,
        },
        "agregado": {"items": filas_item, "diagnosticos": diag},
        "estabilidad": estab,
        "replica": replica,
        "banda": banda_res,
        "sensibilidad": sens_res,
        "por_parche": {p: {"n_filas": por_parche[p]["n_filas"],
                           "n_partidas": por_parche[p]["n_partidas"],
                           "items": {str(a): {"tau_pp": round(100 * v["tau"], 3),
                                              "se_pp": round(100 * v["se"], 3),
                                              "n": int(v["n"])}
                                     for a, v in por_parche[p]["items"].items()}}
                       for p in parches},
    }
    with open(args.salida, "w", encoding="utf-8") as f:
        json.dump(artefacto, f, ensure_ascii=False, indent=1)
    print("\n-> %s (%.1f KB, %.1f s)" % (args.salida,
                                         os.path.getsize(args.salida) / 1024,
                                         time.time() - t0))

    print("\n== top 10 por muestra ==")
    print("%-22s %5s %6s %8s %6s %-14s %6s %5s" %
          ("item", "n", "parches", "tau_pp", "se_pp", "IC95", "+signo", "Q_p"))
    for a in items_orden[:10]:
        f_ = filas_item[a]
        q = f_["Q"]["p"] if f_["Q"] else float("nan")
        print("%-22s %5d %6d %+8.2f %6.2f [%+.1f,%+.1f]  %2d/%-2d %5.3f"
              % (f_["nombre"], f_["n"], f_["parches_con_muestra"], f_["tau_pp"],
                 f_["se_pp"], f_["ic95_pp"][0], f_["ic95_pp"][1],
                 f_["signos_positivos"], f_["parches_con_muestra"], q))
    print("\nréplica temporal: Spearman %.3f · signo %d/%d (%.1f%%)"
          % (replica["spearman"], replica["signo_igual"], replica["n_items_comunes"],
             replica["signo_pct"]))
    if "placebo" in replica:
        print("placebo: Spearman mediana %.3f [%.3f, %.3f] · signo mediana %.1f%%"
              % (replica["placebo"]["spearman_mediana"], replica["placebo"]["spearman_p10"],
                 replica["placebo"]["spearman_p90"], replica["placebo"]["signo_mediana"]))
    print("banda: cortes %s · signos que cambian %d/%d · Spearman pares %s"
          % (banda_res["cortes_badge"], banda_res["n_cambia_signo"],
             banda_res["n_items_comunes"],
             {k: v["spearman"] for k, v in banda_res["pares"].items()}))
    print("estabilidad (>=75%% signo, k>=10, IC95 excluye 0): %d/%d ítems; k>=10: %d; "
          "sin parche con muestra: %d"
          % (estab["n_items_estables"], estab["n_items"], estab["n_con_k_ge_10"],
             estab["n_items_sin_parche"]))
    print("diagnóstico: |z|>1.96 %d de %d (azar %.1f) · corr(tau,coste) %.3f · "
          "corr(|tau|,1/n) %.3f"
          % (diag["z_gt_196"], diag["n_items"], diag["esperado_z_gt_196_bajo_nulo"],
             diag["corr_tau_coste"], diag["corr_abs_tau_inv_n"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
