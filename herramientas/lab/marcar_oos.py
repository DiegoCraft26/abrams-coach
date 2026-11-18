#!/usr/bin/env python3
"""Marca en el artefacto qué ítems replicaron su signo fuera de muestra.

Por qué: el efecto estimado con todas las partidas puede ser un artefacto de esa
muestra. `replicacion()` entrena con el 60 %, mide el efecto en el 20 % de test que el
modelo no vio y compara el signo. Un ítem que cambia de signo fuera de muestra no debe
poder desempatar una recomendación.

Escribe en `datos/modelo_v2.json`:
    items[<id>]["oos_signo"] = true/false
    ["oos"] = {spearman, acuerdo_signo, acciones, generado}

Uso:
    python3 herramientas/lab/marcar_oos.py
    python3 herramientas/lab/marcar_oos.py --seco
"""
from __future__ import annotations

import argparse
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)

from herramientas.lab import politicas  # noqa: E402

RUTA = os.path.join(RAIZ, "datos", "modelo_v2.json")


def marcar(ruta=RUTA, seco=False, verbose=True, riqueza=True, comparables=False):
    """Escribe la replicación fuera de muestra. Nunca deja el archivo a medias.

    `comparables=True` replica el estimando restringido al mismo tramo de precio que
    el artefacto. Hay que pasarlo para el artefacto generado con `--comparables`; si
    no, la réplica mide la media del shortlist completo y no es el mismo número.
    """
    try:
        with open(ruta, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"artefacto ilegible en {ruta}: {exc}") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("items"), dict):
        raise SystemExit(f"artefacto con forma inesperada en {ruta}")
    # El diseño de la réplica tiene que ser el del artefacto. Si no coincide, se avisa:
    # replicar con el contrafactual del shortlist completo un artefacto de comparables
    # mediría otro número y el Spearman no describiría lo que se publica.
    if bool((doc.get("metodo") or {}).get("comparables")) != bool(comparables):
        print("AVISO: el flag --comparables no coincide con el artefacto; "
              "la réplica usará el diseño que se pidió, no el del JSON.",
              file=sys.stderr)
    # Se replica con el MISMO conjunto de ítems que publica el artefacto: si no, un
    # ítem puede quedar sin marcar solo porque el shortlist de train es otro.
    ids_artefacto = set()
    for franja in ((doc.get("metodo") or {}).get("shortlist") or {}).values():
        ids_artefacto.update(str(i) for i in franja)
    rep = politicas.replicacion(ids_items=ids_artefacto or None, riqueza=riqueza,
                                comparables=comparables)
    if rep.get("error"):
        # Sin réplica no se toca nada: borrar los marcados previos sería peor.
        raise SystemExit(f"replicación sin resultado: {rep['error']}")
    por_item = rep.get("por_item") or {}
    marcados = 0
    for item, datos in (doc.get("items") or {}).items():
        info = por_item.get(item)
        if not info:
            datos["oos_signo"] = None          # no evaluable fuera de muestra
            continue
        datos["oos_signo"] = bool(info["signo"])
        datos["oos_train_pp"] = info["train_pp"]
        datos["oos_test_pp"] = info["test_pp"]
        marcados += 1
    doc["oos"] = {
        "spearman": rep.get("spearman_train_vs_test"),
        "acuerdo_signo": rep.get("acuerdo_de_signo"),
        "acciones": rep.get("acciones_comunes"),
        "comparables": bool(comparables),
    }
    if not seco:
        temporal = ruta + ".tmp"
        with open(temporal, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporal, ruta)
    if verbose:
        print(json.dumps(doc["oos"], indent=1, ensure_ascii=False))
        print(f"ítems marcados: {marcados} de {len(doc.get('items') or {})}")
    return doc


def main():
    ap = argparse.ArgumentParser(description="Marca la replicación fuera de muestra")
    ap.add_argument("--ruta", default=RUTA)
    ap.add_argument("--seco", action="store_true")
    ap.add_argument("--sin-riqueza", action="store_true",
                    help="réplica con el diseño anterior (comparación antes/después)")
    ap.add_argument("--comparables", action="store_true",
                    help="réplica con contrafactual del mismo tramo de precio")
    a = ap.parse_args()
    marcar(a.ruta, a.seco, riqueza=not a.sin_riqueza,
           comparables=a.comparables)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
