"""Estimador v3: efecto de una compra contra las alternativas **asequibles y del mismo
tramo de precio**, con el estado que sí trae `demos_norm.csv.gz`.

Por qué este estimando y no el del v2
-------------------------------------
El v2 comparaba contra el *shortlist* (o contra el shortlist del mismo tramo de precio)
sin comprobar que la alternativa se pudiera pagar. Medido en la tabla de demos
(`informes/lab/V3-NORMALIZACION-2026-11-18.md`):

- 99,88 % de las compras tienen ≥ 2 alternativas asequibles;
- en el 65,79 % el jugador compró **lo más caro que podía pagar**.

Con eso, comparar contra «todo lo asequible» reintroduce el efecto de precio: la
alternativa media de un jugador con 800 de oro es un 800, y la de uno con 7 000 es un
3 200. El v3 restringe el contrafactual a las alternativas **asequibles** (precio neto de
componentes ≤ oro_antes), **no poseídas** y **del mismo tramo de precio** que la compra
observada: coste de catálogo entre 0,5× y 1,5× el coste del ítem comprado. Es la banda
±50 % de la tabla, con tope superior (la columna `n_alt_50pct` solo tiene tope inferior).

El estimando, escrito antes de ver ningún número:

    τ(a) = media_{i: A_i = a} [ Y_i(a) − (1/|S_i|) Σ_{a'∈S_i} Y_i(a') ]

con `S_i` = alternativas asequibles y no poseídas en la banda ±50 % del precio de `a`, en
la misma franja. Se estima con AIPW:

    τ̂(a) = (1/n_a) Σ_{i∈a} [ m̂(a|x_i) + AIPW_i − b̂_i ]
    AIPW_i = 1{A_i=a}/ê_i(a) · (Y_i − m̂(a|x_i))
    b̂_i  = (1/|S_i|) Σ_{a'∈S_i} m̂(a'|x_i)

`b̂_i` es **predictivo**: la alternativa nunca es la compra observada de esa fila
(el conjunto excluye `a`), de modo que no hay resultado observado contra el cual corregir
ese lado. La corrección IPW solo protege el lado «mi ítem». Es una limitación del diseño
y va declarada, no escondida. Por eso el artefacto guarda también `plugin_pp` (sin la
corrección) y el ancho del IC de las dos versiones se compara.

Qué se mide y qué no
--------------------
- **Sí**: si, en los estados donde se compró `a`, `a` rinde más o menos que el promedio
  de lo que el jugador **podía pagar** en esa misma banda de precio.
- **No**: causalidad si la habilidad no observada se correlaciona con la compra. Sigue
  sin haber MMR.
- **No**: el efecto de comprar vs *no comprar*. El contrafactual es otra compra.
- **No**: separar «venta» de «consumo» en las bajas de inventario (`change = 2`).

Estado (lo que la tabla permite)
--------------------------------
Franja (3), `oro_antes` en log, oro relativo (oro de la fila / mediana de oro de la
partida), tamaño del menú asequible, ítems ya poseídos, inversión acumulada, segundos,
slot del jugador (12), héroe (one-hot con cresta fuerte). El ítem entra con covariables
de precio/tier/slot/activo **y** una columna propia por ítem observado.

Propensión
----------
Logit condicional sobre el **menú asequible completo** de cada fila (no sobre el
catálogo entero): `ê_i(a) = exp(v_a)/Σ_{a'∈A_i} exp(v_{a'})` con
`v_a = β1·coste + β2·coste² + β3·[es la más cara asequible] + β4·posición + slot`.
Se eligió esto en vez del Dirichlet por celdas del v2 porque con 173 acciones y 16 145
filas el Dirichlet da ê ≈ 1/173 y pesos 1/ê de 50–170: la corrección IPW sería ruido
puro. El logit condicional aprovecha la estructura que la tabla sí tiene (el jugador
elige casi siempre lo más caro que alcanza) y da ê de orden 0,1–0,5. Las filas con
1/ê > `PESO_MAX` se recortan y se cuentan.

Uso:
    python3 herramientas/lab/estimador_v3.py --bootstrap 200 --semilla 7 \
        --salida /tmp/modelo-v3-real.json
    python3 herramientas/lab/estimador_v3.py --tabla /tmp/sint.csv.gz \
        --verdad /tmp/sint_verdad.json --bootstrap 100 --salida /tmp/sint.json
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import sys
import time

import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUTA_TABLA = os.path.join(RAIZ, "datos", "demos_norm.csv.gz")
RUTA_CAT = os.path.join(RAIZ, "data", "catalogo.json")
RUTA_COMP = os.path.join(RAIZ, "data", "componentes.json")

BANDA = (0.5, 1.5)       # tramo de precio: ±50 % del coste del ítem comprado
E_MIN = 0.02             # recorte inferior de ê (el v2 usa el mismo)
PESO_MAX = 10.0          # recorte de 1/ê: por encima, la corrección IPW es ruido
RIDGE = 1e-2             # cresta base del logístico
RIDGE_ITEM = 2.0         # cresta de la columna propia de cada ítem
RIDGE_HERO = 20.0        # cresta del one-hot de héroe (21 jugador-partidas por héroe)
ITER_IRLS = 6            # iteraciones del logístico (con arranque caliente)
ITER_LOGIT = 12          # iteraciones Newton del logit condicional (arranque caliente)
N_MEDIDO = 2149          # compras para la etiqueta "medido" (MDE ≤ 3 pp)
N_PRELIMINAR = 150       # por debajo no se publica número
Z_MDE = 2.8016
VAR_RESIDUO = 0.2464
COLUMNAS_MIN = ("match_id", "slot", "hero_id", "tick", "segundos", "item_id",
                "coste_catalogo", "oro_antes", "franja", "resultado")


# ------------------------------------------------------------------ catálogo y menús
def cargar_catalogo(ruta_cat=RUTA_CAT, ruta_comp=RUTA_COMP):
    """Catálogo comprable (coste > 0) y grafo de componentes, como `demos_norm.py`.

    `data/catalogo.json` es el que usa el normalizador (`comprable`, `costo`), no
    `data/items.json`: con el segundo los 173 comprables no salen igual y la
    reconstrucción del conjunto no cuadraría con `n_alt_50pct`.
    """
    with open(ruta_cat, encoding="utf-8") as f:
        cat = json.load(f)
    with open(ruta_comp, encoding="utf-8") as f:
        comp = json.load(f)
    comprables = sorted((i for i, d in cat.items()
                         if d.get("comprable") and int(d.get("costo") or 0) > 0),
                        key=lambda i: (int(cat[i]["costo"]), i))
    return cat, comp, comprables


def cargar_tabla(ruta=RUTA_TABLA):
    """Lee la tabla normalizada a arrays. Devuelve (filas, arrays, sha256)."""
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for trozo in iter(lambda: f.read(1 << 20), b""):
            h.update(trozo)
    abrir = gzip.open if str(ruta).endswith(".gz") else open
    with abrir(ruta, "rt", encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        campos = lector.fieldnames or []
        faltan = [c for c in COLUMNAS_MIN if c not in campos]
        if faltan:
            raise SystemExit(f"faltan columnas en {ruta}: {faltan}")
        filas = list(lector)
    n = len(filas)
    if not n:
        raise SystemExit(f"tabla vacía: {ruta}")

    def ent(col, defecto=0):
        if col not in campos:
            return np.full(n, defecto, dtype=np.int64)
        return np.asarray([int(r[col]) if r.get(col) not in (None, "") else defecto
                           for r in filas], dtype=np.int64)

    def flot(col, defecto=0.0):
        if col not in campos:
            return np.full(n, defecto, dtype=np.float64)
        return np.asarray([float(r[col]) if r.get(col) not in (None, "") else defecto
                           for r in filas], dtype=np.float64)

    arr = {
        "match": ent("match_id"),
        "slot": ent("slot"),
        "hero": ent("hero_id"),
        "tick": ent("tick"),
        "t": flot("segundos"),
        "franja": ent("franja"),
        "item": [r["item_id"] for r in filas],
        "coste": ent("coste_catalogo"),
        "oro": ent("oro_antes"),
        "y": np.asarray([1 if r["resultado"] == "victoria" else 0 for r in filas],
                        dtype=np.int8),
        "n_alt_50pct": ent("n_alt_50pct", -1),
        "comprado_es_max": ent("comprado_es_max"),
        "slot_confianza": ent("slot_confianza", 1),
    }
    return filas, arr, h.hexdigest()


def construir_menus(arr, cat, comp, comprables, verbose=True):
    """Conjunto asequible A_i y conjunto de comparación S_i por fila.

    Reconstruye el inventario recorriendo las compras de cada (partida, slot) en orden
    de tick: un ítem comprado entra al inventario; si el ítem tiene grafo, sus
    componentes salen (se consumen). No se modelan ventas ni el límite de 4 slots por
    categoría: la tabla no los trae.

    Devuelve arrays planos ordenados por fila:
      - `ini[i]:ini[i+1]` indexa los pares (fila, alternativa) de la fila i;
      - `acc` es el índice de la alternativa en `comprables`;
      - `banda` marca si el par entra en el conjunto de comparación;
      - `elegido[i]` es el índice del par de la compra observada (-1 si no está).
    """
    n = len(arr["item"])
    pos_cat = {i: j for j, i in enumerate(comprables)}
    coste_c = np.asarray([int(cat[i]["costo"]) for i in comprables], dtype=np.int64)
    comp_de = [comp.get(i, []) for i in comprables]
    coste_comp = np.asarray([sum(int(cat[k]["costo"]) for k in comp_de[j]
                                 if k in cat) for j in range(len(comprables))],
                            dtype=np.int64)
    tiene_grafo = np.asarray([i in comp for i in comprables], dtype=bool)

    orden = np.lexsort((arr["tick"], arr["slot"], arr["match"]))
    acc_pares, banda, fila_par = [], [], []
    owned = {}
    for i in orden:
        clave = (int(arr["match"][i]), int(arr["slot"][i]))
        props = owned.setdefault(clave, set())
        a = arr["item"][i]
        oro = int(arr["oro"][i])
        c = int(arr["coste"][i])
        lo, hi = BANDA[0] * c, BANDA[1] * c
        i = int(i)
        for j in range(len(comprables)):
            iid = comprables[j]
            if iid in props:
                continue
            cs = int(coste_c[j])
            if cs - int(coste_comp[j]) > oro:     # ni con todos los componentes alcanza
                continue
            neto = cs
            if tiene_grafo[j]:
                neto = max(0, cs - sum(int(cat[x]["costo"]) for x in comp_de[j]
                                       if x in props and x in cat))
            if neto > oro:
                continue
            acc_pares.append(j)
            fila_par.append(i)
            banda.append(bool(iid != a and lo <= cs <= hi))
        for x in comp.get(a, ()):
            props.discard(x)
        props.add(a)

    acc_pares = np.asarray(acc_pares, dtype=np.int16)
    fila_par = np.asarray(fila_par, dtype=np.int32)
    banda = np.asarray(banda, dtype=bool)
    # orden estable por fila: dentro de cada fila los pares quedan en coste ascendente
    perm = np.argsort(fila_par, kind="stable")
    acc_pares, fila_par, banda = acc_pares[perm], fila_par[perm], banda[perm]
    ini = np.zeros(n + 1, dtype=np.int64)
    ini[1:] = np.cumsum(np.bincount(fila_par, minlength=n))
    # par elegido: clave = fila*n_acciones + acción, estrictamente creciente
    n_acciones = len(comprables)
    clave = fila_par.astype(np.int64) * n_acciones + acc_pares.astype(np.int64)
    buscado = np.arange(n, dtype=np.int64) * n_acciones + np.asarray(
        [pos_cat.get(arr["item"][i], -1) for i in range(n)], dtype=np.int64)
    elegido = np.full(n, -1, dtype=np.int64)
    ok = buscado % n_acciones >= 0
    pos = np.searchsorted(clave, buscado[ok])
    pos = np.clip(pos, 0, max(0, len(clave) - 1))
    encontrado = clave[pos] == buscado[ok] if len(clave) else np.zeros(0, bool)
    elegido[ok] = np.where(encontrado, pos, -1)
    if verbose:
        print(f"menús: {len(acc_pares):,} pares (fila, alternativa) · "
              f"media {len(acc_pares) / n:.1f} por compra · "
              f"elegido en menú {100.0 * np.mean(elegido >= 0):.2f} %", file=sys.stderr)
    return {"ini": ini, "acc": acc_pares, "banda": banda, "fila": fila_par,
            "elegido": elegido, "comprables": comprables, "coste_c": coste_c,
            "pos_cat": pos_cat, "n_acciones": n_acciones}


def cobertura(arr, menus):
    """Conteos de qué entra y qué no, y reconciliación con la columna de la tabla."""
    n = len(arr["item"])
    ini, fila = menus["ini"], menus["fila"]
    acc = menus["acc"]
    coste_c = menus["coste_c"]
    tam_men = np.diff(ini)
    tam_banda = np.bincount(fila, weights=menus["banda"].astype(np.float64),
                            minlength=n)
    a_obs = np.full(n, -1, dtype=np.int64)
    valido = menus["elegido"] >= 0
    a_obs[valido] = acc[menus["elegido"][valido]]
    coste_a = np.where(valido, coste_c[np.maximum(a_obs, 0)], 0)
    # lo que la tabla llama n_alt_50pct: asequibles y de coste >= 0.5x, sin tope
    inferior = ((coste_c[acc] >= 0.5 * coste_a[fila])
                & (acc != a_obs[fila]) & (a_obs[fila] >= 0))
    alt_inf = np.bincount(fila[inferior], minlength=n)
    # precio relativo que queda dentro de la banda: si la alternativa media del
    # conjunto sigue siendo más barata que la compra, no se quitó todo el precio.
    coste_par = coste_c[acc].astype(np.float64)
    suma_precio = np.bincount(fila[menus["banda"]], weights=coste_par[menus["banda"]],
                              minlength=n)
    media_banda = np.divide(suma_precio, np.maximum(tam_banda, 1),
                            out=np.full(n, np.nan), where=tam_banda > 0)
    brecha = (coste_a - media_banda) / np.maximum(coste_a, 1)
    brecha = brecha[np.isfinite(brecha)]
    tabla = arr["n_alt_50pct"]
    comparable = tabla >= 0
    dif = (alt_inf - tabla)[comparable]
    return {
        "compras": int(n),
        "compras_por_partida": round(float(n / max(1, len(np.unique(arr["match"])))), 1),
        "con_menu": int(np.sum(tam_men > 0)),
        "con_comparables": int(np.sum(tam_banda > 0)),
        "sin_menu": int(np.sum(tam_men == 0)),
        "sin_comparables": int(np.sum(tam_banda == 0)),
        "elegido_en_menu": int(np.sum(valido)),
        "menu_mediana": float(np.median(tam_men)),
        "comparables_mediana": float(np.median(tam_banda)),
        "comparables_p10_p90": [float(np.percentile(tam_banda, 10)),
                                float(np.percentile(tam_banda, 90))],
        "items_comprables": len(menus["comprables"]),
        "brecha_precio_banda": {
            "p10_p50_p90": [round(float(np.percentile(brecha, 10)), 3),
                            round(float(np.percentile(brecha, 50)), 3),
                            round(float(np.percentile(brecha, 90)), 3)],
            "pct_banda_mas_barata": round(100.0 * float(np.mean(brecha > 0)), 2),
        },
        "reconciliacion_n_alt_50pct": {
            "filas": int(comparable.sum()),
            "exactas": int(np.sum(dif == 0)),
            "pct_exactas": round(100.0 * float(np.mean(dif == 0)), 2),
            "pct_abs_le_1": round(100.0 * float(np.mean(np.abs(dif) <= 1)), 2),
            "media_dif": round(float(np.mean(dif)), 3),
        },
    }


# ------------------------------------------------------------------------- estado
def construir_estado(arr, menus):
    """Covariables del estado (no dependen de la acción)."""
    n = len(arr["item"])
    mediana_partida = {}
    for m in np.unique(arr["match"]):
        sel = arr["match"] == m
        mediana_partida[int(m)] = float(np.median(arr["oro"][sel]))
    oro_rel = np.asarray([arr["oro"][i] / max(1.0, mediana_partida[int(arr["match"][i])])
                          for i in range(n)], dtype=np.float64)
    oro_rel = np.clip(oro_rel, 0.25, 4.0) - 1.0

    n_items = np.zeros(n, dtype=np.float64)
    inversion = np.zeros(n, dtype=np.float64)
    orden = np.lexsort((arr["tick"], arr["slot"], arr["match"]))
    acum = {}
    for i in orden:
        clave = (int(arr["match"][i]), int(arr["slot"][i]))
        n_items[i], inversion[i] = acum.get(clave, (0, 0))
        acum[clave] = (n_items[i] + 1, inversion[i] + int(arr["coste"][i]))

    tam_men = np.diff(menus["ini"]).astype(np.float64)
    franja = arr["franja"].astype(np.int64)
    heroes = {h: j for j, h in enumerate(sorted(set(arr["hero"].tolist())))}
    h_idx = np.asarray([heroes[int(h)] for h in arr["hero"]], dtype=np.int64)
    slots = arr["slot"].astype(np.int64) - 1

    cols = [np.ones(n), (franja == 1).astype(float), (franja == 2).astype(float),
            np.log(np.maximum(arr["oro"], 1)) - math.log(1300.0), oro_rel,
            np.log1p(tam_men) - math.log(60.0), n_items / 12.0,
            inversion / 20000.0, arr["t"] / 2400.0]
    nombres = ["intercepto", "franja1", "franja2", "log_oro", "oro_rel", "log_menu",
               "n_items", "inversion", "segundos"]
    for s in range(12):
        cols.append((slots == s).astype(float))
        nombres.append(f"slot{s + 1}")
    for h in range(len(heroes)):
        cols.append((h_idx == h).astype(float))
        nombres.append(f"heroe{h}")
    X = np.column_stack(cols).astype(np.float32)
    cresta = np.full(X.shape[1], RIDGE)
    cresta[9 + 12:] = RIDGE_HERO
    return X, nombres, cresta, {"n_heroes": len(heroes)}


def construir_accion(cat, comprables, observados):
    """Covariables de la acción: precio, tier, slot, activo e identidad del ítem."""
    filas, ident = [], []
    idx_obs = {i: j for j, i in enumerate(observados)}
    for i in comprables:
        d = cat[i]
        slot = d.get("slot")
        filas.append([int(d["costo"]) / 6400.0, int(d.get("tier") or 0) / 4.0,
                      1.0 if d.get("activo") else 0.0,
                      1.0 if slot == "weapon" else 0.0,
                      1.0 if slot == "vitality" else 0.0,
                      1.0 if slot == "spirit" else 0.0])
        v = np.zeros(len(observados), dtype=np.float32)
        if i in idx_obs:
            v[idx_obs[i]] = 1.0
        ident.append(v)
    return (np.asarray(filas, dtype=np.float32), np.asarray(ident, dtype=np.float32))


# ------------------------------------------------------------------------ modelos
def ajustar_logistico(X, y, cresta, pesos=None, beta0=None, iteraciones=ITER_IRLS):
    """IRLS con cresta vectorial. `pesos` es el peso de remuestreo del bootstrap."""
    n, k = X.shape
    beta = (np.zeros(k, dtype=np.float64) if beta0 is None
            else np.asarray(beta0, dtype=np.float64).copy())
    yd = y.astype(np.float64)
    wb = (np.ones(n, dtype=np.float64) if pesos is None
          else np.asarray(pesos, dtype=np.float64))
    cresta = np.asarray(cresta, dtype=np.float64)
    for _ in range(iteraciones):
        eta = X @ beta.astype(np.float32)
        np.clip(eta, -30, 30, out=eta)
        p = 1.0 / (1.0 + np.exp(-eta))
        w0 = np.maximum(p * (1.0 - p), 1e-6)
        w = (w0 * wb).astype(np.float32)
        z = eta + (yd - p) / w0
        Xw = X * w[:, None]
        hess = (Xw.T @ X).astype(np.float64)
        hess.flat[:: k + 1] += cresta
        try:
            nuevo = np.linalg.solve(hess, (Xw.T @ z).astype(np.float64))
        except np.linalg.LinAlgError:
            break
        if np.max(np.abs(nuevo - beta)) < 1e-6:
            beta = nuevo
            break
        beta = nuevo
    return beta


def predecir(beta, X):
    eta = (X @ beta.astype(np.float32)).astype(np.float64)
    np.clip(eta, -30, 30, out=eta)
    return 1.0 / (1.0 + np.exp(-eta))


def rasgos_eleccion(menus):
    """Rasgos de cada par (fila, alternativa) para el logit condicional del menú."""
    acc = menus["acc"]
    coste = menus["coste_c"][acc].astype(np.float64)
    fila = menus["fila"]
    tam = np.diff(menus["ini"])[fila].astype(np.float64)
    pos = np.arange(len(acc)) - menus["ini"][fila]
    frac = pos / np.maximum(1.0, tam - 1.0)
    es_max = (pos >= tam - 1).astype(np.float64)
    slots = menus.get("slots_acc")
    if slots is None:
        slots = np.zeros((len(menus["coste_c"]), 3), dtype=np.float32)
    return np.column_stack([coste / 6400.0, (coste / 6400.0) ** 2, es_max, frac,
                            slots[acc, 0], slots[acc, 1], slots[acc, 2]]
                           ).astype(np.float32)


def ajustar_eleccion(rasgos, fila, ini, elegido, pesos=None,
                     iteraciones=ITER_LOGIT, cresta=1e-2, beta0=None):
    """Logit condicional: P(elegir a | menú) = exp(v_a)/Σ_{a'∈menú} exp(v_a').

    Newton sobre la log-verosimilitud condicional. `pesos` pondera filas (bootstrap).
    Devuelve (beta, logsumexp por fila).
    """
    n = len(ini) - 1
    k = rasgos.shape[1]
    beta = (np.zeros(k, dtype=np.float64) if beta0 is None
            else np.asarray(beta0, dtype=np.float64).copy())
    tam = np.diff(ini)
    w_fila = (np.ones(n) if pesos is None else np.asarray(pesos, dtype=np.float64))
    r64 = rasgos.astype(np.float64)
    eleg_seguro = np.clip(elegido, 0, len(r64) - 1)
    x_eleg = r64[eleg_seguro]
    for _ in range(iteraciones):
        v = (rasgos @ beta.astype(np.float32)).astype(np.float64)
        mx = np.maximum.reduceat(v, ini[:-1])
        w = np.exp(v - np.repeat(mx, tam))
        s0 = np.maximum(np.bincount(fila, weights=w, minlength=n), 1e-12)
        wp = (w / s0[fila]) * w_fila[fila]
        # media por fila de los rasgos bajo la distribución del modelo: Σ_a p_a x_a
        media = np.column_stack([np.bincount(fila, weights=wp * r64[:, j], minlength=n)
                                 for j in range(k)])
        media_w = (media * w_fila[:, None]).sum(axis=0)
        grad = (w_fila[:, None] * x_eleg).sum(axis=0) - media_w
        # Hessiano = −Σ_fila w_fila [ Σ_a p_a x x' − (Σ_a p_a x)(Σ_a p_a x)' ]
        s2 = (r64 * wp[:, None]).T @ r64
        m2 = media.T @ (media * w_fila[:, None])
        hess = -(s2 - m2)
        hess.flat[:: k + 1] -= cresta
        try:
            paso = np.linalg.solve(hess, grad)
        except np.linalg.LinAlgError:
            break
        beta = beta - paso
        if np.max(np.abs(paso)) < 1e-8:
            break
    v = (rasgos @ beta.astype(np.float32)).astype(np.float64)
    mx = np.maximum.reduceat(v, ini[:-1])
    s0 = np.bincount(fila, weights=np.exp(v - np.repeat(mx, tam)), minlength=n)
    lse = np.where(s0 > 0, np.log(np.maximum(s0, 1e-12)) + mx, 0.0)
    return beta, lse


def predecir_pares(beta, base, acc, pares, menu, arr, bloque=131072):
    """m̂(x_i, a) para los pares indicados, por bloques de memoria."""
    fila_p = menu["fila"][pares]
    acc_p = menu["acc"][pares].astype(np.int64)
    salida = np.empty(len(pares), dtype=np.float64)
    for ini_b in range(0, len(pares), bloque):
        fin = min(len(pares), ini_b + bloque)
        f = fila_p[ini_b:fin]
        a = acc_p[ini_b:fin]
        h = np.clip(np.log(np.maximum(arr["oro"][f], 1) /
                           np.maximum(menu["coste_c"][a], 1)), -3, 3)
        X = np.hstack([base[f], acc[a], h[:, None].astype(np.float32)])
        salida[ini_b:fin] = predecir(beta, X)
    return salida


# -------------------------------------------------------------------------- AIPW
def tau_por_item(m_obs, m_banda, banda, fila, y, e_obs, a_obs, n_acciones,
                 valida):
    """τ_i por fila y las tres versiones por ítem.

    `base_i = m̂(a) − b̂_i` es el contraste plug-in. La corrección IPW añade
    `w_i (Y_i − m̂(a))` con `w_i = min(1/ê_i, PESO_MAX)`.

    Se devuelven tres versiones porque las tres dicen algo distinto:

    - `hajek`: pesos normalizados (Σw = n_a). Es la que se publica: con ê ≈ 0,03 el
      AIPW sin normalizar no tiene varianza finita en esta muestra (se midió: ±290 pp).
    - `sin_normalizar`: la fórmula literal `m̂ + (Y−m̂)/ê`. Se guarda como diagnóstico
      de por qué no se usa.
    - `plugin`: sin corrección. Si `hajek` y `plugin` difieren mucho, el número depende
      del modelo de desenlace y no de los datos.
    """
    n = len(y)
    cuenta_b = np.bincount(fila, weights=banda.astype(np.float64), minlength=n)
    suma_b = np.bincount(fila[banda], weights=m_banda, minlength=n)
    b = np.divide(suma_b, cuenta_b, out=np.full(n, np.nan), where=cuenta_b > 0)
    base_i = m_obs - b
    bruto = 1.0 / np.maximum(e_obs, E_MIN)
    w = np.minimum(bruto, PESO_MAX)
    truncados = int(np.sum(bruto > PESO_MAX))
    res_i = (y - m_obs) * w
    uso = valida & np.isfinite(base_i)
    a_uso = a_obs[uso]
    n_acc = np.bincount(a_uso, minlength=n_acciones)
    s_base = np.bincount(a_uso, weights=base_i[uso], minlength=n_acciones)
    s_res = np.bincount(a_uso, weights=res_i[uso], minlength=n_acciones)
    s_w = np.bincount(a_uso, weights=w[uso], minlength=n_acciones)
    s_w2 = np.bincount(a_uso, weights=(w[uso] ** 2), minlength=n_acciones)
    media_base = np.divide(s_base, n_acc, out=np.full(n_acciones, np.nan),
                           where=n_acc > 0)
    tau = {}
    tau["plugin"] = media_base
    tau["hajek"] = media_base + np.divide(s_res, s_w, out=np.full(n_acciones, np.nan),
                                          where=s_w > 0)
    tau["sin_normalizar"] = media_base + np.divide(s_res, n_acc,
                                                   out=np.full(n_acciones, np.nan),
                                                   where=n_acc > 0)
    # tamaño efectivo de la muestra con esos pesos (Kish) y dispersión de los pesos
    neff = np.divide(s_w ** 2, s_w2, out=np.full(n_acciones, np.nan), where=s_w2 > 0)
    return tau, n_acc, truncados, neff, base_i, res_i, w


def _agregar(base_i, res_i, w, a_obs, uso, n_acciones):
    """τ Hájek y plug-in por ítem sobre las filas de `uso` (una franja o todo)."""
    a_uso = a_obs[uso]
    cuenta = np.bincount(a_uso, minlength=n_acciones)
    s_base = np.bincount(a_uso, weights=base_i[uso], minlength=n_acciones)
    s_res = np.bincount(a_uso, weights=res_i[uso], minlength=n_acciones)
    s_w = np.bincount(a_uso, weights=w[uso], minlength=n_acciones)
    media = np.divide(s_base, cuenta, out=np.full(n_acciones, np.nan),
                      where=cuenta > 0)
    hajek = media + np.divide(s_res, s_w, out=np.full(n_acciones, np.nan),
                              where=s_w > 0)
    return hajek, media, cuenta


def _resumen_tau(efectos):
    efectos = np.asarray(efectos, dtype=float)
    if not len(efectos):
        return {}
    return {"n_items": int(len(efectos)),
            "p10_p50_p90": [round(float(np.percentile(efectos, 10)), 2),
                            round(float(np.percentile(efectos, 50)), 2),
                            round(float(np.percentile(efectos, 90)), 2)],
            "min_max": [round(float(efectos.min()), 2),
                        round(float(efectos.max()), 2)],
            "media": round(float(efectos.mean()), 2)}


_PAYLOAD = {}


def _replica(b):
    """Una réplica del bootstrap: remuestrea partidas, reajusta m̂ y ê, calcula τ.

    El generador va sembrado con `(semilla, b)`, así que el resultado no depende del
    orden ni del número de procesos. Las matrices grandes llegan por `fork` (COW).
    """
    d = _PAYLOAD
    rng = np.random.default_rng([int(d["semilla"]), int(b)])
    n_partidas = d["n_partidas"]
    pesos = rng.multinomial(n_partidas, np.full(n_partidas, 1.0 / n_partidas))
    w_fila = pesos[d["match_idx"]].astype(np.float64)
    beta_b = ajustar_logistico(d["Xobs"], d["y_ok"], d["cresta"],
                               pesos=w_fila[d["ok"]], beta0=d["beta"])
    beta_e_b, lse_b = ajustar_eleccion(d["rasgos"], d["fila"], d["ini"], d["eleg_prop"],
                                       pesos=w_fila * d["ok"], beta0=d["beta_e"])
    e_b = np.clip(np.exp((d["rasgos"] @ beta_e_b.astype(np.float32)).astype(np.float64)
                         - lse_b[d["fila"]])[d["elegido"]], E_MIN, 0.999)
    m_banda = predecir_pares(beta_b, d["base"], d["acc"], d["pares_banda"],
                             d["menus"], d["arr"])
    m_obs = np.full(d["n"], np.nan)
    m_obs[d["ok"]] = predecir_pares(beta_b, d["base"], d["acc"], d["pares_obs"],
                                    d["menus"], d["arr"])
    tau, _, _, _, bi, ri, wi = tau_por_item(m_obs, m_banda, d["banda"], d["fila"],
                                            d["y"], e_b, d["a_obs"], d["n_acciones"],
                                            d["valida"])
    h = np.full((3, d["n_acciones"]), np.nan)
    pl = np.full((3, d["n_acciones"]), np.nan)
    for e_idx in range(3):
        sel = d["valida"] & (d["fr"] == e_idx)
        if not np.any(sel):
            continue
        he, pe, _ = _agregar(bi, ri, wi, d["a_obs"], sel, d["n_acciones"])
        h[e_idx] = he
        pl[e_idx] = pe
    return b, h, pl, tau["sin_normalizar"]


def _lanzar(bootstrap, semilla, procesos, verbose, t0):
    tareas = list(range(bootstrap))
    rep = {k: np.full((bootstrap, 3, _PAYLOAD["n_acciones"]), np.nan, dtype=np.float32)
           for k in ("plugin", "hajek")}
    rep_sn = np.full((bootstrap, _PAYLOAD["n_acciones"]), np.nan, dtype=np.float32)
    salida = None
    if procesos > 1:
        import multiprocessing as mp
        try:
            ctx = mp.get_context("fork")
            salida = ctx.Pool(procesos)
        except (ValueError, OSError):
            salida = None
    if salida is None:
        for b in tareas:
            _guardar_rep(*_replica(b), rep=rep, rep_sn=rep_sn)
            if verbose and (b + 1) % 25 == 0:
                print(f"  bootstrap {b + 1}/{bootstrap} "
                      f"({time.perf_counter() - t0:.0f} s)", file=sys.stderr)
    else:
        with salida:
            for k, (b, h, pl, sn) in enumerate(salida.imap_unordered(_replica, tareas)):
                _guardar_rep(b, h, pl, sn, rep=rep, rep_sn=rep_sn)
                if verbose and (k + 1) % 25 == 0:
                    print(f"  bootstrap {k + 1}/{bootstrap} "
                          f"({time.perf_counter() - t0:.0f} s)", file=sys.stderr)
    return rep, rep_sn


def _guardar_rep(b, h, pl, sn, rep, rep_sn):
    rep["hajek"][b] = h
    rep["plugin"][b] = pl
    rep_sn[b] = sn
    return b


def estimar(tabla=RUTA_TABLA, bootstrap=200, semilla=7, verbose=True, verdad=None,
            procesos=0):
    """Corre el estimador y devuelve el artefacto (sin escribir)."""
    t0 = time.perf_counter()
    _, arr, sha = cargar_tabla(tabla)
    cat, comp, comprables = cargar_catalogo()
    menus = construir_menus(arr, cat, comp, comprables, verbose=verbose)
    cob = cobertura(arr, menus)
    n = len(arr["item"])
    n_acciones = len(comprables)
    a_obs = np.full(n, -1, dtype=np.int64)
    ok = menus["elegido"] >= 0
    a_obs[ok] = menus["acc"][menus["elegido"][ok]]
    tam_banda = np.bincount(menus["fila"], weights=menus["banda"].astype(float),
                            minlength=n)
    valida = ok & (tam_banda > 0)
    fr = arr["franja"].astype(np.int64)
    if verbose:
        print(f"filas válidas {int(valida.sum()):,}/{n:,} · "
              f"partidas {len(np.unique(arr['match']))}", file=sys.stderr)

    base, nombres_estado, cresta, info_estado = construir_estado(arr, menus)
    observados = sorted(set(arr["item"]))
    acc_est, identidad = construir_accion(cat, comprables, observados)
    acc = np.hstack([acc_est, identidad])
    coste_a = menus["coste_c"][np.maximum(a_obs, 0)]
    holgura = np.clip(np.log(np.maximum(arr["oro"], 1) / np.maximum(coste_a, 1)), -3, 3)
    Xobs = np.hstack([base, acc[np.maximum(a_obs, 0)],
                      holgura[:, None].astype(np.float32)])
    cresta_obs = np.concatenate([cresta, np.full(acc.shape[1], RIDGE),
                                 np.array([RIDGE], dtype=np.float64)])
    ini_id = len(cresta) + acc_est.shape[1]
    cresta_obs[ini_id:len(cresta) + acc.shape[1]] = RIDGE_ITEM
    y = arr["y"].astype(np.float64)
    beta = ajustar_logistico(Xobs[ok], y[ok], cresta_obs)
    if verbose:
        print(f"modelo de desenlace: {Xobs.shape[1]} columnas, "
              f"{int(ok.sum()):,} filas, {time.perf_counter() - t0:.1f} s",
              file=sys.stderr)

    # ---------------------------------------------------------- propensión
    menus["slots_acc"] = np.asarray(
        [[1.0 if cat[i].get("slot") == "weapon" else 0.0,
          1.0 if cat[i].get("slot") == "vitality" else 0.0,
          1.0 if cat[i].get("slot") == "spirit" else 0.0] for i in comprables],
        dtype=np.float32)
    rasgos = rasgos_eleccion(menus)
    fila, ini = menus["fila"], menus["ini"]
    # las filas cuyo ítem no está en el menú no son una elección válida del logit
    # condicional: entran con peso 0 y un par cualquiera.
    eleg_prop = np.where(ok, menus["elegido"], ini[:-1])
    beta_e, lse = ajustar_eleccion(rasgos, fila, ini, eleg_prop,
                                   pesos=ok.astype(float))
    e_obs = np.clip(np.exp((rasgos @ beta_e.astype(np.float32)).astype(np.float64)
                           - lse[fila])[menus["elegido"]], E_MIN, 0.999)
    if verbose:
        print(f"propensión: ê mediana {np.median(e_obs[ok]):.4f} · "
              f"1/ê mediana {np.median(1 / e_obs[ok]):.1f} · "
              f"recortadas {100.0 * np.mean(1 / e_obs[ok] > PESO_MAX):.1f} %",
              file=sys.stderr)

    pares_banda = np.nonzero(menus["banda"])[0]
    pares_obs = menus["elegido"][ok]

    def _tau(beta_b, e_b):
        m_banda = predecir_pares(beta_b, base, acc, pares_banda, menus, arr)
        m_obs = np.full(n, np.nan)
        m_obs[ok] = predecir_pares(beta_b, base, acc, pares_obs, menus, arr)
        return tau_por_item(m_obs, m_banda, menus["banda"], fila, y, e_b, a_obs,
                            n_acciones, valida)

    tau, n_acc, truncados, neff, base_i, res_i, w = _tau(beta, e_obs)

    # ------------------------------------------------ bootstrap por partida
    partidas, match_idx = np.unique(arr["match"], return_inverse=True)
    n_partidas = len(partidas)
    _PAYLOAD.clear()
    _PAYLOAD.update({
        "semilla": semilla, "n_partidas": n_partidas, "match_idx": match_idx,
        "Xobs": Xobs[ok], "y_ok": y[ok], "y": y, "cresta": cresta_obs, "beta": beta,
        "rasgos": rasgos, "fila": fila, "ini": ini, "eleg_prop": eleg_prop,
        "beta_e": beta_e, "elegido": menus["elegido"], "base": base, "acc": acc,
        "pares_banda": pares_banda, "pares_obs": pares_obs, "menus": menus,
        "arr": arr, "banda": menus["banda"], "a_obs": a_obs, "valida": valida,
        "fr": fr, "n_acciones": n_acciones, "n": n, "ok": ok,
    })
    procesos = (min(6, max(1, (os.cpu_count() or 2) - 1)) if procesos in (0, None)
                else int(procesos))
    if verbose:
        print(f"bootstrap: {bootstrap} réplicas con {procesos} proceso(s)",
              file=sys.stderr)
    rep, rep_sn = _lanzar(bootstrap, semilla, procesos, verbose, t0)

    # ------------------------------------------------------------- artefacto
    # coste medio de la banda de cada fila (para ver qué precio se está comparando)
    coste_c = menus["coste_c"]
    fil_banda = fila[menus["banda"]]
    costa_banda = coste_c[menus["acc"][menus["banda"]]].astype(np.float64)
    cnt_b = np.bincount(fil_banda, minlength=n)
    media_banda = np.divide(np.bincount(fil_banda, weights=costa_banda, minlength=n),
                            np.maximum(cnt_b, 1), out=np.full(n, np.nan),
                            where=cnt_b > 0)
    uso_tot = valida & np.isfinite(media_banda)
    coste_banda_item = np.divide(
        np.bincount(a_obs[uso_tot], weights=media_banda[uso_tot],
                    minlength=n_acciones),
        np.maximum(np.bincount(a_obs[uso_tot], minlength=n_acciones), 1),
        out=np.full(n_acciones, np.nan),
        where=np.bincount(a_obs[uso_tot], minlength=n_acciones) > 0)
    items = {}
    for j, iid in enumerate(comprables):
        na = int(n_acc[j])
        if na <= 0 or not np.isfinite(tau["plugin"][j]):
            continue
        col = (rep["plugin"][:, :, j] * 100.0).ravel()
        col = col[np.isfinite(col)]
        if len(col) < min(20, 2 * bootstrap):
            continue
        punto = float(tau["plugin"][j]) * 100.0
        mde = Z_MDE * math.sqrt(VAR_RESIDUO / max(1, na)) * 100.0
        uso_a = valida & (a_obs == j)
        n_part = int(len(np.unique(arr["match"][uso_a])))
        nf = {str(e): int(np.sum(uso_a & (fr == e))) for e in range(3)}
        por_franja, ic_franja = {}, {}
        for e_idx in range(3):
            if nf[str(e_idx)] <= 0:
                continue
            sel = uso_a & (fr == e_idx)
            h_e, _, _ = _agregar(base_i, res_i, w, a_obs, sel, n_acciones)
            por_franja[str(e_idx)] = round(float(h_e[j]) * 100.0, 2)
            col_e = (rep["plugin"][:, e_idx, j] * 100.0)
            col_e = col_e[np.isfinite(col_e)]
            if len(col_e) >= min(20, 2 * bootstrap):
                ic_franja[str(e_idx)] = [round(float(np.percentile(col_e, 5)), 2),
                                         round(float(np.percentile(col_e, 95)), 2)]
        items[iid] = {
            "nombre": cat[iid].get("nombre"),
            "coste": int(cat[iid]["costo"]),
            "slot": cat[iid].get("slot"),
            "n": na,
            "n_partidas": n_part,
            "n_por_franja": {k: v for k, v in nf.items() if v > 0},
            "efecto_pp": round(punto, 2),
            "ic90": [round(float(np.percentile(col, 5)), 2),
                     round(float(np.percentile(col, 95)), 2)],
            "ic95": [round(float(np.percentile(col, 2.5)), 2),
                     round(float(np.percentile(col, 97.5)), 2)],
            "mde_pp": round(mde, 2),
            "etiqueta": ("medido" if na >= N_MEDIDO else
                         "preliminar" if na >= N_PRELIMINAR else
                         "debil" if na >= 40 else "sin_senal"),
            "aipw_pp": (round(float(tau["sin_normalizar"][j]) * 100.0, 2)
                        if np.isfinite(tau["sin_normalizar"][j]) else None),
            "hajek_pp": (round(float(tau["hajek"][j]) * 100.0, 2)
                         if np.isfinite(tau["hajek"][j]) else None),
            "coste_banda_medio": (round(float(coste_banda_item[j]), 1)
                                  if np.isfinite(coste_banda_item[j]) else None),
            "n_efectivo_pesos": int(round(float(neff[j]))) if np.isfinite(neff[j]) else 0,
            "n_partidas": n_part,
            "por_franja": por_franja,
            "por_franja_ic90": ic_franja,
        }
    efectos = [v["efecto_pp"] for v in items.values()]
    cubre0 = sum(1 for v in items.values() if v["ic90"][0] <= 0 <= v["ic90"][1])
    ancho90 = [v["ic90"][1] - v["ic90"][0] for v in items.values()]
    dif_plugin = [abs(v["efecto_pp"] - v["aipw_pp"]) for v in items.values()
                  if v["aipw_pp"] is not None]
    doc = {
        "generado": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "tabla": {"ruta": str(tabla), "sha256": sha, "compras": cob["compras"]},
        "metodo": {
            "estimando": ("τ(a) = E[Y(a) − Y(ã)] con ã = promedio de alternativas "
                          "asequibles, no poseídas y del mismo tramo de precio "
                          "(±50 % del coste del ítem comprado)"),
            "estimador": ("AIPW con pesos normalizados (Hájek): "
                          "base_i + Σ w_i(Y−m̂)/Σ w_i, w_i = min(1/ê_i, 10)"),
            "contrafactual": ("predictivo (b̂_i); la alternativa nunca es la compra "
                              "observada, así que ese lado no tiene corrección IPW"),
            "desenlace": ("logístico S-learner: estado + covariables del ítem + "
                          "columna por ítem + holgura de oro"),
            "propension": ("logit condicional sobre el menú asequible completo "
                           "(coste, coste², máxima asequible, posición, slot)"),
            "bootstrap": (f"{bootstrap} réplicas agrupadas por partida; m̂ y ê "
                          f"reajustados en cada réplica"),
            "semilla": semilla,
            "banda_precio": list(BANDA),
            "e_min": E_MIN, "peso_max": PESO_MAX,
            "ridge": {"base": RIDGE, "item": RIDGE_ITEM, "heroe": RIDGE_HERO},
            "filas_estimadas": int(valida.sum()),
            "filas_con_elegido": int(ok.sum()),
            "truncados_ipw": int(truncados),
            "pct_truncados": round(100.0 * truncados / max(1, int(ok.sum())), 2),
            "e_mediana": round(float(np.median(e_obs[ok])), 4),
            "peso_mediano": round(float(np.median(1.0 / e_obs[ok])), 2),
            "peso_p90": round(float(np.percentile(1.0 / e_obs[ok], 90)), 2),
            "columnas_estado": len(nombres_estado),
            "columnas_desenlace": int(Xobs.shape[1]),
            **info_estado,
        },
        "cobertura": cob,
        "items": items,
        "resumen": {
            "items_con_efecto": len(items),
            "con_n_ge_150": int(sum(1 for v in items.values() if v["n"] >= 150)),
            "con_n_ge_2149": int(sum(1 for v in items.values() if v["n"] >= N_MEDIDO)),
            "ic90_cubre_cero": int(cubre0),
            "tau": _resumen_tau(efectos),
            "tau_aipw": _resumen_tau([i["aipw_pp"] for i in items.values()
                                      if i["aipw_pp"] is not None]),
            "tau_hajek": _resumen_tau([i["hajek_pp"] for i in items.values()
                                       if i["hajek_pp"] is not None]),
            "ic90_ancho_mediana": (round(float(np.median(ancho90)), 2)
                                   if ancho90 else None),
            "dif_plugin_aipw_mediana": (round(float(np.median(dif_plugin)), 2)
                                        if dif_plugin else None),
            "dif_plugin_aipw_max": (round(float(np.max(dif_plugin)), 2)
                                    if dif_plugin else None),
        },
    }
    if verdad:
        doc["verdad"] = verdad
    if verbose:
        print(f"listo en {time.perf_counter() - t0:.1f} s · {len(items)} ítems",
              file=sys.stderr)
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description="Estimador v3 (contrafactual asequible)")
    ap.add_argument("--tabla", default=RUTA_TABLA)
    ap.add_argument("--bootstrap", type=int, default=200)
    ap.add_argument("--semilla", type=int, default=7)
    ap.add_argument("--salida", default="/tmp/modelo-v3-real.json")
    ap.add_argument("--verdad", default=None, help="JSON con la verdad (sintético)")
    ap.add_argument("--comparar", action="store_true",
                    help="compara contra `--verdad` (corpus sintético)")
    ap.add_argument("--silencioso", action="store_true")
    a = ap.parse_args(argv)
    verdad = None
    if a.verdad:
        with open(a.verdad, encoding="utf-8") as f:
            verdad = json.load(f)
    doc = estimar(a.tabla, a.bootstrap, a.semilla, verbose=not a.silencioso,
                  verdad=verdad)
    if a.comparar and verdad:
        if RAIZ not in sys.path:
            sys.path.insert(0, RAIZ)
        from herramientas.lab import sintetico_v3 as sv   # import perezoso: ciclo
        doc["contraste_verdad"] = sv.comparar(doc, verdad)
    with open(a.salida, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"escrito {a.salida}")
    if "contraste_verdad" in doc:
        print(json.dumps(doc["contraste_verdad"]["resumen"], indent=1,
                         ensure_ascii=False))
    print(json.dumps(doc["resumen"], indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
