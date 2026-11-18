"""Ítems situacionales: para qué sirve cada uno y cuándo entra.

No son opiniones del agente: salen de la investigación del 2026-11-07 con su fuente. El
motor los usa de dos maneras:
  1. si el ítem tiene una señal de counter real en los datos de matchup, se le permite
     pasar el filtro de residual (antes quedaba descartado siempre y nunca aparecía);
  2. la razón que se muestra al jugador dice para qué sirve y contra qué.
"""

FECHA = "2026-11-07"

# id -> {tag, para, cuando, fuente}
SITUACIONALES = {
    # anti-curación
    "3696726732": {"tag": "antiheal", "nombre": "Toxic Bullets", "costo": 3200,
                   "para": "-40% curación por sangrado", "cuando": "enemigos con mucha curación",
                   "fuente": "https://denypick.com/items/"},
    "3144988365": {"tag": "antiheal", "nombre": "Decay", "costo": 3200,
                   "para": "-55% curación y se lanza apuntando", "cuando": "enemigos con mucha curación",
                   "fuente": "https://denypick.com/items/"},
    "2603935618": {"tag": "antiheal", "nombre": "Healbane", "costo": 1600,
                   "para": "-35% curación con daño spirit", "cuando": "curación temprana, barato",
                   "fuente": "https://denypick.com/items/"},
    "2037039379": {"tag": "antiheal", "nombre": "Inhibitor", "costo": 6400,
                   "para": "-40% curación y menos daño recibido", "cuando": "mucha curación y pelea larga",
                   "fuente": "https://denypick.com/items/"},
    # contra burst mágico
    "2163598980": {"tag": "antispirit", "nombre": "Spirit Resilience", "costo": 3200,
                   "para": "+30% resistencia spirit", "cuando": "mucho daño spirit",
                   "fuente": "https://denypick.com/items/"},
    "1955841979": {"tag": "antispirit", "nombre": "Spellbreaker", "costo": 6400,
                   "para": "-65% daño spirit tras umbral", "cuando": "burst mágico fuerte",
                   "fuente": "https://denypick.com/items/"},
    "112198670": {"tag": "antispirit", "nombre": "Spirit Shielding", "costo": 1600,
                  "para": "barrera contra daño spirit", "cuando": "burst mágico con poco oro",
                  "fuente": "https://denypick.com/items/"},
    # contra control
    "3357231760": {"tag": "anticc", "nombre": "Unstoppable", "costo": 6400,
                   "para": "5.5 s inmune a control", "cuando": "muchos stuns",
                   "fuente": "https://denypick.com/items/"},
    "1047818222": {"tag": "anticc", "nombre": "Debuff Reducer", "costo": 1600,
                   "para": "reduce duración de control", "cuando": "muchos stuns, barato",
                   "fuente": "https://denypick.com/items/"},
    "1644605047": {"tag": "anticc", "nombre": "Reactive Barrier", "costo": 1600,
                   "para": "barrera al recibir control", "cuando": "CC de inicio de pelea",
                   "fuente": "https://denypick.com/items/"},
    # contra movilidad
    "1813726886": {"tag": "antimovilidad", "nombre": "Slowing Hex", "costo": 1600,
                   "para": "silencia movimiento e ítems de movilidad", "cuando": "enemigos que escapan",
                   "fuente": "https://denypick.com/items/"},
    "1102081447": {"tag": "antimovilidad", "nombre": "Mystic Slow", "costo": 1600,
                   "para": "slow automático con daño spirit", "cuando": "enemigos rápidos",
                   "fuente": "https://denypick.com/items/"},
    "393974127": {"tag": "antimovilidad", "nombre": "Slowing Bullets", "costo": 1600,
                  "para": "slow con balas", "cuando": "enemigos que huyen a tiros",
                  "fuente": "https://denypick.com/items/"},
    # economía / comeback
    "2462046703": {"tag": "recuperacion", "nombre": "Golden Goose Egg", "costo": 800,
                   "para": "genera almas mientras se carga", "cuando": "vas atrás y necesitas escalar",
                   "fuente": "https://denypick.com/items/"},
    "3074274290": {"tag": "recuperacion", "nombre": "Trophy Collector", "costo": 1600,
                   "para": "almas por minuto extra", "cuando": "vas atrás, quieres farmear",
                   "fuente": "https://denypick.com/items/"},
    "2059712766": {"tag": "recuperacion", "nombre": "Restorative Locket", "costo": 1600,
                   "para": "regeneración sostenida", "cuando": "poke constante en línea",
                   "fuente": "https://denypick.com/items/"},
}

