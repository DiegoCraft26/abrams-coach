"""Corpus de compras de Abrams: de `datos/lab.db` a matrices listas para estimar.

Por qué existe. El laboratorio medía ΔW con el estado `(minuto//360, net_worth//6000)`,
que colapsa todo lo que pasa del minuto 30 en una sola celda y promedia por encima de
discontinuidades reales del juego (el net worth cuantiza: 53.6 % de las filas repiten el
valor anterior). La especificación del motor v2 (informes/investigacion-2026-11-18)
decide medir el efecto **por ítem**, con franjas de tiempo como covariable y el
inventario reconstruido como parte del estado.

Este módulo hace tres cosas y solo tres:

1. `cargar()` lee las compras de Abrams y las devuelve como arrays de numpy. Por defecto
   añade también la covariable de riqueza relativa (`riqueza_relativa()`).
2. `con_inventario()` reconstruye, para cada compra, lo que el jugador ya tenía en ese
   instante (nº de ítems, inversión acumulada, activos). Está medido en la base: 0
   repeticiones ítem/partida, así que el inventario es reconstruible exacto.
3. `riqueza_relativa()` calcula `nw_rel` = net worth del jugador dividido por la mediana
   de los 12 jugadores de esa partida en el mismo instante. Existe porque `net_worth` de
   `compras_api` es ≈ gasto acumulado y no distingue «rico porque gana» de «gana porque es
   rico»: sin una medida relativa, comprar caro temprano parece causar la victoria.
4. `congelar()` escribe `datos/corpus.json` con los conteos calculados **desde el
   código**, el sha256 de la base y la fecha de corte. Si el hash no coincide, el motor
   arranca en modo CIEGO y lo dice: ningún número sale de un corpus que no es el suyo.

Nada de esto decide: solo describe los datos con fidelidad comprobable.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import time

import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUTA_DB = os.path.join(RAIZ, "datos", "lab.db")
RUTA_CORPUS = os.path.join(RAIZ, "datos", "corpus.json")
RUTA_ITEMS = os.path.join(RAIZ, "data", "items.json")
HEROE = 6                      # Abrams
FRANJAS_S = (900.0, 1800.0)    # 0-15 min, 15-30 min, 30+ min
# Solo partidas completas de 12 jugadores. Medido el 2026-11-18: 2 747 de las 20 500
# partidas traen 8 jugadores y duran 894 s de media contra 2 228 s de las de 12. No es
# una muestra incompleta: es otro modo, con otra tienda y otra economía (allí el ítem
# más comprado por Abrams es Lifestrike, que en 12 jugadores ni aparece en el top 3).
# Mezclarlas contaminaba el 11.5 % de las compras de Abrams.
MIN_JUGADORES = 12


def sha256(ruta=RUTA_DB, bloque=1 << 20):
    """sha256 del archivo, por bloques (la base pesa 359 MB)."""
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        while True:
            trozo = f.read(bloque)
            if not trozo:
                break
            h.update(trozo)
    return h.hexdigest()


def catalogo():
    """id -> {nombre, coste, tier, slot, activo} desde data/items.json."""
    with open(RUTA_ITEMS, encoding="utf-8") as f:
        crudo = json.load(f)
    valores = crudo.values() if isinstance(crudo, dict) else crudo
    salida = {}
    for v in valores:
        if not v.get("id"):
            continue
        salida[str(v["id"])] = {
            "nombre": v.get("name") or str(v["id"]),
            "coste": int(v.get("cost") or 0),
            "tier": int(v.get("item_tier") or 0),
            "slot": v.get("item_slot_type") or "weapon",
            "activo": bool(v.get("is_active_item")),
        }
    return salida


def _iter_partidas(ruta, partidas, bloque=200_000):
    """Corta `compras_api` en bloques por partida: (match_id, slot, t, nw) de los 12.

    Se lee **solo** `match_id, player_slot, t, net_worth` de las partidas pedidas y se
    entrega una partida a la vez. Leer los 3.9 M de filas de golpe en una lista de
    tuplas costaría ~400 MB de Python; por bloques no pasa de ~50 MB.
    """
    partidas = np.sort(np.asarray(partidas, dtype=np.int64))
    con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    try:
        cur = con.execute(
            "SELECT match_id, player_slot, t, net_worth FROM compras_api "
            "ORDER BY match_id, player_slot, t")
        pendiente = None
        while True:
            lote = cur.fetchmany(bloque)
            if not lote:
                break
            mid = np.fromiter((f[0] for f in lote), dtype=np.int64, count=len(lote))
            slot = np.fromiter((f[1] for f in lote), dtype=np.int16, count=len(lote))
            tt = np.fromiter((f[2] if f[2] is not None else 0.0 for f in lote),
                             dtype=np.float64, count=len(lote))
            nw = np.fromiter((f[3] if f[3] is not None else 0 for f in lote),
                             dtype=np.float64, count=len(lote))
            if pendiente is not None:
                mid = np.concatenate([pendiente[0], mid])
                slot = np.concatenate([pendiente[1], slot])
                tt = np.concatenate([pendiente[2], tt])
                nw = np.concatenate([pendiente[3], nw])
                pendiente = None
            # La última partida del bloque puede seguir en el siguiente.
            corte = int(np.nonzero(mid == mid[-1])[0][0])
            if corte == 0:
                pendiente = (mid, slot, tt, nw)
                continue
            pendiente = (mid[corte:], slot[corte:], tt[corte:], nw[corte:])
            bloques = [(mid[:corte], slot[:corte], tt[:corte], nw[:corte])]
            for m, s, t, v in bloques:
                u, ini, cnt = np.unique(m, return_index=True, return_counts=True)
                dentro = np.isin(u, partidas)
                for j in np.nonzero(dentro)[0]:
                    a = ini[j]
                    yield int(u[j]), s[a:a + cnt[j]], t[a:a + cnt[j]], v[a:a + cnt[j]]
        if pendiente is not None:
            m, s, t, v = pendiente
            u, ini, cnt = np.unique(m, return_index=True, return_counts=True)
            dentro = np.isin(u, partidas)
            for j in np.nonzero(dentro)[0]:
                a = ini[j]
                yield int(u[j]), s[a:a + cnt[j]], t[a:a + cnt[j]], v[a:a + cnt[j]]
    finally:
        con.close()


def riqueza_relativa(datos, ruta=RUTA_DB, verbose=False, columnas=12):
    """Añade `nw_rel`: net worth del jugador / mediana de los 12 en ese instante.

    Por qué. `net_worth` de `compras_api` es ≈ gasto acumulado del propio jugador: un
    número absoluto que mezcla «ya iba ganando» con «compró caro». Lo que hace falta para
    separarlos es una medida **relativa a los otros 11 de la misma partida en el mismo
    segundo**: si Abrams está en 1.4× la mediana, es rico frente a sus pares; si está en
    0.7×, va pobre.

    Qué se usa como «instante». Los ticks de compra **no coinciden** entre jugadores
    (medido: en 200 filas de una partida hay 190 valores de `t` distintos, así que
    agrupar por `(match_id, t)` exacto deja ~1 jugador por grupo y la mediana sería la de
    uno solo). Por eso cada jugador aporta su **último net worth conocido en o antes de
    `t`** (escalera, sin interpolar): es el valor vigente al momento de la compra. La
    mediana se toma sobre los que ya tienen alguna compra; `n_presentes` dice cuántos son
    (mediana 11 de 12 en todas las franjas).

    Qué se devuelve, y por qué el cociente y no el percentil. Se guardan los dos:
    `nw_rel` (cociente, la que entra al modelo) y `nw_pct` (percentil 0-1 dentro de la
    partida, solo diagnóstico). Se elige el cociente porque conserva la magnitud —«1.4× la
    mediana»—, que es justo lo que confunde en franjas tempranas: un percentil lleva a la
    misma casilla a quien va 5 % arriba y a quien va 3× arriba. Ambas son monótonas entre
    sí, así que el percentil sirve de comprobación de que el resultado no depende de la
    escala elegida.

    Límite declarado: el valor del propio jugador es el de su fila (exacto en `t`) y el de
    los demás puede tener decenas de segundos de antigüedad; eso sesga el cociente un poco
    hacia arriba (mediana 1.07 en vez de 1.00). Es un sesgo de nivel, no de orden: no
    cambia quién es rico y quién no.
    """
    n = len(datos["t"])
    partidas_corpus = datos["match"]
    # Índice de filas del corpus agrupadas por partida (el array ya viene ordenado, pero
    # se ordena igual: si alguien filtra antes de llamar, el orden se conserva).
    orden = np.argsort(partidas_corpus, kind="stable")
    _, ini_d, cnt_d = np.unique(partidas_corpus[orden], return_index=True,
                                return_counts=True)
    ini_d = orden[ini_d]

    nw_rel = np.full(n, np.nan, dtype=np.float32)
    nw_med = np.full(n, np.nan, dtype=np.float32)
    nw_pct = np.full(n, np.nan, dtype=np.float32)
    n_pres = np.zeros(n, dtype=np.int16)

    unicas = np.unique(partidas_corpus)
    filas = 0
    for partida, slot, tt, nw in _iter_partidas(ruta, unicas):
        # Índice dentro de `datos` de las compras de Abrams en esta partida.
        j = int(np.searchsorted(unicas, partida))
        a, b = int(ini_d[j]), int(ini_d[j] + cnt_d[j])
        pos = orden[a:b]
        tk = datos["t"][pos].astype(np.float64)
        propia = datos["nw"][pos].astype(np.float64)
        # Escalera por jugador: orden por (slot, t) y un corte por slot.
        o = np.lexsort((tt, slot))
        slot, tt, nw = slot[o], tt[o], nw[o]
        cortes = np.searchsorted(slot, np.arange(columnas + 1))
        vals = np.full((len(tk), columnas), np.nan, dtype=np.float64)
        for c in range(columnas):
            lo, hi = int(cortes[c]), int(cortes[c + 1])
            if hi <= lo:
                continue
            idx = np.searchsorted(tt[lo:hi], tk, side="right") - 1
            ok = idx >= 0
            vals[ok, c] = nw[lo:hi][idx[ok]]
        presente = ~np.isnan(vals)
        cuenta = presente.sum(axis=1)
        # Sin nadie presente (la compra es anterior a la primera de los otros 11): se
        # rellena una columna para que `nanmedian` no avise; esas filas caen en `valido`.
        vacias = np.nonzero(cuenta == 0)[0]
        if len(vacias):
            vals[vacias, 0] = 0.0
        med = np.nanmedian(vals, axis=1)
        if len(vacias):
            vals[vacias, 0] = np.nan
        valido = (cuenta > 0) & (med > 0)
        nw_rel[pos[valido]] = (propia[valido] / med[valido]).astype(np.float32)
        nw_med[pos[valido]] = med[valido].astype(np.float32)
        # Percentil con los empates repartidos (el propio valor cuenta 0.5).
        rango = ((vals < propia[:, None]).sum(axis=1)
                 + 0.5 * (vals == propia[:, None]).sum(axis=1))
        nw_pct[pos[valido]] = (rango[valido] / cuenta[valido]).astype(np.float32)
        n_pres[pos] = cuenta.astype(np.int16)
        filas += len(pos)

    datos["nw_rel"] = nw_rel
    datos["nw_med"] = nw_med
    datos["nw_pct"] = nw_pct
    datos["nw_n"] = n_pres
    validos = np.isfinite(nw_rel)
    datos["riqueza"] = {
        "definicion": "nw_propio / mediana_nw_12(t) con escalera (ultimo valor <= t)",
        "filas": int(filas),
        "con_valor": int(validos.sum()),
        "mediana_nw_rel": round(float(np.median(nw_rel[validos])), 4) if validos.any() else None,
        "mediana_jugadores_presentes": int(np.median(n_pres)) if n else 0,
    }
    if verbose:
        print(f"nw_rel: {int(validos.sum()):,} de {n:,} filas · "
              f"mediana {datos['riqueza']['mediana_nw_rel']}", file=sys.stderr)
    return datos


def cargar(heroe=HEROE, ruta=RUTA_DB, riqueza=True):
    """Compras de un héroe, ordenadas por partida y orden de compra.

    Devuelve un dict de arrays de numpy. `item` es un array de enteros que indexa
    `ids` (la lista de ids en orden alfabético) para que numpy pueda agrupar sin
    repetir cadenas. Con `riqueza=True` añade `nw_rel` (ver `riqueza_relativa`).
    """
    con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    try:
        filas = con.execute("""
            SELECT c.match_id, c.player_slot, c.orden, c.t, c.item_id,
                   c.coste, c.net_worth, c.vendido_t, j.ganador
            FROM compras_api c
            JOIN jugadores_api j ON j.match_id = c.match_id
                                AND j.player_slot = c.player_slot
            JOIN (SELECT match_id FROM jugadores_api
                  GROUP BY match_id HAVING COUNT(*) = ?
                 ) completo ON completo.match_id = c.match_id
            WHERE j.hero_id = ? AND j.ganador IS NOT NULL
            ORDER BY c.match_id, c.player_slot, c.orden
        """, (MIN_JUGADORES, int(heroe))).fetchall()
    finally:
        con.close()
    if not filas:
        raise RuntimeError(f"no hay compras de Abrams en {ruta}")
    ids = sorted({str(f[4]) for f in filas})
    posicion = {x: i for i, x in enumerate(ids)}
    n = len(filas)
    out = {
        "ids": ids,
        "match": np.empty(n, dtype=np.int64),
        "slot": np.empty(n, dtype=np.int16),
        "orden": np.empty(n, dtype=np.int16),
        "t": np.empty(n, dtype=np.float32),
        "item": np.empty(n, dtype=np.int32),
        "coste": np.empty(n, dtype=np.int32),
        "nw": np.empty(n, dtype=np.int64),
        "vendido_t": np.empty(n, dtype=np.float32),
        "y": np.empty(n, dtype=np.int8),
    }
    for i, f in enumerate(filas):
        out["match"][i] = f[0]
        out["slot"][i] = f[1]
        out["orden"][i] = f[2]
        out["t"][i] = f[3]
        out["item"][i] = posicion[str(f[4])]
        out["coste"][i] = f[5] or 0
        out["nw"][i] = f[6] or 0
        out["vendido_t"][i] = f[7] or 0
        out["y"][i] = f[8]
    if riqueza:
        out = riqueza_relativa(out, ruta=ruta)
    return out


def con_inventario(datos, cat):
    """Reconstruye el inventario al momento de cada compra.

    Una compra cuenta como poseída si ocurrió antes **y** no se vendió antes de `t`
    (`vendido_t == 0` es el centinela de «no vendido»). Se calcula por barrido en el
    orden ya establecido del corpus: mismo (partida, slot) y `orden` creciente.
    """
    n = len(datos["t"])
    n_items = np.zeros(n, dtype=np.int16)
    inversion = np.zeros(n, dtype=np.int32)
    activos = np.zeros(n, dtype=np.int16)
    coste = np.asarray([cat[i]["coste"] for i in datos["ids"]], dtype=np.int32)
    activo = np.asarray([cat[i]["activo"] for i in datos["ids"]], dtype=bool)

    grupo_previo = None
    poseidos = []            # (item, coste, activo, vendido_t)
    for i in range(n):
        clave = (int(datos["match"][i]), int(datos["slot"][i]))
        if clave != grupo_previo:
            grupo_previo = clave
            poseidos = []
        t = float(datos["t"][i])
        # Poda de lo que ya se vendió antes de este instante.
        if poseidos:
            poseidos = [p for p in poseidos
                        if not (p[3] and p[3] <= t)]
        n_items[i] = len(poseidos)
        inversion[i] = sum(p[1] for p in poseidos)
        activos[i] = sum(1 for p in poseidos if p[2])
        item = int(datos["item"][i])
        poseidos.append((item, int(coste[item]), bool(activo[item]),
                         float(datos["vendido_t"][i])))
    datos["n_items"] = n_items
    datos["inversion"] = inversion
    datos["n_activos"] = activos
    return datos


def franja(ts):
    """Franja de tiempo: 0-15 min, 15-30 min, 30+ min."""
    ts = np.asarray(ts)
    return np.where(ts < FRANJAS_S[0], 0,
                    np.where(ts < FRANJAS_S[1], 1, 2)).astype(np.int8)


def shortlist(datos, por_franja=8):
    """Ítems con más compras por franja: el espacio de acciones que sí tiene soporte.

    Restringir el espacio de acciones es el primer remedio publicado al soporte
    deficiente (Sachdeva, Su y Joachims, KDD 2020). Los ítems fuera del shortlist no
    entran en el contraste y se declaran como no evaluables.
    """
    fr = franja(datos["t"])
    fuera = {}
    for e in (0, 1, 2):
        cuenta = np.bincount(datos["item"][fr == e], minlength=len(datos["ids"]))
        orden = np.argsort(cuenta)[::-1]
        fuera[e] = [int(i) for i in orden[:por_franja] if cuenta[i] > 0]
    return fuera


def congelar(datos=None, ruta_db=RUTA_DB):
    """Escribe `datos/corpus.json` con los conteos medidos por el código, no a mano."""
    datos = datos or con_inventario(cargar(ruta=ruta_db), catalogo())
    fr = franja(datos["t"])
    partidas = np.unique(datos["match"])
    # Ganador por partida (una fila por compra: se toma la primera aparición).
    _, primero = np.unique(datos["match"], return_index=True)
    victorias = int(datos["y"][primero].sum())
    corto = shortlist(datos)
    pares = {}
    for e in (0, 1, 2):
        dentro = np.isin(datos["item"][fr == e], corto[e])
        for i in np.unique(datos["item"][fr == e][dentro]):
            pares[f"{e}:{datos['ids'][int(i)]}"] = int(
                np.sum((datos["item"][fr == e] == i) & dentro))
    documento = {
        "generado": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "heroe": HEROE,
        "ruta_db": os.path.basename(ruta_db),
        "sha256_db": sha256(ruta_db),
        "filas": int(len(datos["t"])),
        "partidas": int(len(partidas)),
        "victorias": victorias,
        "wr": round(victorias / max(1, len(partidas)), 4),
        "items": int(len(datos["ids"])),
        "franjas": [int(x) for x in np.bincount(fr, minlength=3)],
        "shortlist": {str(e): [datos["ids"][i] for i in corto[e]] for e in corto},
        "pares_franja_item": len(pares),
        "vendidas": int(np.sum(datos["vendido_t"] > 0)),
        "nw_repetido": float(np.mean(np.diff(datos["nw"]) == 0)) if len(datos["nw"]) > 1 else 0.0,
        "riqueza": datos.get("riqueza"),
        "modelo": "aipw-s-learner-v2",
    }
    os.makedirs(os.path.dirname(RUTA_CORPUS), exist_ok=True)
    with open(RUTA_CORPUS, "w", encoding="utf-8") as f:
        json.dump(documento, f, ensure_ascii=False, indent=1, sort_keys=True)
    return documento


def leer_congelado():
    """El corpus congelado, o None si no existe."""
    try:
        with open(RUTA_CORPUS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def coincide(congelado=None, ruta_db=RUTA_DB):
    """¿El corpus congelado describe la base que hay en disco? Barato: compara hash."""
    congelado = congelado or leer_congelado()
    if not congelado:
        return False
    try:
        return congelado.get("sha256_db") == sha256(ruta_db)
    except OSError:
        return False


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Congela el corpus de compras")
    ap.add_argument("--db", default=RUTA_DB)
    a = ap.parse_args()
    datos = con_inventario(cargar(ruta=a.db), catalogo())
    doc = congelar(datos, ruta_db=a.db)
    print(json.dumps(doc, indent=2, ensure_ascii=False)[:1200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
