"""Captura bajo demanda para la visión: un cuadro cuando hace falta, no un vídeo.

El relevo pedía "1 cuadro/5 s + eventos". Con la latencia medida (~23 s por cuadro) eso no
significa 5 s entre capturas, significa **no tener dos peticiones peleando**: este módulo
decide *cuándo* merece la pena mandar un cuadro y deja la cola (y el tope) a
`coach.agente.vision_cola`.

Quién manda:
- la **tienda abierta** (B): es la única vista con los 12 ítems, prioridad máxima;
- el **marcador** (Tab): almas y KDA de los dos equipos;
- **periódico**: reloj y oro cada `intervalo_s`, para no perder el hilo de la partida.

Y de dónde se recorta: del monitor del juego, no del escritorio completo (el panel y los
otros monitores no aportan y encarecen la imagen). El monitor se elige por prioridad de
KWin y se cachea: preguntarlo en cada cuadro costaba más que leerlo.
"""
from __future__ import annotations

import os
import re
import subprocess
import time

ANSI = re.compile(r"\x1b\[[0-9;]*m")
_CACHE_CAJA: dict = {"ts": 0.0, "caja": None}
VIDA_CAJA_S = 60.0


def _parsear_salidas(texto: str) -> list[tuple]:
    """[(nombre, x, y, ancho, alto, prioridad)] de la salida de `kscreen-doctor -o`."""
    salidas = []
    nombre = None
    prioridad = 0
    geometria = None
    for linea in ANSI.sub("", texto).splitlines():
        linea = linea.strip()
        encontrado = re.match(r"Output:\s*\d+\s+(\S+)", linea)
        if encontrado:
            nombre, prioridad, geometria = encontrado.group(1), 0, None
            continue
        if linea.startswith("priority"):
            try:
                prioridad = int(linea.split()[-1])
            except (IndexError, ValueError):
                prioridad = 0
            continue
        if linea.startswith("Geometry:") and nombre:
            try:
                coords, tamano = linea.split(":", 1)[1].split()
                x, y = (int(v) for v in coords.split(","))
                ancho, alto = (int(v) for v in tamano.split("x"))
            except (IndexError, ValueError):
                continue
            geometria = (x, y, ancho, alto)
            salidas.append((nombre, x, y, ancho, alto, prioridad))
    return salidas