# Señales de composición. OJO: esto es una clasificación **heurística del agente** sobre
# el kit de cada héroe, no un dato de la API (heroes.json solo trae id y nombre). Por eso
# solo se usa como desempate y **solo si los datos de matchup del propio proyecto también
# dan señal positiva** para ese ítem contra ese enemigo. Sin las dos cosas, no suma.
# Las claves tienen que ser las de data/heroes_index.json: cuatro estaban mal escritas
# (`mcginness`, `talon`, `geist`, `arcanist`) y una composición de 5 curanderos contaba 4
# (medido en docs/experto/mecanicas.md §4). Corregidas el 2026-11-08.
HEROES_CON = {
    "heal": ("dynamo", "kelvin", "wraith", "paige", "ivy", "mcginnis"),
    "spirit": ("haze", "seven", "lash", "pocket", "grey_talon", "lady_geist", "infernus"),
    "cc": ("mirage", "mcginnis", "bebop", "vindicta", "abrams", "warden"),
    "movilidad": ("haze", "pocket", "wraith", "vindicta", "lash", "infernus"),
}


# Cuánto pesa un enemigo que va por encima cuando el ítem frena justo su amenaza.
# No es una probabilidad: es un multiplicador de prioridad para que el counter del rival
# que está ganando la partida pase por delante del counter genérico de la composición.
PESO_AMENAZA = {"critico": 1.6, "alto": 1.25}

# tag de ítem -> señal de composición (las claves de HEROES_CON). Estaba repetido en
# cuatro sitios con los nombres cruzados y hacía que `tags_de_heroe` no casara con
# `tag`: el counter del crítico salía siempre vacío.
SEÑAL_DE_TAG = {"antiheal": "heal", "antispirit": "spirit", "anticc": "cc",
                "antimovilidad": "movilidad"}


def tag_de(item_id):
    info = SITUACIONALES.get(str(item_id))
    return info["tag"] if info else None


def info(item_id):
    return SITUACIONALES.get(str(item_id))


def _clave_heroe(heroe):
    return str(heroe or "").lower().replace(" ", "_").replace("-", "_")


def tags_de_heroe(heroe):
    """Qué amenazas tiene el kit de este héroe (inverso de HEROES_CON)."""
    clave = _clave_heroe(heroe)
    return [senal for senal, nombres in HEROES_CON.items() if clave in nombres]


def pesos_amenaza(amenazas):
    """{señal: multiplicador} con el rival más peligroso de cada amenaza.

    `amenazas` es la lista de `amenazas.evaluar()["lista"]`. Un crítico que además es
    móvil sube el counter antimovilidad por encima de lo que diga solo la composición.
    """
    peso = {}
    for a in amenazas or ():
        multiplicador = PESO_AMENAZA.get(a.get("nivel"))
        if not multiplicador:
            continue
        for senal in tags_de_heroe(a.get("heroe")):
            if multiplicador > peso.get(senal, 1.0):
                peso[senal] = multiplicador
    return peso


def señales_composicion(heroes_enemigos):
    """Cuenta cuántos enemigos justifican cada señal (0-5)."""
    cuenta = {clave: 0 for clave in HEROES_CON}
    for heroe in heroes_enemigos or []:
        clave_heroe = str(heroe or "").lower().replace(" ", "_").replace("-", "_")
        for señal, nombres in HEROES_CON.items():
            if clave_heroe in nombres:
                cuenta[señal] += 1
    return cuenta


def bonus_contexto(heroes_enemigos, factor=1.0, senal_datos=None, amenazas=None):
    """Devuelve (por item_id -> puntos de score, razones por item_id).

    Peso deliberadamente pequeño frente al lift residual: esto desempata y desbloquea
    situacionales, no reescribe el ranking por sí solo.

    `amenazas` sube ese peso cuando el enemigo que justifica la señal **va por encima**:
    el counter del rival que está ganando la partida vale más que el de la composición
    genérica, y el motivo lo dice con nombre y almas.
    """
    señales = señales_composicion(heroes_enemigos)
    senal_datos = senal_datos or {}
    pesos = pesos_amenaza(amenazas)
    # El peor rival por señal, para poder nombrarlo en el motivo.
    quien = {}
    for a in amenazas or ():
        if not PESO_AMENAZA.get(a.get("nivel")):
            continue
        for senal in tags_de_heroe(a.get("heroe")):
            if senal not in quien or (a.get("delta") or 0) > (quien[senal].get("delta") or 0):
                quien[senal] = a
    puntos, razones = {}, {}
    for iid, datos in SITUACIONALES.items():
        tag = datos["tag"]
        señal = SEÑAL_DE_TAG.get(tag)
        if señal and señales.get(señal):
            peso = min(3, señales[señal]) / 3.0
            multiplo = pesos.get(señal, 1.0)
            peor = quien.get(señal)
            cola = ""
            if peor is not None:
                cola = (f"; {peor.get('heroe')} va "
                        f"{int((peor.get('delta_pct') or 0) * 100):+d}% en almas sobre "
                        f"tu equipo y es a quien hay que frenar")
            if senal_datos.get(iid, 0) > 0.005:
                # Doble respaldo: los datos de 1.9 M de partidas y la composición.
                puntos[iid] = round(4.0 * peso * multiplo * factor, 3)
                razones[iid] = (f"{datos['para']}: {señales[señal]} enemigo(s) lo justifican "
                                f"y los datos del matchup lo apoyan "
                                f"(fuente: {datos['fuente']}, {FECHA}){cola}")
            elif señales[señal] >= 2:
                # Solo composición: menos peso y se dice de dónde viene, para que el
                # jugador sepa que es criterio documentado y no estadística propia.
                puntos[iid] = round(2.0 * peso * multiplo * factor, 3)
                razones[iid] = (f"{datos['para']}: {señales[señal]} enemigo(s) lo justifican "
                                f"(investigación, fuente: {datos['fuente']}, {FECHA}){cola}")
        elif tag == "recuperacion":
            puntos[iid] = round(0.5 * factor, 3)
            razones[iid] = f"{datos['para']} cuando vas atrás"
    return puntos, razones


