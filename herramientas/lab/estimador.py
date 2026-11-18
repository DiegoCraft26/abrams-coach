"""Estimador del valor de una compra: AIPW doblemente robusto, con bootstrap por partida.

Qué mide. El efecto de comprar el ítem `a` en un estado dado, **contra la compra
alternativa del shortlist** —no contra «no comprar»—, en puntos porcentuales de
probabilidad de ganar. Es el estimando ATT condicional al estrato de la especificación
(informes/investigacion-2026-11-18/00-ESPECIFICACION-MOTOR-V2.md, §3):

    τ̂(e, a) = media_i∈e [ m̂(a|x_i) + 1{A_i=a}/ê(a|x_i) · (Y_i − m̂(a|x_i)) ]
              − Σ_{a'≠a}  p_e(a')/(1−p_e(a)) · μ̂(e, a')

con `m̂` un modelo logístico (S-learner: el ítem entra como covariables), `ê` conteo
suavizado Dirichlet sobre el shortlist y `p_e` la frecuencia observada. El bootstrap
remuestrea **partidas**, nunca compras: dos compras de la misma partida comparten el
resultado y tratarlas como independientes estrecha el intervalo de forma falsa.

Qué NO hace, dicho aquí para que no se descubra después:

- No identifica causalidad si la habilidad no observada se correlaciona con lo que se
  compra. Con este corpus (sin MMR) eso no se puede descartar; por eso cada cifra sale
  con su E-value y su etiqueta de evidencia.
- El bootstrap **no reajusta** `m̂` ni `ê` en cada réplica (coste: 200 reajustes sobre
  313 k filas). Por tanto el intervalo no incluye la incertidumbre de los modelos
  auxiliares: es más estrecho de lo honesto, no más ancho. Se declara en el artefacto.
- `nw_rel` (riqueza relativa, ver `corpus.riqueza_relativa`) entra en el estado del
  S-learner y como cubeta de la propensión. Sirve para separar «rico porque gana» de
  «gana porque es rico»; no resuelve la habilidad no observada, que sigue haciendo falta
  (no hay MMR en la base). Con `--sin-riqueza` la columna se omite y el estimador vuelve
  al diseño anterior, que es el que se usa para comparar antes/después.
- Con `--comparables` el contrafactual de cada ítem se restringe a los ítems del
  shortlist que están en **su mismo tramo de precio** (≤1 200 / 1 201–2 500 /
  2 501–5 000 / >5 000). Sin el flag el contrafactual es la media del shortlist
  completo, ponderada por frecuencia. El flag no cambia el diseño por defecto.
  Lo que sigue sin resolverse con este cambio: el tramo no comprueba que el jugador
  **pudiera pagar** la alternativa (eso exige oro real, `CurrencyChangedEvent`).

Uso:
    python3 herramientas/lab/estimador.py --bootstrap 200
    python3 herramientas/lab/estimador.py --bootstrap 200 --comparables
    python3 herramientas/lab/estimador.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)

from herramientas.lab import corpus  # noqa: E402

RUTA_MODELO = os.path.join(RAIZ, "datos", "modelo_v2.json")
KAPPA = 200.0            # encogimiento: n/(n+κ) compras para creer el efecto del estrato
ALFA_DIRICHLET = 20.0    # suavizado de la propensión
RIDGE = 1e-2             # regularización del logístico (estabilidad numérica)
N_MEDIDO = 2149          # compras para la etiqueta "medido" (MDE ≤ 3 pp)
N_PRELIMINAR = 150       # por debajo no se publica número
Z_MDE = 2.8016           # z(0.975) + z(0.80)
VAR_RESIDUO = 0.2464     # p(1−p) medido con p = 0.5211
CORTES_RIQUEZA = (0.90, 1.15)   # nw_rel: <0.90 pobre, [0.90, 1.15) normal, ≥1.15 rico
E_MIN = 0.02             # recorte inferior de ê: sin él, una acción rara da pesos 1/ê enormes
# Tramos de precio para `--comparables`. Los cortes caen ENTRE los peldaños de la
# tienda de Deadlock (800 / 1 600 / 3 200 / 6 400), no los parten: cada tramo es un
# peldaño. Se probó además la regla «razón de coste ≤ 1.25×» y en estos 21 ítems
# produce exactamente la misma partición (21/21), así que el resultado no depende de
# dónde se ponga el corte.
CORTES_PRECIO = (1200, 2500, 5000)


# ---------------------------------------------------------------- diseño del modelo
def _base(datos):
    """Covariables del estado (no dependen del ítem que se compre).

    `nw_rel` entra centrada en 1 (0 = justo en la mediana de los 12) y recortada a
    [0.25, 4]: el recorte evita que un jugador con la mediana en 0 en los primeros
    segundos mande la fila a infinito. Si el corpus no trae la columna —el sintético de
    `sintetico.py`, por ejemplo— queda en 0 y el modelo es el de antes.
    """
    t = datos["t"].astype(np.float32)
    fr = corpus.franja(t)
    riqueza = datos.get("nw_rel")
    if riqueza is None:
        rr = np.zeros(len(t), dtype=np.float32)
    else:
        rr = np.clip(np.nan_to_num(np.asarray(riqueza, dtype=np.float32), nan=1.0),
                     0.25, 4.0) - 1.0
    return np.column_stack([
        np.ones(len(t), dtype=np.float32),
        (fr == 0).astype(np.float32), (fr == 1).astype(np.float32),
        datos["nw"].astype(np.float32) / 10000.0,
        datos["n_items"].astype(np.float32) / 12.0,
        datos["inversion"].astype(np.float32) / 20000.0,
        datos["n_activos"].astype(np.float32) / 4.0,
        t / 2400.0,
        rr,
    ]).astype(np.float32)


def _accion(cat, ids):
    """Covariables del ítem (dependen de la acción)."""
    filas = []
    for i in ids:
        m = cat[i]
        slot = m["slot"]
        filas.append([m["coste"] / 6400.0, m["tier"] / 4.0,
                      1.0 if m["activo"] else 0.0,
                      1.0 if slot == "weapon" else 0.0,
                      1.0 if slot == "vitality" else 0.0,
                      1.0 if slot == "spirit" else 0.0])
    return np.asarray(filas, dtype=np.float32)


def tramo_precio(coste, cortes=CORTES_PRECIO):
    """Tramo 0..3 de un coste: ≤1 200, 1 201–2 500, 2 501–5 000, >5 000.

    Un ítem sin coste (0) cae en el tramo 0; en el shortlist actual no hay ninguno.
    La función es deliberadamente explícita y no aprende los cortes de los datos:
    con cortes optimizados el contrafactual se elegiría después de ver el resultado.
    """
    coste = int(coste)
    for j, corte in enumerate(cortes):
        if coste <= corte:
            return j
    return len(cortes)


def tramos_precio(cat, ids, cortes=CORTES_PRECIO):
    """Vector de tramo para cada id (`ids` son claves de `cat`)."""
    return np.asarray([tramo_precio(cat[i]["coste"], cortes) for i in ids],
                      dtype=np.int8)


def _matriz_accion(base, accion_item):
    """Concatena el estado con las covariables del ítem, para todas las filas."""
    return np.hstack([base, np.broadcast_to(accion_item, (len(base), len(accion_item)))])


def ajustar_logistico(X, y, ridge=RIDGE, iteraciones=8, pesos=None):
    """IRLS ponderado con regularización de cresta. Devuelve los coeficientes.

    `pesos` es el peso de remuestreo del bootstrap: sin él, reajustar en cada réplica
    no tendría sentido (se ajustaría siempre con la misma muestra).
    """
    n, k = X.shape
    beta = np.zeros(k, dtype=np.float64)
    Xd = X.astype(np.float64)
    yd = y.astype(np.float64)
    peso_base = (np.ones(n, dtype=np.float64) if pesos is None
                 else np.asarray(pesos, dtype=np.float64))
    for _ in range(iteraciones):
        eta = Xd @ beta
        np.clip(eta, -30, 30, out=eta)
        p = 1.0 / (1.0 + np.exp(-eta))
        # `w0` es la varianza del logístico; el peso de remuestreo multiplica aparte.
        # Antes se dividía por `w` ya multiplicado: una partida no muestreada deja
        # w = 0 y `z` sale infinito (los IC salían NaN).
        w0 = np.maximum(p * (1.0 - p), 1e-6)
        w = w0 * peso_base
        z = eta + (yd - p) / w0
        XtW = Xd.T * w
        hess = XtW @ Xd
        hess.flat[:: k + 1] += ridge
        try:
            nuevo = np.linalg.solve(hess, XtW @ z)
        except np.linalg.LinAlgError:
            break
        if np.max(np.abs(nuevo - beta)) < 1e-8:
            beta = nuevo
            break
        beta = nuevo
    return beta


def predecir(beta, X):
    eta = X.astype(np.float64) @ beta
    np.clip(eta, -30, 30, out=eta)
    return 1.0 / (1.0 + np.exp(-eta))


# ------------------------------------------------------------------- propensiones
def cubeta_riqueza(datos, cortes=CORTES_RIQUEZA):
    """Cubeta 0/1/2 de `nw_rel`: pobre, normal, rico frente a los 12 de la partida.

    Sin la columna (sintético) devuelve todo en 0, que es el diseño anterior. Los cortes
    son 0.90 y 1.15 —redondos, no optimizados— y no parten en terciles porque la
    distribución está apretada alrededor de 1: en la franja 0 dejan 13 % / 52 % / 35 %.
    """
    riqueza = datos.get("nw_rel")
    if riqueza is None:
        return np.zeros(len(datos["item"]), dtype=np.int64)
    rr = np.nan_to_num(np.asarray(riqueza, dtype=np.float64), nan=1.0)
    return np.where(rr < cortes[0], 0, np.where(rr < cortes[1], 1, 2)).astype(np.int64)


def propensiones(datos, corto, franja, accion_idx, alfa=ALFA_DIRICHLET, pesos=None,
                 devolver_tablas=False):
    """ê(a|x) con conteo suavizado Dirichlet dentro de (franja, riqueza, inventario).

    Se estima solo sobre el shortlist de cada franja: restringir el espacio de acciones
    es el primer remedio al soporte deficiente. Las celdas se definen con bucketing
    grueso a propósito: con celdas finas cada una tendría una sola compra.

    Desde 2026-11-18 la riqueza entra dos veces: la absoluta (`nw`, gasto acumulado) y
    la relativa a los 12 (`nw_rel`). Medido en el corpus filtrado: 35 celdas sin la
    relativa, 83 con ella, y la mediana de filas por celda pasa de 388 a 226 — se
    fragmenta poco y el Dirichlet (α=20) apenas encoge.
    """
    n = len(datos["item"])
    corto_global = sorted({i for e in corto for i in corto[e]})
    pos = {item: j for j, item in enumerate(corto_global)}
    nw_b = np.clip(datos["nw"].astype(np.int64) // 4000, 0, 5)
    inv_b = np.clip(datos["n_items"].astype(np.int64) // 4, 0, 2)
    rr_b = cubeta_riqueza(datos)
    celda = (franja.astype(np.int64) * 1000 + nw_b * 100 + rr_b * 10
             + inv_b).astype(np.int64)
    _, celda = np.unique(celda, return_inverse=True)

    # Frecuencia marginal de cada ítem del shortlist: π̄(a).
    cuenta_total = np.bincount(accion_idx[accion_idx >= 0],
                               minlength=len(corto_global)).astype(np.float64)
    pi = (cuenta_total + 1.0) / (cuenta_total.sum() + len(corto_global))

    # Conteo por celda y acción (ponderado si viene del bootstrap).
    n_celdas = int(celda.max()) + 1
    clave = celda * len(corto_global) + np.where(accion_idx >= 0, accion_idx, 0)
    valido = accion_idx >= 0
    w_conteo = (None if pesos is None else np.asarray(pesos, dtype=np.float64)[valido])
    tabla = np.bincount(clave[valido], weights=w_conteo,
                        minlength=n_celdas * len(corto_global)).reshape(
                            n_celdas, len(corto_global)).astype(np.float64)
    total_celda = tabla.sum(axis=1, keepdims=True)
    suave = (tabla + alfa * pi[None, :]) / (total_celda + alfa)
    # ê de cada fila para cada acción del shortlist -> matriz (n, 8)
    e = suave[celda]
    salida = np.clip(e, E_MIN, 0.98)
    if devolver_tablas:
        return salida, {"celda": celda, "suave": suave, "pi": pi,
                        "corto_global": corto_global,
                        "nw_b": nw_b, "inv_b": inv_b, "franja": franja}
    return salida, corto_global


# ------------------------------------------------------------------------- AIPW
def _mu_estratos(M, y, e, accion_idx, franja, w=None):
    """μ̂(e, a) por estrato: media (o media ponderada) de la parte AIPW."""
    n_estratos = 3
    n_acc = M.shape[1]
    mu = np.zeros((n_estratos, n_acc), dtype=np.float64)
    for e_idx in range(n_estratos):
        sel = franja == e_idx
        if not np.any(sel):
            continue
        ww = np.ones(int(sel.sum()), dtype=np.float64) if w is None else w[sel]
        den = ww.sum()
        if den <= 0:
            continue
        Msel = M[sel]
        ysel = y[sel].astype(np.float64)
        esel = e[sel]
        asel = accion_idx[sel]
        # Corrección de la parte no elegida: 1{A=a}/ê(a) (y - m̂(a))
        correccion = np.zeros_like(Msel)
        valido = asel >= 0
        filas = np.nonzero(valido)[0]
        correccion[filas, asel[valido]] = (
            (ysel[valido] - Msel[filas, asel[valido]])
            / esel[filas, asel[valido]])
        compuesto = Msel + correccion
        mu[e_idx] = (ww @ compuesto) / den
    return mu


def _tau(mu, frec):
    """τ̂(e,a) contra la alternativa del shortlist, con la frecuencia observada."""
    n_acc = mu.shape[1]
    tau = np.zeros_like(mu)
    for e_idx in range(mu.shape[0]):
        m = mu[e_idx]
        p = frec[e_idx]
        total = float((p @ m))
        for a in range(n_acc):
            if p[a] >= 0.999:
                tau[e_idx, a] = 0.0
                continue
            alterna = (total - p[a] * m[a]) / max(1e-9, (1.0 - p[a]))
            tau[e_idx, a] = m[a] - alterna
    return tau


def _tau_comparables(mu, frec, tramo):
    """τ̂(e,a) contra la media de los ítems del shortlist del MISMO tramo de precio.

    La alternativa se renormaliza dentro del tramo:
        alterna(e,a) = Σ_{a'∈tramo(a), a'≠a} q(a') μ(e,a') / (1 − q(a)),
        q(a') = frec(e,a') / Σ_{a''∈tramo(a)} frec(e,a'').
    Si en una franja el tramo solo tiene compras de `a` (q(a)=1), el contrafactual no
    existe y τ queda NaN; la agregación omite ese estrato y lo publica. No se cae al
    shortlist completo: eso reintroduciría el precio que se quiere quitar.
    """
    n_acc = mu.shape[1]
    tau = np.full(mu.shape, np.nan, dtype=np.float64)
    for e_idx in range(mu.shape[0]):
        m = mu[e_idx]
        p = frec[e_idx]
        for a in range(n_acc):
            mismo = tramo == tramo[a]
            masa = float(p[mismo].sum())
            if masa <= 0:
                continue
            qa = float(p[a]) / masa
            if qa >= 1.0 - 1e-12:
                continue
            q = p[mismo] / masa
            total = float(q @ m[mismo])
            alterna = (total - qa * m[a]) / (1.0 - qa)
            tau[e_idx, a] = m[a] - alterna
    return tau


def _agregar_tau(tau, n_ea):
    """Agrega τ por ítem ponderando por compras e ignorando estratos sin comparable.

    Acepta `tau` de forma (estratos, acciones) o (réplicas, estratos, acciones).
    En el diseño por defecto no hay NaN y el resultado es el de siempre.
    """
    valido = ~np.isnan(tau)
    if tau.ndim == 2:
        num = np.nansum(np.where(valido, tau * n_ea, 0.0), axis=0)
        den = np.where(valido, n_ea, 0.0).sum(axis=0)
        salida = np.full(num.shape, np.nan, dtype=np.float64)
        return np.divide(num, den, out=salida, where=den > 0)
    num = np.nansum(np.where(valido, tau * n_ea[None, :, :], 0.0), axis=1)
    den = np.where(valido, n_ea[None, :, :], 0.0).sum(axis=1)
    salida = np.full(num.shape, np.nan, dtype=np.float64)
    return np.divide(num, den, out=salida, where=den > 0)


def estimar(datos=None, cat=None, bootstrap=200, semilla=7, verbose=True,
            prob_verdad=None, riqueza=True, comparables=False):
    """Corre el estimador completo y devuelve el artefacto (sin escribir).

    `riqueza=False` quita `nw_rel` de `datos` antes de ajustar: el modelo vuelve al
    diseño anterior con el mismo código, el mismo shortlist y la misma semilla. Es lo
    que hace comparables el «antes» y el «después» sin tener que creerse dos scripts.

    `comparables=True` restringe el contrafactual de cada ítem a los ítems del shortlist
    de su mismo tramo de precio (`CORTES_PRECIO`). Sin el flag, el contrafactual es la
    media del shortlist completo: el comportamiento por defecto no cambia.
    """
    t0 = time.perf_counter()
    cat = cat or corpus.catalogo()
    datos = datos or corpus.con_inventario(corpus.cargar(), cat)
    datos = dict(datos)
    info_riqueza = datos.get("riqueza") or {}
    if not riqueza:
        for clave in ("nw_rel", "nw_med", "nw_pct", "nw_n"):
            datos.pop(clave, None)
    fr = corpus.franja(datos["t"])
    corto = corpus.shortlist(datos)

    # Espacio de acciones común (unión de los shortlists), para una matriz M única.
    corto_global = sorted({i for e in corto for i in corto[e]})
    # Tramo de precio de cada acción, solo si se pide el contrafactual restringido.
    # Se calcula del catálogo (`data/items.json`), no del coste observado en la compra:
    # el tramo es una propiedad del ítem, no de cuánto pagó ese jugador.
    tramo = (tramos_precio(cat, [datos["ids"][i] for i in corto_global])
             if comparables else None)
    pos = {item: j for j, item in enumerate(corto_global)}
    accion_idx = np.full(len(datos["item"]), -1, dtype=np.int16)
    dentro = np.isin(datos["item"], corto_global)
    accion_idx[dentro] = [pos[int(i)] for i in datos["item"][dentro]]

    # Se excluyen las compras fuera del shortlist ANTES de estimar. Antes entraban en
    # la media de μ̂ pero no en la cuenta de compras por (franja, ítem): el denominador
    # de μ̂ y el peso de τ no hablaban del mismo conjunto y el efecto del ítem con
    # señal salía 1.6 pp por encima de la verdad (visto en el corpus sintético).
    if not np.all(dentro):
        n_todas = len(datos["item"])
        datos = {k: (v[dentro] if isinstance(v, np.ndarray) and len(v) == n_todas else v)
                 for k, v in datos.items()}
        fr = fr[dentro]
        accion_idx = accion_idx[dentro]

    e_hat, tablas_e = propensiones(datos, corto, fr, accion_idx, devolver_tablas=True)
    # Ocupación de las celdas de propensión: si el bucketing fragmenta de más, cada
    # celda tendría una compra y ê sería la marginal disfrazada. Se publica, no se estima.
    celdas_prop = int(tablas_e["celda"].max()) + 1 if len(tablas_e["celda"]) else 0
    ocupacion = (np.bincount(tablas_e["celda"]) if len(tablas_e["celda"])
                 else np.array([0]))
    base = _base(datos)
    # Identidad del ítem: sin una columna por acción, dos ítems con el mismo coste,
    # tier y slot comparten predicción y el modelo no puede distinguirlos (medido en
    # el corpus sintético: sesgo de 1.7 pp con las covariables estáticas solas).
    estaticas = _accion(cat, [datos["ids"][i] for i in corto_global])
    acc = np.hstack([estaticas,
                     np.eye(len(corto_global), dtype=np.float32)])

    # Ajuste del desenlace sobre la acción observada (S-learner).
    Xobs = np.hstack([base, acc[accion_idx.clip(0)]])
    validas = accion_idx >= 0
    beta = ajustar_logistico(Xobs[validas], datos["y"][validas])

    # M[i, a] = m̂(x_i, a), solo para filas con acción en el shortlist.
    M = np.empty((len(datos["item"]), len(corto_global)), dtype=np.float32)
    for a in range(len(corto_global)):
        M[:, a] = predecir(beta, np.hstack([base, np.broadcast_to(
            acc[a], (len(base), len(acc[a])))]))

    mu = _mu_estratos(M, datos["y"], e_hat, accion_idx, fr)
    frec = np.zeros((3, len(corto_global)), dtype=np.float64)
    for e_idx in range(3):
        sel = (fr == e_idx) & validas
        if np.any(sel):
            cuenta = np.bincount(accion_idx[sel], minlength=len(corto_global))
            frec[e_idx] = cuenta / cuenta.sum()
    tau = _tau_comparables(mu, frec, tramo) if comparables else _tau(mu, frec)

    # Partidas distintas por ítem: el bootstrap agrupa por partida y ese es el n que
    # de verdad sostiene el intervalo (no el número de compras).
    partidas_item = np.zeros(len(corto_global), dtype=np.int64)
    for a in range(len(corto_global)):
        sel = accion_idx == a
        if np.any(sel):
            partidas_item[a] = len(np.unique(datos["match"][sel]))

    # Compras por (estrato, ítem) y agregado por ítem.
    n_ea = np.zeros_like(frec)
    for e_idx in range(3):
        sel = (fr == e_idx) & validas
        if np.any(sel):
            n_ea[e_idx] = np.bincount(accion_idx[sel], minlength=len(corto_global))
    n_a = n_ea.sum(axis=0)
    if comparables:
        # Los estratos sin comparable (el tramo solo tiene compras de `a`) son NaN y
        # se omiten del agregado; `n_a` sigue siendo el total de compras del ítem.
        tau_item = _agregar_tau(tau, n_ea)
        sin_comparable = sorted(
            datos["ids"][corto_global[a]] for a in range(len(corto_global))
            if n_a[a] > 0 and not np.isfinite(tau_item[a]))
    else:
        tau_item = np.zeros(len(corto_global))
        for a in range(len(corto_global)):
            if n_a[a] > 0:
                tau_item[a] = float((n_ea[:, a] * tau[:, a]).sum() / n_a[a])
        sin_comparable = []

    if verbose:
        print(f"modelo ajustado en {time.perf_counter() - t0:.1f} s · "
              f"{int(validas.sum()):,} filas en shortlist", file=sys.stderr)

    # ---------------- bootstrap por partida (reajustando en cada réplica) --------
    # Con m̂ y ê fijos el intervalo sale demasiado estrecho: el AIPW cancela en la
    # misma muestra los errores del modelo y el bootstrap no los ve. Medido con el
    # corpus sintético: cobertura 83 % y 20 % de falsos positivos con IC fijos. Se
    # reajustan los dos modelos dentro de cada réplica (cuesta ~0.5 s por réplica).
    partidas, match_idx = np.unique(datos["match"], return_inverse=True)
    n_partidas = len(partidas)
    rng = np.random.default_rng(semilla)
    rep_tau = np.empty((bootstrap, 3, len(corto_global)), dtype=np.float32)
    y64 = datos["y"].astype(np.float64)
    for b in range(bootstrap):
        # Pesos multinomiales por partida = remuestreo con reemplazo.
        pesos = rng.multinomial(n_partidas, np.full(n_partidas, 1.0 / n_partidas))
        w_fila = pesos[match_idx].astype(np.float64)
        e_b, _ = propensiones(datos, corto, fr, accion_idx, pesos=w_fila)
        beta_b = ajustar_logistico(Xobs[validas], datos["y"][validas],
                                   pesos=w_fila[validas])
        M_b = np.empty_like(M)
        for a in range(len(corto_global)):
            M_b[:, a] = predecir(beta_b, np.hstack([base, np.broadcast_to(
                acc[a], (len(base), len(acc[a])))]))
        mu_b = _mu_estratos(M_b, y64, e_b, accion_idx, fr, w=w_fila)
        rep_tau[b] = (_tau_comparables(mu_b, frec, tramo) if comparables
                      else _tau(mu_b, frec))
        if verbose and (b + 1) % 50 == 0:
            print(f"  bootstrap {b + 1}/{bootstrap}", file=sys.stderr)

    if comparables:
        rep_item = _agregar_tau(rep_tau, n_ea)
    else:
        rep_item = np.zeros((bootstrap, len(corto_global)), dtype=np.float32)
        for a in range(len(corto_global)):
            if n_a[a] > 0:
                rep_item[:, a] = (rep_tau[:, :, a] * n_ea[:, a][None, :]).sum(
                    axis=1) / n_a[a]

    # ---------------- artefacto ----------------
    items = {}
    for a, item in enumerate(corto_global):
        # Sin compras no hay fila; con comparables, un ítem cuyo tramo no tiene
        # alternativa en ninguna franja tampoco tiene efecto que publicar.
        if n_a[a] <= 0 or not np.isfinite(tau_item[a]):
            continue
        rep = rep_item[:, a] * 100.0          # puntos porcentuales
        efecto = float(tau_item[a] * 100.0)
        bajo90 = float(np.percentile(rep, 5))
        alto90 = float(np.percentile(rep, 95))
        bajo95 = float(np.percentile(rep, 2.5))
        alto95 = float(np.percentile(rep, 97.5))
        n = int(n_a[a])
        p0 = 0.5211
        mde = Z_MDE * float(np.sqrt(VAR_RESIDUO / max(1, n))) * 100.0
        # E-value sobre el riesgo relativo (VanderWeele y Ding, 2017).
        p1 = min(0.999, max(0.001, p0 + efecto / 100.0))
        rr = p1 / p0
        # El E-value se define sobre el riesgo relativo en la dirección del efecto: si
        # el efecto es negativo se usa 1/RR. Un E-value < 1.5 significa que un confusor
        # moderado —la habilidad, que NO está en la base— explica el hallazgo entero.
        rr_efecto = rr if rr >= 1.0 else (1.0 / max(1e-9, rr))
        evalue = rr_efecto + np.sqrt(max(0.0, rr_efecto * (rr_efecto - 1.0)))
        if n >= N_MEDIDO:
            etiqueta = "medido"
        elif n >= N_PRELIMINAR:
            etiqueta = "preliminar"
        elif n >= 40:
            etiqueta = "debil"
        else:
            etiqueta = "sin_senal"
        # Estabilidad al encogimiento: κ ∈ {100, 200, 400} sobre el efecto del estrato.
        signos = []
        for kappa in (100.0, 200.0, 400.0):
            valores = []
            for e_idx in range(3):
                if (n_a[a] > 0 and n_ea[e_idx, a] > 0
                        and np.isfinite(tau[e_idx, a])):
                    encogido = tau_item[a] + (tau[e_idx, a] - tau_item[a]) * (
                        n_ea[e_idx, a] / (n_ea[e_idx, a] + kappa))
                    valores.append(encogido)
            signos.append(1 if sum(valores) >= 0 else -1)
        estable = len(set(signos)) == 1
        fila = {
            "nombre": cat[datos["ids"][item]]["nombre"],
            "efecto_pp": round(efecto, 3),
            "ic90": [round(bajo90, 3), round(alto90, 3)],
            "ic95": [round(bajo95, 3), round(alto95, 3)],
            "lcb90": round(bajo90, 3),
            "n": n,
            "n_por_franja": {str(e_idx): int(n_ea[e_idx, a])
                             for e_idx in range(3) if n_ea[e_idx, a] > 0},
            "n_partidas": int(partidas_item[a]),
            "mde_pp": round(mde, 3),
            "evalue": round(float(evalue), 3),
            "etiqueta": etiqueta,
            "estable_kappa": bool(estable),
            "por_franja": {
                str(e_idx): round(float(tau[e_idx, a] * 100.0), 3)
                for e_idx in range(3)
                if n_ea[e_idx, a] > 0 and np.isfinite(tau[e_idx, a])},
            # IC90 del efecto DENTRO de cada franja, del mismo bootstrap. Sin esto la
            # franja solo tenía punto y no había forma de decir si el cambio era señal.
            "por_franja_ic90": {
                str(e_idx): [round(float(np.percentile(rep_tau[:, e_idx, a] * 100.0, 5)), 3),
                             round(float(np.percentile(rep_tau[:, e_idx, a] * 100.0, 95)), 3)]
                for e_idx in range(3)
                if n_ea[e_idx, a] > 0 and np.isfinite(tau[e_idx, a])},
        }
        if comparables:
            fila["tramo_precio"] = int(tramo[a])
            fila["coste"] = int(cat[datos["ids"][item]]["coste"])
            fila["n_comparables_por_franja"] = {
                str(e_idx): int(np.sum((tramo == tramo[a]) & (n_ea[e_idx] > 0))) - 1
                for e_idx in range(3) if n_ea[e_idx, a] > 0}
        items[datos["ids"][item]] = fila

    # Verdad de referencia cuando se valida con corpus sintético: se pasa P(Y=1|a) y
    # se calcula el mismo estimando (τ contra la alternativa del shortlist, ponderado
    # por las mismas compras por estrato). Sin esto, la «verdad» sería otro número y
    # la validación mediría una diferencia que no existe.
    verdad_items = {}
    if prob_verdad:
        mu_t = np.zeros((3, len(corto_global)), dtype=np.float64)
        for a, item in enumerate(corto_global):
            valor = prob_verdad.get(datos["ids"][item])
            if valor is not None:
                mu_t[:, a] = float(valor)
        tau_t = (_tau_comparables(mu_t, frec, tramo) if comparables
                 else _tau(mu_t, frec))
        tau_t_item = _agregar_tau(tau_t, n_ea) if comparables else None
        for a, item in enumerate(corto_global):
            if n_a[a] <= 0:
                continue
            if comparables:
                if np.isfinite(tau_t_item[a]):
                    verdad_items[datos["ids"][item]] = round(
                        float(tau_t_item[a] * 100.0), 3)
            else:
                verdad_items[datos["ids"][item]] = round(
                    float((n_ea[:, a] * tau_t[:, a]).sum() / n_a[a] * 100.0), 3)

    # El hash que va en el artefacto es el de la BASE que se acaba de leer, no el que
    # diga `corpus.json`: copiarlo del corpus hacía el guard circular (el artefacto se
    # validaba contra el mismo archivo del que había copiado el hash) y el modo CIEGO
    # no podía detectar una base re-estimada sin volver a congelar.
    congelado = corpus.leer_congelado() or {}
    hash_real = corpus.sha256()
    if congelado.get("sha256_db") and congelado["sha256_db"] != hash_real:
        print("AVISO: el corpus congelado no coincide con la base; el artefacto "
              "quedará en modo CIEGO hasta re-congelar.", file=sys.stderr)
    doc = {
        "generado": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "corpus": {**congelado, "sha256_db": hash_real,
                   "sha256_corpus": congelado.get("sha256_db")},
        "metodo": {
            "estimador": ("AIPW (Dudík-Langford-Li 2011) con contrafactual "
                          + ("del mismo tramo de precio" if comparables
                             else "del shortlist")),
            "desenlace": "logístico S-learner con covariables del ítem",
            "propension": f"Dirichlet alpha={ALFA_DIRICHLET}, recorte [0.02, 0.98]",
            "bootstrap": (f"{bootstrap} réplicas agrupadas por partida, m̂ y ê reajustados en cada réplica"),
            "kappa": KAPPA,
            "semilla": semilla,
            "riqueza_relativa": bool(riqueza),
            "riqueza": (info_riqueza if riqueza else None),
            "comparables": bool(comparables),
            "comparables_definicion": (
                "contrafactual restringido a ítems del shortlist con coste en el "
                "mismo tramo: <=1200, 1201-2500, 2501-5000, >5000; en este shortlist "
                "coincide con la regla de razón de coste <=1.25x (21/21 ítems)"
                if comparables else None),
            "cortes_precio": list(CORTES_PRECIO) if comparables else None,
            "tramos_precio": (
                {str(t): sorted(datos["ids"][corto_global[a]]
                                for a in range(len(corto_global)) if tramo[a] == t)
                 for t in range(len(CORTES_PRECIO) + 1)}
                if comparables else None),
            "items_sin_comparable": sin_comparable if comparables else None,
            "celdas_propension": celdas_prop,
            "filas_por_celda_mediana": int(np.median(ocupacion)),
            "cortes_riqueza": list(CORTES_RIQUEZA),
            "partidas": int(n_partidas),
            "filas_shortlist": int(validas.sum()),
            "shortlist": {str(e): [datos["ids"][i] for i in corto[e]]
                          for e in corto},
        },
        "items": items,
    }
    if verdad_items:
        doc["verdad_items"] = verdad_items
    if verbose:
        print(f"listo en {time.perf_counter() - t0:.1f} s", file=sys.stderr)
    return doc


def guardar(doc, ruta=RUTA_MODELO):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    temporal = ruta + ".tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(temporal, ruta)
    return ruta


def main():
    ap = argparse.ArgumentParser(description="Estima el valor de cada compra")
    ap.add_argument("--bootstrap", type=int, default=200)
    ap.add_argument("--semilla", type=int, default=7)
    ap.add_argument("--salida", default=RUTA_MODELO)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--sin-riqueza", action="store_true",
                    help="omite nw_rel: reproduce el diseño anterior (antes/después)")
    ap.add_argument("--comparables", action="store_true",
                    help="contrafactual restringido a ítems del mismo tramo de precio")
    a = ap.parse_args()
    doc = estimar(bootstrap=a.bootstrap, semilla=a.semilla,
                  riqueza=not a.sin_riqueza, comparables=a.comparables)
    if not a.json:
        guardar(doc, a.salida)
        print(f"escrito {a.salida}")
    print(json.dumps({k: v for k, v in list(doc["items"].items())[:8]},
                     indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
