#!/usr/bin/env python3
"""QA de comportamiento esperado: seis escenarios con estados inyectados.

No juega, no abre el juego y no toca el navegador. Todo sale de estados sintéticos
armados con el conocimiento real del proyecto (data/conocimiento.json, componentes.json)
y del mismo motor, servidor y bucle que corre en partida.

Los escenarios 3, 4 y 6 necesitan el bucle en vivo, que es infinito: se corren en un
subproceso (`--hijo`) con el reloj del bucle falseado para no esperar 12 s reales.
El servidor de 8090 no se toca: los chequeos de HTTP usan un puerto libre.

Uso:
    /tmp/dlvenv/bin/python herramientas/qa_comportamiento.py
    /tmp/dlvenv/bin/python herramientas/qa_comportamiento.py --escenario 2

Doc con la tabla de resultados: docs/QA-comportamiento.md
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

# Cuenta de prueba para los escenarios que consultan el API. Sin ABRAMS_CUENTA el
# escenario 6 usa 0: sirve igual para probar que un fallo de red no cuelga ni miente,
# que es lo único que mide.
CUENTA_QA = int(os.environ.get("ABRAMS_CUENTA", "0"))

EXTRA_HEALTH = "3633614685"
COLOSSUS = "2407781327"
WITCHMAIL = "3028234315"
SPRINT_BOOTS = "3399065363"
GRIT = "1672893796"
EXTRA_STAMINA = "4139877411"
NO_VENDIBLES = [COLOSSUS, WITCHMAIL, "1371725689", "3357231760"]  # Colossus, Witchmail, Phantom Strike, Unstoppable
COMP_ENEMIGA = [{"heroe": "Haze", "almas": 6000}, {"heroe": "Infernus", "almas": 6000}]

HECHOS = []


def probar(nombre, condicion, detalle=""):
    HECHOS.append({"nombre": nombre, "ok": bool(condicion), "detalle": str(detalle)})
    print(f"  {'ok  ' if condicion else 'FALLA'} {nombre}{(' · ' + str(detalle)) if detalle else ''}")
    return bool(condicion)


def estado(t, almas, items, enemigos=None, oro=None):
    yo = {"heroe": "Abrams", "almas": almas, "items": list(items)}
    if oro is not None:
        yo["oro"] = oro
    return {"t": t, "yo": yo, "aliados": [],
            "enemigos": enemigos if enemigos is not None else COMP_ENEMIGA,
            "confianza": 1.0, "fuente": "manual"}


def motor():
    from coach.motor_api import Motor
    return Motor()


def filas_de(m, est):
    """Ranking completo por id, con lo que el panel no enseña (requiere_venta incluido)."""
    from coach import motor as motor_mod
    from coach.decision import heroe as heroes
    e = m.estado_desde(est)
    _, filas = motor_mod.candidatos(e, m.conoc, m.cat, m.cfg, limite=10,
                                    heroe=heroes.cargar(e.yo.heroe or "abrams"))
    return {f["id"]: f for f in filas}


# --------------------------------------------------------------- escenario 1
def escenario1(m):
    print("\n1 · Extra Health + Colossus: pagar solo la diferencia")
    est = estado(900, 6000, [EXTRA_HEALTH], oro=6000)
    r = m.analizar_dict(est)
    filas = filas_de(m, est)
    col = filas.get(COLOSSUS)
    probar("Colossus entra en el ranking", col is not None)
    if col:
        probar("paga la diferencia (5,600 de 6,400)", col["costo"] == 5600,
               f"costo={col['costo']} lista={col['costo_lista']} ahorro={col['ahorro']}")
        probar("no pide vender", col["requiere_venta"] is False,
               f"requiere_venta={col['requiere_venta']}")
        probar("la razón dice qué absorbe", any("Extra Health" in x for x in col["razones"]),
               [x for x in col["razones"] if "Extra Health" in x])
    probar("la venta sugerida está vacía", r["venta"] is None, r["venta"])
    ids_panel = [x["id"] for x in r["recomendaciones"][:3]]
    probar("el panel lo enseña entre las tres primeras", COLOSSUS in ids_panel,
           [x["nombre"] for x in r["recomendaciones"][:3]])
    orden = [x["id"] for x in r["recomendaciones"]]
    if COLOSSUS in orden:
        print(f"       posición de Colossus en la lista del motor: {orden.index(COLOSSUS) + 1}"
              f" de {len(orden)}")


# --------------------------------------------------------------- escenario 2
def escenario2(m):
    print("\n2 · slots de vitalidad llenos")
    llenos = [EXTRA_HEALTH, SPRINT_BOOTS, GRIT, EXTRA_STAMINA]   # 4 de 4, todos vendibles
    est = estado(1500, 30000, llenos)
    filas = filas_de(m, est)
    col = filas.get(COLOSSUS)
    probar("un upgrade entra sin vender (Colossus libera el hueco de Extra Health)",
           col is not None and col["requiere_venta"] is False and col["costo"] == 5600,
           col and f"costo={col['costo']} venta={col['requiere_venta']}")
    witch = filas.get(WITCHMAIL)
    probar("un ítem nuevo NO entra gratis con el slot lleno (Witchmail pide venta)",
           witch is not None and witch["requiere_venta"] is True,
           witch and f"costo={witch['costo']} venta={witch['requiere_venta']}")
    r = m.analizar_dict(est)
    probar("para ese ítem nuevo propone a quién vender", bool(r["venta"]),
           r["venta"] and f"vende {r['venta']['nombre']} → {r['venta']['para']}")

    est2 = estado(1500, 30000, NO_VENDIBLES)
    filas2 = filas_de(m, est2)
    de_vitalidad = [f["nombre"] for f in filas2.values() if f["slot"] == "vitality"]
    probar("sin nada vendible en el slot, ningún ítem nuevo de vitalidad aparece",
           not de_vitalidad, de_vitalidad)


# --------------------------------------------------------------- escenario 5
def escenario5(m):
    print("\n5 · determinismo y sensibilidad al reloj")
    est = estado(900, 6000, ["800"])
    a = m.analizar_dict(json.loads(json.dumps(est)))
    b = m.analizar_dict(json.loads(json.dumps(est)))
    firma = lambda r: [(x["id"], x["costo"], x["score"]) for x in r["recomendaciones"]]
    probar("el mismo estado dos veces da la misma recomendación", firma(a) == firma(b),
           a["recomendaciones"][0]["nombre"] if a["recomendaciones"] else "sin recomendación")

    # con la capa de la app (estabilizador) y reloj de pared falseado
    import coach.estabilizador as EST
    import run as R

    class Reloj:
        def __init__(self, t=1000.0):
            self.t = t

        def time(self):
            return self.t

    reloj = Reloj()
    original = EST.time
    EST.time = reloj
    try:
        analizar = R.crear_analizador(motor())
        x = analizar(estado(600, 6000, ["800"]))
        y = analizar(estado(600, 6000, ["800"]))
        probar("con el estabilizador, el mismo estado dos veces no cambia",
               x["recomendaciones"][0]["id"] == y["recomendaciones"][0]["id"],
               f"{x['recomendaciones'][0]['nombre']} / {y['recomendaciones'][0]['nombre']}")
        reloj.t += 60
        z = analizar(estado(660, 6000, ["800"]))
        probar("dos estados con 60 s de diferencia pueden dar otra recomendación",
               z["recomendaciones"][0]["id"] != y["recomendaciones"][0]["id"],
               f"{y['recomendaciones'][0]['nombre']} → {z['recomendaciones'][0]['nombre']}")
    finally:
        EST.time = original

    # mismo resultado en otro proceso (sin depender de hash ni del reloj)
    huellas = []
    for _ in range(2):
        salida = subprocess.run([sys.executable, os.path.abspath(__file__), "--hijo", "huella"],
                                capture_output=True, text=True, timeout=120)
        huellas.append(salida.stdout.strip().splitlines()[-1] if salida.stdout.strip() else "")
    probar("dos procesos distintos dan la misma huella", len(set(huellas)) == 1 and huellas[0],
           huellas[0][:60])


# ------------------------------------------------------- servidor: rancio
def _puerto_libre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    puerto = s.getsockname()[1]
    s.close()
    return puerto


def _get_json(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read().decode())


def _estado_http(servidor_mod, puerto):
    """Lo mismo que ve el panel: payload + edad_s + rancio."""
    return _get_json(f"http://127.0.0.1:{puerto}/api/estado")


def _publicacion(t, compras=True):
    d = {"t": t, "almas": 6000, "oro": 600, "fuente": "en_vivo",
         "estado": {"estado": "PELEAR", "motivo": "vas 12% arriba", "objetivo": "presiona"},
         "recomendaciones": [{"id": COLOSSUS, "nombre": "Colossus", "costo": 5600,
                              "score": 9.0, "razones": ["x"]}],
         "plan": [], "inventario": [], "enemigos": [], "aliados": [],
         "notas": [], "almas_12": [6000] * 12}
    if compras:
        d["compras"] = [{"texto": "Abrams: Extra Health", "item": EXTRA_HEALTH, "ts": 0}]
    return d


def _con_tope(tope_s, accion):
    """Corre `accion` contra un reloj que avanza al dormir y corta a los `tope_s`."""
    import coach.servidor as S
    puerto = _puerto_libre()
    srv = S.arrancar(puerto)
    umbral_original = S.UMBRAL_RANCIO_S
    S.UMBRAL_RANCIO_S = tope_s * 0.4
    try:
        return accion(S, puerto)
    finally:
        S.UMBRAL_RANCIO_S = umbral_original
        srv.shutdown()
        srv.server_close()


# --------------------------------------------------------------- escenario 3
def escenario3():
    print("\n3 · partida pausada: el reloj se congela")
    hijo = _hijo("congelado")
    tics = [t for t in hijo["ticks_publicados"] if t is not None]
    probar("el reloj publicado no avanza", len(tics) <= 1, f"ticks publicados {hijo['ticks_publicados']}")
    avisos = hijo["aviso_congelado"]
    probar("avisa una sola vez que el broadcast se paró", len(avisos) == 1,
           avisos[0]["mensaje"] if avisos else "sin aviso")
    probar("no republica el estado viejo después del aviso",
           hijo["ultimo"].get("listo") is False, hijo["ultimo"])
    probar("el aviso no lleva compras ni recomendaciones",
           "recomendaciones" not in hijo["ultimo"] and "compras" not in hijo["ultimo"],
           sorted(hijo["ultimo"]))

    def correr(S, puerto):
        for _ in range(3):                     # ráfaga cada 3 s de un tick parado
            S.EST.publicar(_publicacion(900.0))
            time.sleep(0.12)
        time.sleep(1.0)                        # el stream sigue mudo
        return _estado_http(S, puerto)

    datos = _con_tope(1.5, correr)
    probar("con el reloj parado, a los pocos segundos ya no está fresco",
           datos.get("rancio") is True, f"edad={datos.get('edad_s')} rancio={datos.get('rancio')}")
    probar("el tiempo que muestra el panel sigue siendo el mismo",
           datos.get("t") == 900.0, datos.get("t"))


# --------------------------------------------------------------- escenario 4
def escenario4():
    print("\n4 · partida terminada: rancio y sin la última compra como actual")
    def correr(S, puerto):
        S.EST.publicar(_publicacion(2080.0))          # último estado que llegó
        antes = _estado_http(S, puerto)
        time.sleep(1.2)                               # el stream ya no manda nada
        despues = _estado_http(S, puerto)
        S.EST.publicar({"listo": False, "fuente": "en_vivo",
                        "mensaje": "el broadcast dejó de mandar datos (último tick 133120); reintentando"})
        aviso = _estado_http(S, puerto)
        return antes, despues, aviso

    antes, despues, aviso = _con_tope(1.5, correr)
    probar("mientras llega, el estado es fresco", antes.get("rancio") is False,
           f"edad={antes.get('edad_s')}")
    probar("al dejar de llegar, pasa a rancio", despues.get("rancio") is True,
           f"edad={despues.get('edad_s')}")
    probar("la edad crece sola (nada repone la marca de tiempo)",
           (despues.get("edad_s") or 0) > (antes.get("edad_s") or 0),
           f"{antes.get('edad_s')} → {despues.get('edad_s')}")
    probar("el aviso deja el panel sin partida", aviso.get("listo") is False, aviso.get("mensaje"))
    probar("y sin la última compra ni la última recomendación",
           "recomendaciones" not in aviso and "compras" not in aviso,
           sorted(aviso))


# --------------------------------------------------------------- escenario 6
def escenario6():
    print("\n6 · sin conexión al API")
    from coach import en_vivo
    from coach.fuentes import api_vivo

    original = urllib.request.urlopen

    def sin_red(*a, **k):
        raise urllib.error.URLError("sin red (QA)")

    urllib.request.urlopen = sin_red
    try:
        t0 = time.perf_counter()
        match = en_vivo.partida_activa(CUENTA_QA)
        dt = time.perf_counter() - t0
        probar("partida_activa no se cuelga y devuelve None", match is None and dt < 5,
               f"{dt:.2f} s, match={match}")
        t0 = time.perf_counter()
        hallado = api_vivo.descubrir(cuenta=CUENTA_QA, forzar=True, con_hud=False)
        dt = time.perf_counter() - t0
        probar("descubrir no se cuelga y no inventa un match",
               hallado["match"] is None and dt < 15, f"{dt:.2f} s")
        probar("descubrir NO dice que la cuenta no está en partida cuando no pudo consultar",
               "no pudo" in hallado["detalle"] or "sin conexión" in hallado["detalle"]
               or "sin red" in hallado["detalle"], hallado["detalle"])
        errores = en_vivo.DIARIO.resumen()["errores"]
        probar("el fallo de red queda anotado para el diagnóstico", bool(errores),
               errores[-1]["texto"] if errores else "el diario quedó vacío")
    finally:
        urllib.request.urlopen = original

    hijo = _hijo("sinred")
    probar("el bucle vivo sigue publicando (no se cuelga)", hijo["publicados"] > 0,
           f"{hijo['publicados']} publicaciones")
    probar("el bucle marca listo=False: no finge una partida en curso",
           hijo["alg_aviso_listo_false"], f"fuentes={hijo['fuentes']}")
    textos = [t.lower() for t in hijo["textos"] if t]
    probar("el bucle dice qué falta (conexión, red o cuota de la API)",
           any(clave in t for t in textos for clave in ("conex", "sin red", "api", "cuota")),
           hijo["textos"][:2])


# --------------------------------------------------------------- subprocesos
class RelojFalso:
    """Reloj del bucle: avanza al dormir, sin esperar de verdad, y corta al tope."""

    def __init__(self, tope_s, al_terminar):
        self.t = 1000.0
        self.inicio = 1000.0
        self.tope = tope_s
        self.al_terminar = al_terminar

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += max(0.5, float(s))
        if self.t - self.inicio >= self.tope:
            self.al_terminar()


def _hijo_vivo(modo):
    """Corre bucle_vivo con el stream falseado y devuelve lo que se publicó."""
    import threading
    import run as R
    from coach import en_vivo as EV
    from coach import servidor as S
    import coach.registro as REG
    from coach import hud as HUD

    publicados = []
    original = S.EST.publicar

    def espia(datos):
        publicados.append(dict(datos) if isinstance(datos, dict) else datos)
        return original(datos)

    S.EST.publicar = espia

    def terminar():
        print(json.dumps({
            "publicados": len(publicados),
            "ticks_publicados": [p.get("t") for p in publicados][:20],
            "aviso_congelado": [p for p in publicados if isinstance(p, dict) and p.get("listo") is False],
            "fuentes": sorted({str(p.get("fuente")) for p in publicados if isinstance(p, dict)}),
            "notas": [p.get("notas") for p in publicados[-1:]][0] if publicados else None,
            "textos": sorted({str(x) for p in publicados if isinstance(p, dict)
                              for x in ([p.get("mensaje")] if p.get("mensaje") else [])
                              + list(p.get("notas") or [])}),
            "alg_aviso_listo_false": any(isinstance(p, dict) and p.get("listo") is False
                                         for p in publicados),
            "ultimo": publicados[-1] if publicados else None,
        }, ensure_ascii=False, default=str), flush=True)
        os._exit(0)

    R.time = RelojFalso(20.0 if modo == "congelado" else 15.0, terminar)
    R.arrancar_hud = lambda a, hud, flags: {"t": None, "oro": None, "ts": 0.0}
    R.ajustar_con_hud = lambda *a, **k: None
    R.medir_latencias = lambda a: {}
    REG.anotar = lambda *a, **k: None
    HUD.leer_match_id = lambda *a, **k: None

    class EscuchaFalsa:
        def __init__(self, *a, **k):
            j = {"cuenta": 1, "equipo": 2, "heroe": "Abrams", "almas": 6000, "neto": 6300,
                 "oro": 600, "bajas": 1, "muertes": 0, "asistencias": 2,
                 "items": [EXTRA_HEALTH]}
            j2 = {"cuenta": 2, "equipo": 3, "heroe": "Haze", "almas": 6000, "neto": 6100,
                  "oro": 300, "bajas": 0, "muertes": 1, "asistencias": 1, "items": []}
            self.estado = {"tick": 57600, "t": 900.0, "jugadores": [j, j2], "yo": j,
                           "aliados": [j], "enemigos": [j2]}
            self.error = None
            self.filas = 0

        def arrancar(self):
            return self

        def parar(self, espera=1.0):
            return self

        def vivo(self):
            return True

    def revienta(*a, **k):
        raise OSError("sin red (QA)")

    if modo == "congelado":
        EV.partida_activa = lambda cuenta, timeout=20: 111
        EV.Escucha = EscuchaFalsa
    else:
        EV.partida_activa = lambda cuenta, timeout=20: None
        EV.listado_activo = revienta
        EV.buscar_en_listado = revienta

    class Args:
        match = None
        cuenta = 1
        intervalo = 1.0
        sin_hud = True

    def analizar(d):
        return {"t": d.get("t"), "almas": (d.get("yo") or {}).get("almas"), "listo": True,
                "fuente": "en_vivo",
                "recomendaciones": [{"id": COLOSSUS, "nombre": "Colossus", "costo": 5600,
                                     "score": 9.0, "razones": ["aprovecha lo que ya llevas"]}],
                "compras": [{"texto": "Abrams: Colossus", "item": COLOSSUS, "ts": 0}],
                "estado": {"estado": "PELEAR", "motivo": "vas arriba"}}

    threading.Thread(target=R.bucle_vivo, args=(Args(), analizar), daemon=True).start()
    time.sleep(8.0)
    terminar()


def _hijo_huella():
    m = motor()
    r = m.analizar_dict(estado(900, 6000, [EXTRA_HEALTH]))
    print(json.dumps([(x["id"], x["costo"], x["score"]) for x in r["recomendaciones"]]),
          flush=True)
    return 0


def _hijo(modo):
    salida = subprocess.run([sys.executable, os.path.abspath(__file__), "--hijo", modo],
                            capture_output=True, text=True, timeout=180)
    lineas = [x for x in salida.stdout.strip().splitlines() if x.strip()]
    if not lineas:
        raise SystemExit(f"el hijo {modo} no devolvió nada: {salida.stderr[-400:]}")
    return json.loads(lineas[-1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--escenario", type=int, default=0, help="1..6, 0 = todos")
    ap.add_argument("--hijo", default=None, help="interno: corre un escenario en subproceso")
    a = ap.parse_args()

    if a.hijo == "huella":
        return _hijo_huella()
    if a.hijo:
        return _hijo_vivo(a.hijo)

    m = motor()
    escenarios = {1: lambda: escenario1(m), 2: lambda: escenario2(m), 3: escenario3,
                  4: escenario4, 5: lambda: escenario5(m), 6: escenario6}
    for numero in ([a.escenario] if a.escenario else range(1, 7)):
        escenarios[numero]()

    fallos = [h for h in HECHOS if not h["ok"]]
    print(f"\n{len(HECHOS) - len(fallos)}/{len(HECHOS)} comprobaciones OK")
    for h in fallos:
        print(f"  FALLA {h['nombre']} · {h['detalle']}")
    return 0 if not fallos else 1


if __name__ == "__main__":
    sys.exit(main())
