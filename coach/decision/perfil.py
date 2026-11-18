"""Perfil del camino de build: el inicio es el mismo, el resto depende de la partida.

El problema que resuelve: `camino.construir()` armaba una sola secuencia por héroe y la
guardaba en caché, así que la recomendación era la misma en las 50 partidas. La apertura
(las tres piezas de 800) sí puede ser fija; lo que viene después no, porque depende de
tres cosas que el motor ya conoce:

  1. **Quién va por encima** (`amenazas`). Si un rival está 40k cuando tu equipo va con
     25-30k, el camino se desvía a lo que frena su kit antes que a otra pieza del build.
  2. **Cómo vas en almas** (`econ.delta_pct`). Yendo atrás se acorta (nada de spikes de
     6,400 que no llegas a pagar); yendo arriba se permite adelantar el spike.
  3. **Lo que ya llevas** (`balance`). Se prefiere el slot más flojo para no terminar con
     cuatro de arma y el vitality vacío, que es el build plano de siempre.

No es aleatorio: dos llamadas con el mismo reloj (bloque de 10 s), inventario y almas dan
el mismo perfil, que es la invariante que ya respeta el resto del motor.
"""
from __future__ import annotations

from . import situacionales

# Tope de precio por fase: lo que no se puede pagar a tiempo no se persigue.
TOPE_FASE = ((600, 3200), (1500, 4800), (None, 6400))
UMBRAL_ATRAS = -0.10
UMBRAL_ARRIBA = 0.10


def tope_de_fase(t_s):
    for limite, tope in TOPE_FASE:
        if limite is None or t_s < limite:
            return tope
    return TOPE_FASE[-1][1]


def _contra_de(heroe, tope, poseidos):
    """Ítems situacionales que frenan el kit de ese rival, dentro del presupuesto."""
    if not heroe:
        return ()
    tags = set(situacionales.tags_de_heroe(heroe))
    if not tags:
        return ()
    salida = [str(iid) for iid, datos in situacionales.SITUACIONALES.items()
              if situacionales.SEÑAL_DE_TAG.get(datos["tag"]) in tags
              and datos["costo"] <= tope
              and str(iid) not in poseidos]
    # Los baratos primero: el counter llega antes y deja al resto del camino intacto.
    salida.sort(key=lambda iid: situacionales.SITUACIONALES[iid]["costo"])
    return tuple(salida[:3])


def calcular(estado, econ=None, amenazas=None, t_ef=None, poseidos=()):
    """Perfil vigente: `modo`, `motivo`, `tope` de precio y counters del rival que va arriba."""
    t = float(t_ef if t_ef is not None else (getattr(estado, "t", 0.0) or 0.0))
    tope = tope_de_fase(t)
    delta = (econ or {}).get("delta_pct")
    poseidos = {str(x) for x in (poseidos or ())}
    # Acepta la ficha completa de `amenazas.evaluar()` o solo su lista.
    lista = amenazas.get("lista") if isinstance(amenazas, dict) else (amenazas or ())
    peor = next((a for a in lista if a.get("nivel") == "critico"), None)

    if peor is not None:
        contra = _contra_de(peor.get("heroe"), tope, poseidos)
        pct = int(round((peor.get("delta_pct") or 0.0) * 100))
        motivo = (f"{peor.get('heroe')} va {pct:+d}% en almas sobre tu equipo: "
                  f"el siguiente hueco del camino va a lo que lo frena")
        if not contra:
            motivo = (f"{peor.get('heroe')} va {pct:+d}% sobre tu equipo, pero no hay "
                      f"counter suyo que pague esta fase: build corto y a farmear")
        return {"clave": f"contra|{peor.get('heroe')}", "modo": "contra",
                "etiqueta": f"counter de {peor.get('heroe')}",
                "motivo": motivo, "tope": tope, "contra": contra,
                "rival": peor.get("heroe")}

    if delta is not None and delta <= UMBRAL_ATRAS:
        pct = int(round(delta * 100))
        # A partir del minuto 20 yendo atrás esto es una remontada, no un build corto:
        # piezas baratas de impacto inmediato y nada de perseguir un 6,400.
        remontada = t >= 1200
        return {"clave": "atras", "modo": "atras",
                "etiqueta": "remontada" if remontada else "build corto",
                "motivo": (f"vas {abs(pct)}% atrás en almas: piezas baratas de impacto "
                           f"inmediato, sin spikes caros"
                           if remontada else
                           f"vas {abs(pct)}% atrás en almas: camino corto, sin spikes "
                           f"caros hasta el cierre"),
                "tope": min(tope, 3200), "contra": (), "rival": None}

    if delta is not None and delta >= UMBRAL_ARRIBA:
        pct = int(round(delta * 100))
        return {"clave": "arriba", "modo": "arriba", "etiqueta": "build agresivo",
                "motivo": (f"vas {pct}% arriba en almas: el spike se adelanta, "
                           f"tienes con qué pagarlo"),
                "tope": min(6400, tope * 2), "contra": (), "rival": None}

    return {"clave": "base", "modo": "base", "etiqueta": "build base",
            "motivo": "sin desviación: la partida va pareja", "tope": tope,
            "contra": (), "rival": None}
