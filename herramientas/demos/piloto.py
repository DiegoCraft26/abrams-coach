#!/usr/bin/env python3
"""Piloto: compras reales del demo contra lo que dice `data/replay_cache.json`.

Para cada partida del corpus:

  1. pide la consulta `todo` (compras + moneda + mapeo de slots) y la cachea;
  2. resuelve el slot: `AbilitiesChangedEvent.purchaser_player_slot` es el índice
     0-based de `CCitadelPlayerController.entity_index` (= entity_index − 1), y el
     slot del lobby sale de `m_unLobbyPlayerSlot` (u64 little-endian en binario);
  3. saca las compras (`change = 0`) y las ventas (`change = 2`) del jugador;
  4. empareja con el corpus por id y mide recall, sobran/faltan y desfase de tiempo.

El desfase entre el tick 0 del demo y el reloj de la partida no se asume: se acota
con los pares emparejados (el corpus guarda segundos enteros, así que cada par da
un intervalo) y se cruza el intervalo de todas las partidas.

Uso:
    python3 herramientas/demos/piloto.py                  # 5 partidas
    python3 herramientas/demos/piloto.py --n 5 --paralelo 2
    python3 herramientas/demos/piloto.py --matches 132662221,132597784 --json salida.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import consulta  # noqa: E402

RAIZ = consulta.RAIZ
CORPUS = RAIZ / "data" / "replay_cache.json"
ITEMS = RAIZ / "data" / "items.json"
TPS = consulta.TPS
CUENTA_STEAM = 76561197960265728


def leer_rows(ruta: Path) -> list[dict]:
    with open(ruta, encoding="utf-8") as f:
        return [json.loads(linea) for linea in f if linea.strip()]


def decodificar_slot(texto: str | None) -> int | None:
    """`m_unLobbyPlayerSlot` llega como 8 bytes little-endian, en dos formas.

    - columna binaria cruda: el JSON trae 16 caracteres hex, `"0300000000000000"`;
    - casteada a VARCHAR: trae los 8 bytes de verdad, `"\x03\x00..."`.
    """
    if not texto:
        return None
    limpio = texto.strip()
    if len(limpio) == 16 and all(c in "0123456789abcdefABCDEF" for c in limpio):
        return int.from_bytes(bytes.fromhex(limpio), "little")
    crudo = texto.encode("utf-8", "surrogateescape")[:8]
    if len(crudo) < 8:
        return None
    return int.from_bytes(crudo, "little")


def partir(rows: list[dict]) -> tuple[dict, dict, list[dict], list[tuple[int, int]]]:
    """Separa el NDJSON de la consulta `todo` en mapa, moneda, compras y pausas."""
    mapa, moneda, compras = {}, defaultdict(list), []
    pausas: list[tuple[int, int]] = []
    for r in rows:
        tag = r.get("tag")
        if tag == "pausa":
            pausas.append((int(r["t"]), int(r["a"] or 0)))
            continue
        if tag == "ctrl":
            entidad = int(r["a"])
            slot = decodificar_slot(r.get("c"))
            mapa[entidad] = {
                "slot_lobby": slot,
                "slot_evento": entidad - 1,
                "steam_id": int(r["b"]) if r.get("b") else 0,
                "cuenta": int(r["b"]) - CUENTA_STEAM if r.get("b") else 0,
                "nombre": r.get("d") or "",
            }
        elif tag == "cur":
            moneda[(int(r["a"]), int(r["b"]))].append(
                (int(r["t"]), int(r["c"] or 0), int(r["d"] or 0))
            )
        elif tag == "ab":
            compras.append({
                "tick": int(r["t"]),
                "slot": int(r["a"]),
                "item": int(r["b"]),
                "cambio": int(r["c"] or 0),
            })
    for fila in moneda.values():
        fila.sort()
    pausas.sort()
    return mapa, moneda, compras, pausas


def oro_en(moneda: dict, slot: int, tick: int, tipo: int = 0) -> int | None:
    """Oro absoluto (tipo 0) del jugador en ese tick: el último `new_value` <= tick."""
    mejor = None
    for t, delta, nuevo in moneda.get((slot, tipo), []):
        if t > tick:
            break
        mejor = nuevo
    return mejor


def emparejar(corpus: list[dict], demo: list[dict]) -> list[tuple[dict, dict, float]]:
    """Empareja por id en orden cronológico.

    No se puede usar una ventana de ±N s contra el tiempo del corpus, porque entre
    el tick 0 del demo y el reloj de la partida hay un desfase de ~33 s que es
    justamente lo que se quiere medir. Por eso se agrupa por id y se empareja el
    i-ésimo del corpus con el i-ésimo del demo; el desfase sale después, de los
    propios pares.
    """
    por_id: dict[int, list[dict]] = defaultdict(list)
    for d in demo:
        por_id[d["item"]].append(d)
    pares = []
    for c in corpus:
        cola = por_id.get(int(c["id"]))
        if cola:
            pares.append((c, cola.pop(0), 0.0))
    return pares


def medir_desfase(pares: list[tuple[dict, dict, float]]) -> dict | None:
    """Desfase demo<->reloj de partida a partir de los pares.

    El corpus guarda segundos enteros, así que cada par da `x = demo - corpus` con
    ±1 s de granularidad. Se toma la mediana como desfase y se marca como dudoso lo
    que se aleje más de 1,5 s (emparejamiento equivocado, no desfase).
    """
    if not pares:
        return None
    x = sorted(d["segundos"] - float(c["t"]) for c, d, _ in pares)
    centro = statistics.median(x)
    dudosos = [(c["id"], round(v, 1)) for (c, _, _), v in zip(pares, x)
               if abs(v - centro) > 1.5]
    return {
        "centro": round(centro, 2),
        "spread": round(x[-1] - x[0], 2),
        "dentro": f"{len(x) - len(dudosos)}/{len(x)}",
        "dudosos": dudosos[:6],
    }


def analizar(match: int, slot_corpus: int, items_por_id: dict, cache: Path,
             opciones: dict, caliente: dict | None = None) -> dict:
    resumen = consulta.una(match, "todo", consulta.CONSULTAS["todo"](None), cache, **opciones)
    if not resumen.get("segundos"):
        resumen["segundos"] = (caliente or {}).get("segundos", 0.0)
    filas = leer_rows(Path(resumen["ruta"]))
    mapa, moneda, compras, pausas = partir(filas)

    # slot del evento -> slot del lobby, vía entity_index
    evento_a_lobby = {m["slot_evento"]: m["slot_lobby"] for m in mapa.values()}
    entidad = next((e for e, m in mapa.items() if m["slot_lobby"] == slot_corpus), None)
    slot_evento = entidad - 1 if entidad is not None else None
    if slot_evento is None:
        raise SystemExit(f"{match}: nadie tiene el slot de lobby {slot_corpus}")

    del_slot = sorted([c for c in compras if c["slot"] == slot_evento],
                      key=lambda c: c["tick"])
    for c in del_slot:
        # crudo (tick/64) y corregido por pausas; el preámbulo se ajusta después
        c["segundos"] = consulta.segundos_juego(c["tick"], pausas)
        c["segundos_crudos"] = c["tick"] / TPS
    compras_demo = [c for c in del_slot if c["cambio"] == 0]
    ventas_demo = [c for c in del_slot if c["cambio"] == 2]

    ids_visibles = {c["item"] for c in compras}
    corpus = json.loads(json.dumps(items_por_id["corpus"][str(match)]))
    visibles = [e for e in corpus if int(e["id"]) in ids_visibles]
    pares = emparejar(visibles, compras_demo)
    usados = {id(d) for _, d, _ in pares}
    sobran = [c for c in compras_demo if id(c) not in usados]

    # ventas: el corpus dice en qué segundo se vendió cada compra
    vendidos_corpus = [e for e in corpus if int(e["vendido"]) > 0]
    pares_venta = emparejar(
        [{"t": e["vendido"], "id": e["id"]} for e in vendidos_corpus], ventas_demo
    )

    # desfase: se mide con las compras y se comprueba aparte con las ventas
    desfase = medir_desfase(pares)
    desfase_ventas = medir_desfase(pares_venta)
    deltas = [d["segundos"] - float(c["t"]) for c, d, _ in pares]

    return {
        "match": match,
        "slot_corpus": slot_corpus,
        "slot_evento": slot_evento,
        "slot_lobby_demo": evento_a_lobby.get(slot_evento),
        "steam_id": mapa[entidad]["steam_id"] if entidad else 0,
        "cuenta": mapa[entidad]["cuenta"] if entidad else 0,
        "corpus_total": len(corpus),
        "corpus_visibles": len(visibles),
        "demo_compras": len(compras_demo),
        "demo_ventas": len(ventas_demo),
        "acertadas": len(pares),
        "ventas_acertadas": len(pares_venta),
        "sobran": [{"item": c["item"], "seg": round(c["segundos"], 1)} for c in sobran],
        "faltan": [{"item": int(e["id"]), "t": e["t"]} for e in visibles
                   if int(e["id"]) not in {int(c["id"]) for c, _, _ in pares}],
        "delta_medio": round(statistics.mean(deltas), 2) if deltas else None,
        "faltan": [],
        "desfase": desfase,
        "desfase_ventas": desfase_ventas,
        "segundos_job": resumen.get("segundos", 0.0),
        "filas": resumen.get("filas", 0),
        "oro": _resumen_oro(moneda, slot_evento, compras_demo, items_por_id["items"]),
    }


def _resumen_oro(moneda: dict, slot: int, compras: list[dict], items: dict) -> dict | None:
    """¿Se puede leer el oro en el momento de cada compra?"""
    if not moneda.get((slot, 0)):
        return None
    muestras = []
    for c in compras[:6]:
        antes = oro_en(moneda, slot, c["tick"])
        despues = oro_en(moneda, slot, c["tick"] + 1)
        if antes is None:
            continue
        nombre = (items.get(str(c["item"])) or {}).get("name", "?")
        muestras.append({"item": nombre, "seg": round(c["segundos"], 1),
                         "oro_antes": antes, "oro_despues": despues,
                         "gastado": (antes - despues) if despues is not None else None})
    return {"filas": len(moneda[(slot, 0)]), "muestras": muestras}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Piloto demo vs replay_cache")
    p.add_argument("--n", type=int, default=5, help="cuántas partidas (defecto: 5)")
    p.add_argument("--matches", default="", help="ids concretos separados por coma")
    p.add_argument("--paralelo", type=int, default=2)
    p.add_argument("--forzar", action="store_true")
    p.add_argument("--json", default="", help="guardar el resultado en JSON")
    args = p.parse_args(argv)

    cache = consulta.CACHE_POR_DEFECTO
    corpus_crudo = json.loads(CORPUS.read_text(encoding="utf-8"))
    por_match = {int(m["match_id"]): m for m in corpus_crudo}
    items = json.loads(ITEMS.read_text(encoding="utf-8"))

    if args.matches:
        objetivos = [int(x) for x in args.matches.replace(" ", "").split(",") if x]
    else:
        objetivos = [int(m["match_id"]) for m in corpus_crudo[:args.n]]

    opciones = {"forzar": args.forzar, "reintentos": 2, "tope_s": 300.0,
                "guardar_zst": False, "paralelo": args.paralelo}

    # precalienta la caché en paralelo: una sola consulta por partida
    caliente = {r["match"]: r for r in
                consulta.varias(objetivos, "todo", consulta.CONSULTAS["todo"](None),
                                cache, **opciones)}

    resultados = []
    for match in objetivos:
        entrada = por_match.get(match)
        if not entrada:
            print(f"{match}: no está en el corpus", file=sys.stderr)
            continue
        datos = {"corpus": {str(match): entrada["yo"]["items"]}, "items": items}
        try:
            extra = {k: v for k, v in opciones.items() if k != "paralelo"}
            resultados.append(analizar(match, int(entrada["yo"]["slot"]), datos,
                                       cache, extra, caliente.get(match, {})))
        except (consulta.ErrorFatal, consulta.ErrorDemo) as e:
            print(f"{match}: {e}", file=sys.stderr)
            resultados.append({"match": match, "error": str(e)})

    if args.json:
        Path(args.json).write_text(json.dumps(resultados, indent=1, ensure_ascii=False),
                                   encoding="utf-8")

    ok = [r for r in resultados if "error" not in r]
    print()
    print("| partida | slot corpus | slot demo | cuenta | visibles | demo | "
          "acertadas | recall | desfase | ventas |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for r in ok:
        desf = r["desfase"] or {}
        ven = r["desfase_ventas"] or {}
        print(f"| {r['match']} | {r['slot_corpus']} | {r['slot_evento']} | "
              f"{r['cuenta']} | {r['corpus_visibles']} | "
              f"{r['demo_compras']} | {r['acertadas']} | "
              f"{100 * r['acertadas'] / max(1, r['corpus_visibles']):.0f}% | "
              f"{desf.get('centro')}s | {ven.get('centro')}s |")

    total_corpus = sum(r["corpus_visibles"] for r in ok)
    total_ok = sum(r["acertadas"] for r in ok)
    total_todo = sum(r["corpus_total"] for r in ok)
    centros = [r["desfase"]["centro"] for r in ok if r.get("desfase")]
    if centros:
        print(f"\ndesfase por partida: {centros} s -> "
              f"{'NO es constante' if max(centros) - min(centros) > 2 else 'constante'}")
    print(f"recall sobre ítems visibles en el demo: {total_ok}/{total_corpus} "
          f"({100 * total_ok / max(1, total_corpus):.1f}%)")
    print(f"recall sobre el corpus completo: {total_ok}/{total_todo} "
          f"({100 * total_ok / max(1, total_todo):.1f}%)")
    print(f"tiempo de servidor: {sum(r['segundos_job'] for r in ok):.0f}s en {len(ok)} partidas")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