def sugerencias_composicion(heroes_enemigos, poseidos=(), maximo=2, residuales=None,
                            ganancia=1.0, motivo_ajuste=None, amenazas=None):
    """Ítems que la composición enemiga justifica, **fuera del ranking**.

    No entran en la recomendación porque sus datos de residual son negativos (los compra
    quien ya va perdiendo: el sesgo que este proyecto mide y evita). Se muestran aparte,
    con su fuente y con el dato en contra, para que el jugador decida con todo a la vista.

    `residuales` es {item_id: lift_residual} y viaja hasta la interfaz: sin el número al
    lado, el panel parecía respaldar el ítem y se compraba a ciegas (reportado el 2026-11-08).

    `ganancia` es la ganancia de contexto del motor (`motor.ganancias_contexto`). El
    coeficiente que se muestra es residual × ganancia: el mismo número con el que el
    ranking puntúa el ítem. Así "contra su composición" deja de ser una constante por
    ítem y responde a la fase y a las almas; `coef_global` queda al lado para poder
    comparar con la tabla de 1.9 M de partidas.

    `amenazas` marca el consejo que frena al rival que va por encima (`urgente`) y dice a
    quién: "contra Haze" no es lo mismo que "contra su composición".
    """
    residuales = residuales or {}
    señales = señales_composicion(heroes_enemigos)
    poseidos = {str(x) for x in (poseidos or ())}
    pesos = pesos_amenaza(amenazas)
    candidatos = []
    for iid, datos in SITUACIONALES.items():
        señal = SEÑAL_DE_TAG.get(datos["tag"])
        if not señal or not señales.get(señal):
            continue
        if iid in poseidos or señales[señal] < 2:
            continue
        coef = residuales.get(iid)
        ajustado = None if coef is None else coef * 100 * ganancia
        # Quién de los enemigos justifica esta señal y si alguno va por encima.
        quien = [a.get("heroe") for a in (amenazas or ())
                 if señal in tags_de_heroe(a.get("heroe")) and a.get("heroe")]
        critico = next((a for a in (amenazas or ())
                        if señal in tags_de_heroe(a.get("heroe"))
                        and a.get("nivel") == "critico"), None)
        candidatos.append({
            "id": iid,
            "nombre": datos["nombre"],
            "costo": datos["costo"],
            "para": datos["para"],
            "cuando": datos["cuando"],
            "enemigos_que_lo_justifican": señales[señal],
            "contra_quien": quien,
            "urgente": critico is not None,
            "fuente": datos["fuente"],
            "fecha_fuente": FECHA,
            # Coeficiente CONTEXTUAL en puntos porcentuales: el lift residual de 1.9 M de
            # partidas × la ganancia del estado. Negativo = el ítem lo compra quien ya va
            # perdiendo; se muestra tal cual.
            "coef": None if ajustado is None else round(ajustado, 2),
            "coef_global": None if coef is None else round(coef * 100, 2),
            "peso_contexto": round(ganancia, 2),
            "peso_amenaza": round(pesos.get(señal, 1.0), 2),
            "motivo_ajuste": motivo_ajuste if abs(ganancia - 1.0) >= 0.02 else None,
        })
    # Urgente primero (frena a quien va ganando la partida), luego coeficiente
    # contextual: el consejo se reordena al cambiar el estado, no por precio, que era lo
    # que dejaba siempre los mismos dos arriba (y en ese orden).
    candidatos.sort(key=lambda x: (not x["urgente"], x["coef"] is None,
                                  -(x["coef"] or 0.0), x["costo"]))
    return candidatos[:maximo]
