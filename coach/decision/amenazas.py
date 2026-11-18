"""Amenazas: quién del otro equipo está por encima y a quién no buscas solo.

No mide "quién mata más", mide **quién puede matarte solo ahora**: almas relativas a tu
equipo. Un enemigo con 40k cuando tu equipo va con 25-30k no es uno más de la lista; si
lo encuentras en una línea pierdes la pelea, el objetivo y el tempo.

De dónde salen los números: de las almas que ya trae el estado (broadcast o marcador).
Sin aliados con almas no hay con qué comparar y se dice (`nivel: None`); no se inventa
una amenaza a partir de la media enemiga, que es lo que haría parecer "normal" a un rival
que en realidad está dos ítems por delante.

Los umbrales son de criterio, no de datos: 35% o 8k por encima es "crítico", 15% o 4k es
"alto". Están en `UMBRALES` para poder moverlos sin tocar la lógica.
"""
from __future__ import annotations

UMBRALES = {
    "critico_pct": 0.35,
    "critico_delta": 8000,
    "alto_pct": 0.15,
    "alto_delta": 4000,
    "flojo_pct": -0.20,
    # "alto" solo obliga a evitar cuando además mata: 25% arriba o dos bajas netas.
    "alto_evitar_pct": 0.25,
    "alto_evitar_netas": 2,
}

NIVELES = ("critico", "alto", "parejo", "flojo")


def _media_equipo(estado):
    """Media de almas de tu equipo: tú y los aliados que traigan almas."""
    valores = []
    mio = getattr(getattr(estado, "yo", None), "almas", None)
    if mio:
        valores.append(mio)
    for a in getattr(estado, "aliados", ()) or ():
        if a.almas:
            valores.append(a.almas)
    return sum(valores) / len(valores) if valores else None


def _nivel(pct, delta):
    if pct is None:
        return None
    if pct >= UMBRALES["critico_pct"] or delta >= UMBRALES["critico_delta"]:
        return "critico"
    if pct >= UMBRALES["alto_pct"] or delta >= UMBRALES["alto_delta"]:
        return "alto"
    if pct <= UMBRALES["flojo_pct"]:
        return "flojo"
    return "parejo"


def _motivo(heroe, almas, delta, pct, nivel):
    nombre = str(heroe or "rival")
    if pct is None:
        return f"{nombre}: sin almas para comparar"
    if nivel == "flojo":
        return f"{nombre}: {pct:+.0%} bajo tu equipo, es pelea ganable"
    if delta is None or delta <= 0:
        return f"{nombre}: {pct:+.0%} sobre tu equipo"
    return f"{nombre}: {delta:,} almas más que la media de tu equipo ({pct:+.0%})"


def evaluar(estado):
    """Ficha de amenaza por enemigo, con el peor primero.

    Devuelve un dict para el motor y para el panel:

        {"media_equipo": 27400, "referencia": "media de tu equipo",
         "lista": [ {heroe, almas, delta, delta_pct, nivel, evitar_solo, motivo}, ... ],
         "peor": {...} | None, "alerta": "no busques a Haze solo..." | None,
         "cuenta": {"critico": 1, "alto": 0}}
    """
    media = _media_equipo(estado)
    lista = []
    for j in (getattr(estado, "enemigos", ()) or ()):
        if not j.heroe and j.almas is None:
            continue
        almas = j.almas
        if media and almas is not None:
            delta = almas - media
            pct = delta / media
        else:
            delta = pct = None
        nivel = _nivel(pct, delta)
        netas = (j.bajas or 0) - (j.muertes or 0)
        evitar = (nivel == "critico"
                  or (nivel == "alto"
                      and (pct >= UMBRALES["alto_evitar_pct"]
                           or netas >= UMBRALES["alto_evitar_netas"])))
        lista.append({
            "heroe": j.heroe,
            "almas": almas,
            "bajas": j.bajas,
            "muertes": j.muertes,
            "asistencias": j.asistencias,
            "delta": delta,
            "delta_pct": pct,
            "nivel": nivel,
            "evitar_solo": bool(evitar),
            "motivo": _motivo(j.heroe, almas, delta, pct, nivel),
        })

    orden = {None: 4, "critico": 0, "alto": 1, "parejo": 2, "flojo": 3}
    lista.sort(key=lambda x: (orden.get(x["nivel"], 4), -(x["delta"] or 0)))
    peor = next((x for x in lista if x["evitar_solo"]), None)
    if peor is None and lista and lista[0]["nivel"] in ("critico", "alto"):
        peor = lista[0]

    alerta = None
    if peor is not None and peor.get("evitar_solo"):
        alerta = (f"no busques a {peor['heroe']} solo: "
                  f"va {int(peor['delta_pct']*100):+d}% en almas sobre tu equipo")
    cuenta = {"critico": sum(1 for x in lista if x["nivel"] == "critico"),
              "alto": sum(1 for x in lista if x["nivel"] == "alto")}

    return {
        "media_equipo": int(media) if media else None,
        "referencia": "media de tu equipo" if media else "sin almas de tu equipo",
        "lista": lista,
        "peor": peor,
        "alerta": alerta,
        "cuenta": cuenta,
    }


def criticos(amenazas):
    """Solo los que obligan a cambiar la compra: críticos o altos que matan."""
    return [x for x in (amenazas or {}).get("lista", ()) if x.get("nivel") == "critico"
            or (x.get("nivel") == "alto" and x.get("evitar_solo"))]
