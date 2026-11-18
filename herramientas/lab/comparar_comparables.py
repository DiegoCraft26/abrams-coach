#!/usr/bin/env python3
"""Compara dos artefactos del estimador y publica la tabla antes/después.

Pensado para el cambio de contrafactual de 2026-11-18: el «antes» es el shortlist
completo y el «después» el mismo tramo de precio. Lee los dos JSON, calcula el n por
franja desde el corpus (los artefactos viejos no lo traían) y escribe markdown.

Uso:
    python3 herramientas/lab/comparar_comparables.py \
        --antes /tmp/modelo-antes-v3.json --despues /tmp/modelo-v3.json
    ... --salida /tmp/tabla-v3.md
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

NOMBRE_TRAMO = {0: "T0 ≤1200", 1: "T1 1201–2500", 2: "T2 2501–5000",
                3: "T3 >5000"}


def _cargar(ruta):
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def _formato(punto, ic):
    if punto is None or not np.isfinite(punto):
        return "n/a"
    return f"{punto:+.2f} [{ic[0]:+.2f}, {ic[1]:+.2f}]"


def _delta(antes, despues):
    if antes is None or despues is None:
        return "n/a"
    return f"{despues - antes:+.2f}"


def _signo(punto):
    if punto is None or not np.isfinite(punto):
        return "n/a"
    return "−" if punto < 0 else "+"


def _contexto():
    """Carga el corpus una vez y devuelve lo que necesitan la tabla y la composición."""
    cat = corpus.catalogo()
    datos = corpus.con_inventario(corpus.cargar(riqueza=False), cat)
    fr = corpus.franja(datos["t"])
    corto = corpus.shortlist(datos)
    cg = sorted({i for e in corto for i in corto[e]})
    pos = {it: j for j, it in enumerate(cg)}
    acc = np.full(len(datos["item"]), -1, dtype=np.int16)
    dentro = np.isin(datos["item"], cg)
    acc[dentro] = [pos[int(i)] for i in datos["item"][dentro]]
    tramo = estimador.tramos_precio(cat, [datos["ids"][i] for i in cg])
    return {"cat": cat, "datos": datos, "fr": fr, "cg": cg, "acc": acc,
            "tramo": tramo}


def _n_por_franja(ids_artefacto, ctx):
    """Compras de cada id del artefacto por franja, del corpus actual."""
    datos, fr = ctx["datos"], ctx["fr"]
    pos = {str(x): i for i, x in enumerate(datos["ids"])}
    n = {i: {0: 0, 1: 0, 2: 0} for i in ids_artefacto}
    for item in ids_artefacto:
        j = pos.get(str(item))
        if j is None:
            continue
        sel = datos["item"] == j
        for e in (0, 1, 2):
            n[item][e] = int(np.sum(sel & (fr == e)))
    return n


def _imprimir_composicion(ctx, salida=sys.stdout):
    """Compras del shortlist por tramo y franja, y equivalencia con la regla 1.25×."""
    datos, fr, cg, acc, tramo = (ctx[k] for k in ("datos", "fr", "cg", "acc", "tramo"))
    print("## Composición del shortlist por tramo", file=salida)
    print(file=salida)
    print("| Tramo | f0 | f1 | f2 | total | % f0 |", file=salida)
    print("|---|---:|---:|---:|---:|---:|", file=salida)
    total_f0 = 0
    filas = []
    for t in range(len(estimador.CORTES_PRECIO) + 1):
        cnt = [int(np.sum((fr == e) & (acc >= 0) & (tramo[acc.clip(0)] == t)))
               for e in range(3)]
        total_f0 += cnt[0]
        filas.append((t, cnt))
    for t, cnt in filas:
        print(f"| T{t} | {cnt[0]} | {cnt[1]} | {cnt[2]} | {sum(cnt)} | "
              f"{100.0 * cnt[0] / max(1, total_f0):.1f} % |", file=salida)
    print(file=salida)
    print(f"Franja 0 del shortlist: **{total_f0}** compras; "
          f"T0+T1 = **{100.0 * (filas[0][1][0] + filas[1][1][0]) / max(1, total_f0):.1f} %**.",
          file=salida)
    costes = np.asarray([ctx["cat"][datos["ids"][i]]["coste"] for i in cg],
                        dtype=float)
    malos = 0
    pares = 0
    for i in range(len(cg)):
        for j in range(len(cg)):
            if i == j:
                continue
            pares += 1
            razon = max(costes[i], costes[j]) / max(1.0, min(costes[i], costes[j]))
            if (tramo[i] == tramo[j]) != (razon <= 1.25 + 1e-12):
                malos += 1
    print(f"Equivalencia banda vs razón de coste ≤1.25×: **{pares - malos}/{pares}** "
          f"pares de acuerdo ({malos} desacuerdos).", file=salida)
    print(file=salida)


def comparar(antes, despues, n_ea, salida=sys.stdout):
    ia = antes.get("items") or {}
    ib = despues.get("items") or {}
    ids = sorted(set(ia) | set(ib), key=lambda k: (
        int((ib.get(k) or ia.get(k)).get("coste") or 0),
        (ib.get(k) or ia.get(k)).get("nombre") or k))

    def w(linea=""):
        print(linea, file=salida)

    w("# Tabla antes/después · contrafactual del mismo tramo de precio")
    w()
    w(f"Antes: `{antes.get('generado')}` · después: `{despues.get('generado')}`")
    metodo = despues.get("metodo") or {}
    w(f"Corpus: {despues.get('corpus', {}).get('partidas')} partidas · "
      f"{despues.get('corpus', {}).get('filas')} compras · "
      f"sha256 `{despues.get('corpus', {}).get('sha256_db', '?')[:12]}…`")
    w(f"Comparables: {metodo.get('comparables')} · "
      f"cortes {metodo.get('cortes_precio')}")
    w()
    w("## Tabla compacta (agregado y franja 0)")
    w()
    w("| Ítem | Coste | Tramo | n | τ agg antes (IC90) | τ agg después (IC90) | Δ agg | "
      "τ f0 antes (IC90) | τ f0 después (IC90) | Δ f0 | Signo agg | Signo f0 |")
    w("|---|---:|---|---:|---|---|---:|---|---|---:|---|---|")
    cambios_agg = []
    cambios_f0 = []
    for k in ids:
        a = ia.get(k) or {}
        b = ib.get(k) or {}
        if not a or not b:
            continue
        n = int(b.get("n") or a.get("n") or 0)
        tramo = b.get("tramo_precio", a.get("tramo_precio"))
        pa = a.get("efecto_pp")
        pb = b.get("efecto_pp")
        f0a = (a.get("por_franja") or {}).get("0")
        f0b = (b.get("por_franja") or {}).get("0")
        if pa is not None and pb is not None and (pa > 0) != (pb > 0):
            cambios_agg.append(b.get("nombre") or k)
        if f0a is not None and f0b is not None and (f0a > 0) != (f0b > 0):
            cambios_f0.append(b.get("nombre") or k)
        w(f"| {b.get('nombre') or k} | {b.get('coste') or a.get('coste')} | "
          f"{NOMBRE_TRAMO.get(tramo, tramo)} | {n} | "
          f"{_formato(pa, a.get('ic90') or [float('nan')] * 2)} | "
          f"{_formato(pb, b.get('ic90') or [float('nan')] * 2)} | "
          f"{_delta(pa, pb)} | "
          f"{_formato(f0a, (a.get('por_franja_ic90') or {}).get('0', [float('nan')] * 2))} | "
          f"{_formato(f0b, (b.get('por_franja_ic90') or {}).get('0', [float('nan')] * 2))} | "
          f"{_delta(f0a, f0b)} | {_signo(pa)}→{_signo(pb)} | "
          f"{_signo(f0a)}→{_signo(f0b)} |")
    w()
    w("## Tabla completa por franja")
    w()
    w("| Ítem | Franja | n | τ antes (IC90) | τ después (IC90) | Δ | Signo |")
    w("|---|---|---:|---|---|---:|---|")
    for k in ids:
        a = ia.get(k) or {}
        b = ib.get(k) or {}
        if not a or not b:
            continue
        nombre = b.get("nombre") or k
        for e in ("0", "1", "2"):
            pa = (a.get("por_franja") or {}).get(e)
            pb = (b.get("por_franja") or {}).get(e)
            if pa is None and pb is None:
                continue
            n = int((n_ea.get(k) or {}).get(int(e), 0))
            w(f"| {nombre} | {e} | {n} | "
              f"{_formato(pa, (a.get('por_franja_ic90') or {}).get(e, [float('nan')] * 2))} | "
              f"{_formato(pb, (b.get('por_franja_ic90') or {}).get(e, [float('nan')] * 2))} | "
              f"{_delta(pa, pb)} | {_signo(pa)}→{_signo(pb)} |")
    w()
    w("## Resumen")
    w()
    comunes = [k for k in ids if k in ia and k in ib]
    difs_agg = [abs(ib[k]["efecto_pp"] - ia[k]["efecto_pp"]) for k in comunes]
    pares_f0 = [(ia[k]["por_franja"].get("0"), ib[k]["por_franja"].get("0"))
                for k in comunes
                if ia[k]["por_franja"].get("0") is not None
                and ib[k]["por_franja"].get("0") is not None]
    difs_f0 = [abs(y - x) for x, y in pares_f0]
    w(f"- Ítems comparados: **{len(comunes)}**.")
    w(f"- Media |Δ| agregado: **{np.mean(difs_agg):.2f} pp** · "
      f"mediana {np.median(difs_agg):.2f} pp · máximo {np.max(difs_agg):.2f} pp.")
    w(f"- Media |Δ| franja 0: **{np.mean(difs_f0):.2f} pp** · "
      f"mediana {np.median(difs_f0):.2f} pp · máximo {np.max(difs_f0):.2f} pp.")
    w(f"- Cambian de signo en el agregado: **{len(cambios_agg)}** "
      f"({', '.join(cambios_agg) if cambios_agg else 'ninguno'}).")
    w(f"- Cambian de signo en franja 0: **{len(cambios_f0)}** "
      f"({', '.join(cambios_f0) if cambios_f0 else 'ninguno'}).")

    def _excluye_cero(ic):
        return bool(ic and ic[0] * ic[1] > 0)

    agg_a = sum(_excluye_cero(ia[k].get("ic90")) for k in comunes)
    agg_b = sum(_excluye_cero(ib[k].get("ic90")) for k in comunes)
    f0_a = sum(_excluye_cero((ia[k].get("por_franja_ic90") or {}).get("0"))
               for k in comunes if ia[k]["por_franja"].get("0") is not None)
    f0_b = sum(_excluye_cero((ib[k].get("por_franja_ic90") or {}).get("0"))
               for k in comunes if ib[k]["por_franja"].get("0") is not None)
    w(f"- IC90 que excluye 0, agregado: antes **{agg_a}/{len(comunes)}**, "
      f"después **{agg_b}/{len(comunes)}**. Franja 0: antes **{f0_a}/{len(pares_f0)}**, "
      f"después **{f0_b}/{len(pares_f0)}**.")
    caros = [k for k in comunes if (ib[k].get("coste") or 0) > 5000
             and ib[k]["por_franja"].get("0") is not None]
    dentro = [k for k in caros if abs(ib[k]["por_franja"]["0"]) < 3.0]
    fuera = [k for k in caros if abs(ib[k]["por_franja"]["0"]) >= 3.0]
    fuera_txt = ", ".join(
        f"{ib[k]['nombre']} ({ib[k]['por_franja']['0']:+.2f}, "
        f"n={n_ea.get(k, {}).get(0, 0)})" for k in fuera) or "ninguno"
    w(f"- Caros (>5000) con franja 0: {len(caros)}. Con |τ| < 3 pp después: "
      f"**{len(dentro)}/{len(caros)}**; fuera: {fuera_txt}.")
    baratos = [k for k in comunes if (ib[k].get("coste") or 0) <= 1200]
    conservan = [k for k in baratos
                 if ia[k]["efecto_pp"] * ib[k]["efecto_pp"] > 0]
    w(f"- Ítems de 800: {len(baratos)}; conservan el signo del agregado "
      f"**{len(conservan)}/{len(baratos)}** "
      f"({', '.join(ib[k]['nombre'] for k in conservan) if conservan else 'ninguno'}).")
    return {"comunes": len(comunes), "cambios_agg": cambios_agg,
            "cambios_f0": cambios_f0, "caros_f0_fuera": fuera}


def main():
    ap = argparse.ArgumentParser(description="Tabla antes/después de dos artefactos")
    ap.add_argument("--antes", default=None)
    ap.add_argument("--despues", default=None)
    ap.add_argument("--salida", default=None)
    ap.add_argument("--composicion", action="store_true",
                    help="imprime la composición por tramo sin comparar artefactos")
    a = ap.parse_args()
    if not a.composicion and not (a.antes and a.despues):
        ap.error("hacen falta --antes y --despues (o --composicion)")
    ctx = _contexto()
    if a.composicion:
        _imprimir_composicion(ctx)
        if not (a.antes and a.despues):
            return 0
    antes = _cargar(a.antes)
    despues = _cargar(a.despues)
    ids = set((antes.get("items") or {})) | set((despues.get("items") or {}))
    n_ea = _n_por_franja(ids, ctx)
    if a.salida:
        with open(a.salida, "w", encoding="utf-8") as f:
            comparar(antes, despues, n_ea, salida=f)
        print(f"escrito {a.salida}")
    else:
        comparar(antes, despues, n_ea)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
