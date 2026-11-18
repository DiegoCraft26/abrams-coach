"""La apertura del héroe: del banco cuando lo hay, del pozo del API cuando es otro.

El coach nació para Abrams y tenía la apertura **escrita a mano** en `nucleo_vivo`
(`APERTURA = ["1437614329", "1342610602", "2829638276"]`, Melee Lifesteal, Close Quarters,
Extra Regen). El banco de 626 partidas dice otra cosa: la apertura real de Abrams es
Spirit Strike, Close Quarters, Extra Regen (ver `data/meta_abrams.json`). Las dos listas
convivían y el panel enseñaba la escrita a mano.

Aquí hay una sola fuente de verdad por héroe, en este orden:

1. `data/meta_abrams.json` para Abrams (626 partidas jugadas, lo más fiable);
2. `data/meta/<id>.json` para cualquier otro héroe (pozo temprano del API, validado como
   conjunto contra el banco de Abrams el 2026-11-15);
3. la lista escrita a mano, solo si no hay nada en disco.

Nunca inventa: si no hay dato, devuelve la lista de reserva y quien lo use puede decir de
dónde viene con `fuente()`.
"""
from __future__ import annotations

import json
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META_ABRAMS = os.path.join(RAIZ, "data", "meta_abrams.json")
META_HEROE = os.path.join(RAIZ, "data", "meta")
HEROE_ABRAMS = 6

#: Reserva: lo que el panel enseñaba antes de mirar el banco. Solo se usa si no hay meta.
RESERVA = ("1437614329", "1342610602", "2829638276")

_cache = {"ts": 0.0, "datos": {}}


def _leer(ruta):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _ids_de_abrams():
    crudo = _leer(META_ABRAMS)
    if not isinstance(crudo, dict):
        return None
    lista = crudo.get("apertura")
    if isinstance(lista, list) and lista:
        return [str(x) for x in lista]
    detalle = crudo.get("apertura_detalle")
    if isinstance(detalle, list) and detalle:
        return [str(x.get("id")) for x in detalle if x.get("id")]
    return None


def _ids_de_heroe(hero_id):
    crudo = _leer(os.path.join(META_HEROE, f"{int(hero_id)}.json"))
    if not isinstance(crudo, dict):
        return None
    pozo = crudo.get("apertura")
    if isinstance(pozo, list) and pozo:
        return [str(x.get("id")) for x in pozo if isinstance(x, dict) and x.get("id")]
    return None


def resolver(heroe=None, cuantos=5):
    """(ids, fuente). `heroe` puede ser nombre, id o None (Abrams por defecto)."""
    from . import historico

    hero_id = HEROE_ABRAMS
    if heroe not in (None, ""):
        if isinstance(heroe, int) or str(heroe).isdigit():
            hero_id = int(heroe)
        else:
            hero_id = historico.nombre_a_id().get(str(heroe).strip().lower(),
                                                  HEROE_ABRAMS)

    if hero_id == HEROE_ABRAMS:
        lista = _ids_de_abrams()
        if lista:
            return lista[:cuantos], "banco (626 partidas)"
    lista = _ids_de_heroe(hero_id)
    if lista:
        return lista[:cuantos], f"pozo del API (héroe {hero_id})"
    if hero_id != HEROE_ABRAMS:
        # Otro héroe sin pozo: se cae a Abrams solo para no dejar el panel vacío, y se
        # dice en la fuente para que nadie lo confunda con un dato de ese héroe.
        lista = _ids_de_abrams()
        if lista:
            return lista[:cuantos], "reserva de Abrams (sin pozo de este héroe)"
    return list(RESERVA)[:cuantos], "reserva escrita a mano"


def ids(heroe=None, cuantos=5):
    return resolver(heroe, cuantos)[0]


def fuente(heroe=None):
    return resolver(heroe)[1]
