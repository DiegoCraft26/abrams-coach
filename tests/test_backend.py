"""Suite de backend: dominio, bus y config. Sin dependencias externas."""
import json
import os
import sys
import tempfile
import threading
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from coach.dominio import (
    Jugador, Item, Recomendacion, Evento, Partida, EstadoPartida,
)
from coach.bus import Bus
from coach.config import cargar, guardar, Config

HECHOS = {}


def check(nombre, condicion, detalle=""):
    HECHOS[nombre] = bool(condicion)
    print(f"  {'ok  ' if condicion else 'FALLA'} {nombre}{(' · ' + detalle) if detalle else ''}")


def main():
    print("backend: dominio, bus, config")
    fallos = 0

    # ---------------- dominio: ida y vuelta ----------------
    j = Jugador(heroe="Abrams", almas=3000, items=["800"], bajas=2, muertes=1, asistencias=3)
    j2 = Jugador.desde_dict(j.a_dict())
    check("Jugador ida y vuelta", j == j2, str(j.a_dict()))

    it = Item(id="800", nombre="Restorative Shot", slot="vitality", costo=500, tier=1, n=100)
    it2 = Item.desde_dict(it.a_dict())
    check("Item ida y vuelta", it == it2)

    r = Recomendacion(id="800", nombre="Restorative Shot", costo=500, slot="vitality",
                      score=1.23, residual=0.05, n=100, razones=["buena"], requiere_venta=False)
    r2 = Recomendacion.desde_dict(r.a_dict())
    check("Recomendacion ida y vuelta", r == r2)

    ev = Evento(tipo="compra", t=120.0, datos={"id": "800"}, fuente="vivo", ts=1.0, notas=["x"])
    ev2 = Evento.desde_dict(ev.a_dict())
    check("Evento ida y vuelta", ev == ev2)

    pa = Partida(match_id=123, heroe="Abrams", fuente="vivo", t=600.0, confianza=0.9,
                 yo=Jugador(heroe="Abrams", almas=1000), aliados=[Jugador(almas=900)],
                 enemigos=[Jugador(heroe="haze", almas=1100)], notas=["ok"])
    pa2 = Partida.desde_dict(pa.a_dict())
    check("Partida ida y vuelta", pa == pa2)

    d0 = {"t": 1200, "yo": {"heroe": "Abrams", "almas": 3000, "items": ["800"]},
          "aliados": [{"heroe": "aliado", "almas": 2900}],
          "enemigos": [{"heroe": "haze", "almas": 3100}],
          "fuente": "vivo", "confianza": 0.9}
    ep = EstadoPartida.desde_dict(d0)
    ep2 = EstadoPartida.desde_dict(ep.a_dict())
    check("EstadoPartida ida y vuelta estable", ep == ep2)
    check("EstadoPartida conserva t", ep.t == 1200)
    check("EstadoPartida conserva fuente", ep.fuente == "vivo")
    check("EstadoPartida conserva confianza", abs(ep.confianza - 0.9) < 1e-9)
    check("EstadoPartida yo heroe", ep.yo.heroe == "Abrams")
    check("EstadoPartida yo almas", ep.yo.almas == 3000)
    check("EstadoPartida yo items", ep.yo.items == ["800"])

    # ---------------- tolerancia a basura ----------------
    for cls in (Jugador, Item, Recomendacion, Evento, Partida, EstadoPartida):
        try:
            obj = cls.desde_dict(None)
            obj2 = cls.desde_dict("no es dict")
            obj3 = cls.desde_dict([])
            check(f"{cls.__name__} tolera basura", True)
        except Exception as e:
            check(f"{cls.__name__} tolera basura", False, repr(e))

    # listas vacías / ausentes
    epv = EstadoPartida.desde_dict({})
    check("EstadoPartida vacío -> t=0", epv.t == 0)
    check("EstadoPartida vacío -> aliados=[]", epv.aliados == [])
    check("EstadoPartida vacío -> enemigos=[]", epv.enemigos == [])
    check("EstadoPartida vacío -> items=[]", epv.yo.items == [])

    jv = Jugador.desde_dict({})
    check("Jugador vacío -> almas=None", jv.almas is None)
    check("Jugador vacío -> bajas=0", jv.bajas == 0)

    # ---------------- bus ----------------
    bus = Bus()
    recibidos = {"a": [], "b": []}

    def sa(estado):
        recibidos["a"].append(estado)

    def sb(estado):
        recibidos["b"].append(estado)

    def sfallo(estado):
        raise RuntimeError("boom")

    des_a = bus.suscribir(sa)
    des_b = bus.suscribir(sb)
    bus.suscribir(sfallo)

    estado_in = {"x": 1}
    v1 = bus.publicar(estado_in)
    check("bus publicar devuelve versión 1", v1 == 1)
    check("bus versión() == 1", bus.version() == 1)
    check("suscriptor a recibió", recibidos["a"] == [estado_in])
    check("suscriptor b recibió", recibidos["b"] == [estado_in])
    check("bus fallos == 1", bus.fallos == 1)

    ultimo, ver = bus.leer()
    check("bus leer versión", ver == 1)
    check("bus leer estado", ultimo == estado_in)

    payload, ver2, edad = bus.encuesta()
    check("bus encuesta versión", ver2 == 1)
    check("bus encuesta edad no None", edad is not None)
    check("bus encuesta edad >= 0", edad is not None and edad >= 0)

    # desuscribir
    des_a()
    v2 = bus.publicar({"x": 2})
    check("bus segunda versión == 2", v2 == 2)
    check("desuscrito no recibe", len(recibidos["a"]) == 1)
    check("suscrito sigue recibiendo", len(recibidos["b"]) == 2)

    # thread-safety básica
    errores = []

    def worker():
        try:
            for i in range(50):
                bus.publicar({"i": i})
        except Exception as e:
            errores.append(e)

    hilos = [threading.Thread(target=worker) for _ in range(4)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    check("bus multihilo sin excepción", len(errores) == 0)
    check("bus versión final == 202", bus.version() == 2 + 4 * 50)

    # ---------------- config archivo real ----------------
    cfg = cargar()
    check("config carga real", isinstance(cfg, Config))
    check("config get motor.w_lift", cfg.get("motor.w_lift") == 1.0,
         str(cfg.get("motor.w_lift")))
    check("config get ui.angosto_max", cfg.get("ui.angosto_max") == 760,
         str(cfg.get("ui.angosto_max")))
    check("config avisos vacío (archivo real)", cfg.avisos == [], str(cfg.avisos))
    check("config motor dict", isinstance(cfg.motor, dict))
    check("config ui dict", isinstance(cfg.ui, dict))
    check("config fuentes dict", isinstance(cfg.fuentes, dict))
    check("config agente dict", isinstance(cfg.agente, dict))
    check("config flags dict", isinstance(cfg.flags, dict))
    check("config agente modelo", cfg.agente.get("modelo") == "deepseek/deepseek-v4.1-flash")

    # ---------------- config YAML roto en /tmp ----------------
    tmpdir = tempfile.gettempdir()
    ruta_rota = os.path.join(tmpdir, "coach_roto_test.yaml")
    with open(ruta_rota, "w", encoding="utf-8") as f:
        f.write(":\n  - [\n  esto no es yaml valido\n")
    cfg_rota = cargar(ruta_rota)
    check("config YAML roto -> Config", isinstance(cfg_rota, Config))
    check("config YAML roto -> avisos no vacío", len(cfg_rota.avisos) > 0,
         str(cfg_rota.avisos))
    check("config YAML roto -> w_lift default", cfg_rota.get("motor.w_lift") == 1.0)
    check("config YAML roto -> angosto_max default", cfg_rota.get("ui.angosto_max") == 760)

    # ---------------- corrección fuera de rango ----------------
    ruta_mala = os.path.join(tmpdir, "coach_malo_test.yaml")
    import yaml
    datos_malos = {
        "motor": {"w_lift": 999, "venta_margen_s": -5, "fase_minima_s": 999999},
        "ui": {"angosto_max": -1, "actualizacion_hz": 0},
        "fuentes": {"timeout_s": -1, "reintentos": 9999},
        "agente": {"timeout_s": 0, "presupuesto_llamadas_min": -3},
        "flags": {"debug": "si"},
    }
    with open(ruta_mala, "w", encoding="utf-8") as f:
        yaml.safe_dump(datos_malos, f)
    cfg_mala = cargar(ruta_mala)
    check("fuera de rango -> avisos no vacío", len(cfg_mala.avisos) > 0, str(cfg_mala.avisos))
    check("fuera de rango -> w_lift corregido", cfg_mala.get("motor.w_lift") == 1.0)
    check("fuera de rango -> venta_margen_s corregido", cfg_mala.get("motor.venta_margen_s") == 60)
    check("fuera de rango -> angosto_max corregido", cfg_mala.get("ui.angosto_max") == 760)
    check("fuera de rango -> actualizacion_hz corregido", cfg_mala.get("ui.actualizacion_hz") == 1)
    check("fuera de rango -> timeout fuentes corregido", cfg_mala.get("fuentes.timeout_s") == 10)
    check("fuera de rango -> reintentos corregido", cfg_mala.get("fuentes.reintentos") == 3)
    check("fuera de rango -> timeout agente corregido", cfg_mala.get("agente.timeout_s") == 45)
    check("fuera de rango -> flag no bool -> False", cfg_mala.flags.get("debug") is False)

    # JSON fallback
    ruta_json = os.path.join(tmpdir, "coach_json_test.json")
    with open(ruta_json, "w", encoding="utf-8") as f:
        json.dump({"motor": {"w_lift": 0.5}, "ui": {"angosto_max": 700}}, f)
    cfg_json = cargar(ruta_json)
    check("config JSON fallback w_lift", cfg_json.get("motor.w_lift") == 0.5)
    check("config JSON fallback angosto", cfg_json.get("ui.angosto_max") == 700)

    # guardar idempotente
    ruta_guardar = os.path.join(tmpdir, "coach_guardar_test.yaml")
    guardar(cfg, ruta_guardar)
    cfg2 = cargar(ruta_guardar)
    check("guardar/cargar estable w_lift", cfg2.get("motor.w_lift") == cfg.get("motor.w_lift"))
    check("guardar/cargar estable angosto", cfg2.get("ui.angosto_max") == cfg.get("ui.angosto_max"))

    # limpieza
    for p in (ruta_rota, ruta_mala, ruta_json, ruta_guardar):
        try:
            os.remove(p)
        except OSError:
            pass

    print()
    fallos = sum(1 for v in HECHOS.values() if not v)
    if fallos:
        print(f"backend: {fallos} fallos -> {[k for k,v in HECHOS.items() if not v]}")
    else:
        print(f"backend: OK ({len(HECHOS)} comprobaciones)")
    return fallos


def test_suite():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
