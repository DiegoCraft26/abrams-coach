"""Filtro de estabilidad: detecta lecturas imposibles y evita que el panel parpadee."""
import time
from collections import deque


class Estabilizador:
    def __init__(self, margen_cambio=0.8, repeticiones=2, ventana=6, quietud_s=10.0):
        self.margen = margen_cambio
        self.repeticiones = repeticiones
        self.historial = deque(maxlen=ventana)
        self.anterior = None          # última salida buena
        self.actual = None            # recomendación fijada
        self.contador = 0
        self.tiempo_quieto = 0
        self.quietud_s = quietud_s
        self.cambio_ts = 0.0

    # ---------- detección de errores de lectura ----------
    def anomalias(self, estado):
        problemas = []
        almas = estado.yo.almas
        t = estado.t
        ult = self.historial[-1] if self.historial else None

        if ult:
            t_ant, almas_ant = ult
            if t is not None and t_ant is not None:
                if t < t_ant - 2:
                    problemas.append("el reloj retrocedió")
                elif t == t_ant:
                    self.tiempo_quieto += 1
                    if self.tiempo_quieto >= 4:
                        problemas.append("el reloj no avanza")
                else:
                    self.tiempo_quieto = 0
            if almas is not None and almas_ant is not None:
                subida = almas - almas_ant
                if subida > 12000:
                    problemas.append(f"salto imposible de almas (+{subida:,})")
                if subida < -12000:
                    problemas.append(f"caída imposible de almas ({subida:,})")
        else:
            self.tiempo_quieto = 0

        if almas is not None and almas < 0:
            problemas.append("almas negativas")
        if t is not None and t > 5400:
            problemas.append("tiempo fuera de rango")
        self.historial.append((t, almas))
        return problemas

    # ---------- histéresis de la recomendación ----------
    def _fijar_actual(self, nuevo, ahora):
        self.actual, self.contador = nuevo, 1
        self.cambio_ts = ahora

    def fijar(self, salida):
        recos = salida.get("recomendaciones") or []
        if not recos:
            self.actual = None
            self.contador = 0
            return salida

        nuevo = recos[0]
        ahora = time.time()

        # quietud mínima: no cambiar de opinión antes de `quietud_s`, salvo salto grande
        if (self.actual is not None and nuevo["id"] != self.actual["id"]
                and ahora - self.cambio_ts < self.quietud_s
                and nuevo["score"] < self.actual["score"] + 3.0):
            salida["recomendaciones"] = [self.actual] + [r for r in recos if r["id"] != self.actual["id"]]
            salida["estable"] = True
            return salida

        if self.actual is None:
            self._fijar_actual(nuevo, ahora)
        elif nuevo["id"] == self.actual["id"]:
            self.actual = nuevo
            self.contador += 1
        else:
            self.contador += 1
            if self.contador >= self.repeticiones or nuevo["score"] > self.actual["score"] + self.margen:
                self._fijar_actual(nuevo, ahora)

        salida["recomendaciones"] = [self.actual] + [r for r in recos if r["id"] != self.actual["id"]]
        salida["estable"] = self.contador >= self.repeticiones
        return salida

    def procesar(self, estado, salida):
        # en modo demo la partida se reinicia en bucle: no es una lectura rota
        if estado.fuente == "simulado":
            self.historial.clear()
            self.tiempo_quieto = 0
        problemas = self.anomalias(estado)
        if problemas:
            salida["notas"] = list(salida.get("notas") or []) + problemas
            salida["confianza"] = min(salida.get("confianza", 1.0), 0.35)
            salida["lectura_dudosa"] = True
            if self.anterior:
                salida["recomendaciones"] = self.anterior.get("recomendaciones", [])
        else:
            salida["lectura_dudosa"] = False
            salida = self.fijar(salida)
            self.anterior = salida
        salida["ts"] = time.time()
        return salida
