"""Modelo de estado de una partida de Deadlock, tal como lo lee la app."""
from dataclasses import dataclass, field, asdict
from typing import Optional

SLOTS_POR_CATEGORIA = {"weapon": 4, "vitality": 4, "spirit": 4}


@dataclass
class Jugador:
    heroe: Optional[str] = None
    almas: Optional[int] = None
    items: list = field(default_factory=list)       # ids como str
    bajas: int = 0
    muertes: int = 0
    asistencias: int = 0

    @property
    def kda(self):
        return (self.bajas + self.asistencias) / max(1, self.muertes)


@dataclass
class Estado:
    t: float = 0.0                     # segundos de partida
    yo: Jugador = field(default_factory=Jugador)
    aliados: list = field(default_factory=list)
    enemigos: list = field(default_factory=list)
    slots: dict = field(default_factory=lambda: dict(SLOTS_POR_CATEGORIA))
    confianza: float = 1.0             # 0..1, cuánto se cree la lectura
    fuente: str = "manual"             # manual | ocr
    notas: list = field(default_factory=list)

    def a_dict(self):
        return asdict(self)

    @staticmethod
    def desde_dict(d):
        if not isinstance(d, dict):
            d = {}
        e = Estado(t=_num(d.get("t"), 0.0) or 0.0,
                   confianza=_num(d.get("confianza"), 1.0),
                   fuente=str(d.get("fuente", "manual")),
                   notas=[str(x) for x in _lista(d.get("notas"))])
        e.yo = _jugador(d.get("yo"))
        e.aliados = [_jugador(x) for x in _lista(d.get("aliados")) if isinstance(x, dict)]
        e.enemigos = [_jugador(x) for x in _lista(d.get("enemigos")) if isinstance(x, dict)]
        slots = d.get("slots")
        if isinstance(slots, dict):
            e.slots = {k: int(_num(v, 0) or 0) for k, v in slots.items()}
        return e


def _num(v, defecto=None):
    try:
        if isinstance(v, bool):
            return defecto
        return float(v) if v is not None else defecto
    except (TypeError, ValueError):
        return defecto


def _lista(v):
    return v if isinstance(v, list) else []


def _jugador(x):
    if not isinstance(x, dict):
        return Jugador()
    items = [str(i) for i in _lista(x.get("items")) if i is not None]
    return Jugador(
        heroe=str(x["heroe"]) if x.get("heroe") else None,
        almas=int(_num(x.get("almas"))) if _num(x.get("almas")) is not None else None,
        items=items,
        bajas=int(_num(x.get("bajas"), 0) or 0),
        muertes=int(_num(x.get("muertes"), 0) or 0),
        asistencias=int(_num(x.get("asistencias"), 0) or 0),
    )


def validar(e: Estado):
    """Reglas de cordura. Devuelve lista de problemas detectados."""
    problemas = []
    # rangos de una partida real de Deadlock
    if e.t is not None and (e.t < 0 or e.t > 5400):
        problemas.append("tiempo fuera de una partida")
    if e.yo.almas is not None:
        if e.yo.almas < 0 or e.yo.almas > 200000:
            problemas.append("almas fuera de rango")
        # las almas crecen con el tiempo: un valor imposible delata mala lectura
        minuto = (e.t or 0)/60
        if minuto >= 3 and e.yo.almas > 0:
            if e.yo.almas < minuto*80:
                problemas.append("almas demasiado bajas para el minuto")
            elif e.yo.almas > 4000*minuto + 4000:
                problemas.append("almas demasiado altas para el minuto")
    if e.t < 0:
        problemas.append("tiempo negativo")
    if e.yo.almas is not None and e.yo.almas < 0:
        problemas.append("almas negativas")
    if len(e.enemigos) > 6:
        problemas.append("más de 6 enemigos")
    if len(set(e.yo.items)) != len(e.yo.items):
        problemas.append("ítems duplicados en el inventario")
    return problemas