def salidas() -> list[tuple]:
    """Los monitores conectados, según KWin. Lista vacía si no se puede preguntar."""
    try:
        texto = subprocess.run(["kscreen-doctor", "-o"], capture_output=True,
                               text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return _parsear_salidas(texto)


def caja_juego(forzar: bool = False) -> tuple[int, int, int, int] | None:
    """Caja del monitor donde está el juego: (x, y, ancho, alto).

    Se elige el de mayor prioridad (el principal) y, si hay dudas, el más grande. Se
    cachea porque preguntarle a KWin cuesta más que capturar.
    """
    ahora = time.time()
    if not forzar and _CACHE_CAJA["caja"] and ahora - _CACHE_CAJA["ts"] < VIDA_CAJA_S:
        return _CACHE_CAJA["caja"]
    lista = salidas()
    if not lista:
        return None
    # Prioridad primero (1 = principal); a igual prioridad, el monitor más grande.
    elegida = max(lista, key=lambda s: (-s[5] or 0, s[3] * s[4]))
    caja = (elegida[1], elegida[2], elegida[3], elegida[4])
    _CACHE_CAJA.update({"ts": ahora, "caja": caja})
    return caja


class SchedulerVision:
    """Decide qué cuadros se mandan a la cola y con qué motivo."""

    def __init__(self, cola, intervalo_s: float = 20.0, capturador=None,
                 caja_fn=None, modo: str = "tira", cada_tienda: int = 4):
        self.cola = cola
        self.intervalo_s = float(intervalo_s)
        self.capturador = capturador or _capturar
        self.caja_fn = caja_fn or caja_juego
        # "tira": recorte de las zonas del HUD (reloj, oro, ítems) — 10 kB y correcto.
        # "cuadro": el monitor entero a 640 px — más caro y más lento, para la tienda.
        self.modo = modo
        # Cada cuántas lecturas periódicas se mira la tienda. Con una lectura cada 25 s,
        # 4 significa una mirada a la tienda por minuto y medio: suficiente para pillar
        # a Diego comprando sin gastar en balde.
        self.cada_tienda = max(1, int(cada_tienda))
        self._ciclos = 0
        self._ultimo = 0.0
        self._ultimo_tienda = 0.0
        self.enviados = 0
        self.descartes = 0
        # Peso del último JPEG: es el número que decide si la API contesta o se cae
        # (por encima de ~40 kB no vuelve). Sin verlo, depurar esto es a ciegas.
        self.ultimo_peso_kb = None

    def quizas_encolar(self, motivo: str = "periodico", fuerza: bool = False) -> bool:
        """Manda un cuadro si toca. Devuelve True si entró en la cola.

        La tienda va aparte: su propio reloj (no más de una cada `intervalo_s`) para que
        abrir y cerrar la tienda rápido no mande diez cuadros iguales.
        """
        ahora = time.time()
        espera = self.intervalo_s if motivo != "tienda" else max(6.0, self.intervalo_s / 3)
        referencia = self._ultimo_tienda if motivo == "tienda" else self._ultimo
        if not fuerza and ahora - referencia < espera:
            self.descartes += 1
            return False
        cuadro = self.capturador()
        if cuadro is None:
            self.descartes += 1
            return False
        caja = self.caja_fn()
        self._ciclos += 1
        mirar_tienda = (motivo == "tienda"
                        or (self.modo == "tira" and self._ciclos % self.cada_tienda == 0))
        try:
            from ..agente import vision as _vision
            if mirar_tienda and caja is not None:
                from ..agente import vision_tienda as _tienda
                enviado = _tienda.imagen_tienda(cuadro, caja)
                caja_envio = None
                motivo = "tienda"
            elif self.modo == "tira" and caja is not None:
                from ..agente import vision_zonas as _zonas
                enviado = _zonas.tira_hud(cuadro, caja)
                caja_envio = None
            else:
                enviado = cuadro
                caja_envio = caja
            self.ultimo_peso_kb = round(len(_vision.cuadro_a_jpeg(
                _vision.recorte_juego(enviado, caja_envio))) / 1024, 1)
        except Exception:                                 # noqa: BLE001
            enviado, caja_envio, self.ultimo_peso_kb = cuadro, caja, None
        entro = self.cola.encolar(enviado, motivo=motivo, caja=caja_envio)
        if entro:
            self.enviados += 1
            if motivo == "tienda":
                self._ultimo_tienda = ahora
            self._ultimo = ahora
        else:
            self.descartes += 1
        return entro

    def ajustar_tienda(self, abierta: bool):
        """Sube o baja la frecuencia de miradas a la tienda según lo último que se vio.

        Tienda abierta = es donde está el inventario, se mira seguido (cada 2 lecturas).
        Cerrada = no gasta: cada 8. Sin esto, o se gasta de más o se llega tarde.
        """
        self.cada_tienda = 2 if abierta else 8

    def estado(self) -> dict:
        return {"enviados": self.enviados, "descartes": self.descartes,
                "intervalo_s": self.intervalo_s, "caja": self.caja_fn(),
                "ultimo_peso_kb": self.ultimo_peso_kb}




def _capturar():
    """Un cuadro del escritorio (RGBX) o None. Nunca lanza: el bucle no puede caerse."""
    try:
        from . import captura_kwin
        return captura_kwin.capturar_escritorio()
    except Exception:                                     # noqa: BLE001
        return None


def motivo_por_estado(estado_vision: dict | None) -> str:
    """Traduce lo último leído a prioridad de la siguiente captura.

    Si la tienda estaba abierta, se insiste en la tienda: es donde está el inventario y
    lo que el motor necesita para decidir.
    """
    if not estado_vision:
        return "periodico"
    if estado_vision.get("tienda_abierta"):
        return "tienda"
    if estado_vision.get("marcador_abierto"):
        return "marcador"
    return "periodico"
