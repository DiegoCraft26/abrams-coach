"""Puente: carga datos y expone analizar(estado_dict)."""
import os, sys, time
from . import catalogo, motor
from .estado import Estado, validar

# Rango de almas de una partida real. Fuera de esto el dato es una mala lectura, y
# pasarlo a la decisión produce consejos con una economía inventada (QA, 2026-11-07).
ALMAS_MIN, ALMAS_MAX = 0, 200000


def sanear_almas(d):
    """Acota las almas imposibles al rango de una partida real, dejando constancia.

    No basta con que `validar()` lo detecte: el valor seguía llegando a la economía, al
    estado táctico y al panel. Se acota (no a `None`) para que la decisión sea la misma
    que con el valor razonable más cercano y no dependa de por dónde llegó la basura;
    el aviso queda en `notas` y la confianza ya baja por `validar()`.
    """
    if not isinstance(d, dict):
        return d
    d = dict(d)
    avisos = []

    def limpiar(jugador, etiqueta):
        if not isinstance(jugador, dict):
            return jugador
        jugador = dict(jugador)
        valor = jugador.get("almas")
        if valor is None:
            return jugador
        try:
            numero = float(valor)
        except (TypeError, ValueError):
            jugador["almas"] = ALMAS_MIN
            avisos.append(f"{etiqueta}: almas no numéricas ({valor!r}), se toman "
                          f"{ALMAS_MIN}")
            return jugador
        if numero != numero:                      # NaN
            jugador["almas"] = ALMAS_MIN
            avisos.append(f"{etiqueta}: almas NaN, se toman {ALMAS_MIN}")
            return jugador
        acotado = min(max(numero, ALMAS_MIN), ALMAS_MAX)
        if acotado != numero:
            avisos.append(f"{etiqueta}: almas {numero:g} fuera de rango, se toman {acotado:g}")
        jugador["almas"] = int(acotado)
        return jugador

    d["yo"] = limpiar(d.get("yo") or {}, "yo")
    for clave in ("aliados", "enemigos"):
        if isinstance(d.get(clave), list):
            d[clave] = [limpiar(x, clave) for x in d[clave]]
    if avisos:
        d["notas"] = list(d.get("notas") or []) + avisos
    return d


class Motor:
    def __init__(self, cfg=None):
        self.cat = catalogo.cargar()
        import json
        ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "conocimiento.json")
        self.conoc = json.load(open(ruta))
        self.cfg = dict(motor.CFG_DEFECTO)
        if cfg:
            self.cfg.update(cfg)
        self.ultimo_ms = 0.0

    def estado_desde(self, d):
        return Estado.desde_dict(sanear_almas(d))

    def analizar_dict(self, d):
        t0 = time.perf_counter()
        d = sanear_almas(d)
        e = Estado.desde_dict(d)
        problemas = validar(e)
        if problemas:
            e.notas = list(e.notas) + problemas
            e.confianza = min(e.confianza, 0.5)
        r = motor.recomendar(e, self.conoc, self.cat, self.cfg)
        r["ms"] = round((time.perf_counter() - t0) * 1000, 2)
        r["notas"] = e.notas
        r["heroe"] = e.yo.heroe
        r["fuente"] = e.fuente
        self.ultimo_ms = r["ms"]
        return r
