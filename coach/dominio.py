"""Modelo de dominio tipado para el panel de Deadlock (Abrams).

Dataclasses que cruzan capas en lugar de dicts sueltos. Cada una sabe
convertirse desde/hacia dict de forma tolerante, para que una lectura rota
nunca tumbe el panel.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# ------------------------------------------------------------------ helpers
def _num(v, defecto=None):
    try:
        if isinstance(v, bool):
            return defecto
        if v is None:
            return defecto
        return float(v)
    except (TypeError, ValueError):
        return defecto


def _lista(v):
    return v if isinstance(v, list) else []


def _str_o_none(v):
    if v is None:
        return None
    s = str(v).strip()
    return s if s != "" else None


def _campo(d, *claves, defecto=None):
    """Devuelve el primer valor presente entre varias claves (tolerancia de nombres)."""
    if not isinstance(d, dict):
        return defecto
    for c in claves:
        if c in d:
            return d[c]
    return defecto


def _jugador(x):
    if not isinstance(x, dict):
        return Jugador()
    items = [str(i) for i in _lista(x.get("items")) if i is not None]
    almas = _num(x.get("almas"))
    return Jugador(
        heroe=_str_o_none(x.get("heroe")),
        almas=int(almas) if almas is not None else None,
        items=items,
        bajas=int(_num(x.get("bajas"), 0) or 0),
        muertes=int(_num(x.get("muertes"), 0) or 0),
        asistencias=int(_num(x.get("asistencias"), 0) or 0),
    )


# ------------------------------------------------------------------ dataclasses
@dataclass
class Jugador:
    heroe: Optional[str] = None
    almas: Optional[int] = None
    items: list = field(default_factory=list)          # ids como str
    bajas: int = 0
    muertes: int = 0
    asistencias: int = 0

    @property
    def kda(self):
        return (self.bajas + self.asistencias) / max(1, self.muertes)

    @classmethod
    def desde_dict(cls, d):
        if not isinstance(d, dict):
            d = {}
        almas = _num(d.get("almas"))
        return cls(
            heroe=_str_o_none(d.get("heroe")),
            almas=int(almas) if almas is not None else None,
            items=[str(i) for i in _lista(d.get("items")) if i is not None],
            bajas=int(_num(d.get("bajas"), 0) or 0),
            muertes=int(_num(d.get("muertes"), 0) or 0),
            asistencias=int(_num(d.get("asistencias"), 0) or 0),
        )

    def a_dict(self):
        return asdict(self)


@dataclass
class Item:
    id: Optional[str] = None
    nombre: Optional[str] = None
    slot: Optional[str] = None
    costo: Optional[int] = None
    tier: Optional[int] = None
    n: int = 0
    winrate: Optional[float] = None
    lift: Optional[float] = None
    lift_residual: Optional[float] = None
    min_compra: Optional[float] = None
    min_venta: Optional[float] = None
    tasa_venta: Optional[float] = None
    veces_vendido: Optional[int] = None
    icono: Optional[str] = None

    @classmethod
    def desde_dict(cls, d):
        if not isinstance(d, dict):
            d = {}
        costo = _num(_campo(d, "costo", "cost", "precio"))
        tier = _num(_campo(d, "tier", "nivel"))
        n = _num(_campo(d, "n", "muestras", "cantidad"), 0)
        winrate = _num(_campo(d, "winrate", "wr"))
        lift = _num(_campo(d, "lift"))
        lift_residual = _num(_campo(d, "lift_residual", "residual"))
        min_compra = _num(_campo(d, "min_compra", "minuto_compra"))
        min_venta = _num(_campo(d, "min_venta", "minuto_venta"))
        tasa_venta = _num(_campo(d, "tasa_venta"))
        veces = _num(_campo(d, "veces_vendido", "veces"))
        return cls(
            id=_str_o_none(_campo(d, "id", "item_id", "id_item")),
            nombre=_str_o_none(_campo(d, "nombre", "name", "titulo")),
            slot=_str_o_none(_campo(d, "slot", "categoria", "tipo")),
            costo=int(costo) if costo is not None else None,
            tier=int(tier) if tier is not None else None,
            n=int(n) if n is not None else 0,
            winrate=winrate,
            lift=lift,
            lift_residual=lift_residual,
            min_compra=min_compra,
            min_venta=min_venta,
            tasa_venta=tasa_venta,
            veces_vendido=int(veces) if veces is not None else None,
            icono=_str_o_none(_campo(d, "icono", "icon")),
        )

    def a_dict(self):
        return asdict(self)


@dataclass
class Recomendacion:
    id: Optional[str] = None
    nombre: Optional[str] = None
    costo: Optional[int] = None
    slot: Optional[str] = None
    score: Optional[float] = None
    residual: Optional[float] = None
    n: int = 0
    razones: list = field(default_factory=list)
    mejora: Any = None
    min_compra: Optional[float] = None
    fase: Optional[float] = None
    requiere_venta: bool = False
    icono: Optional[str] = None

    @classmethod
    def desde_dict(cls, d):
        if not isinstance(d, dict):
            d = {}
        costo = _num(_campo(d, "costo", "cost", "precio"))
        score = _num(_campo(d, "score", "puntuacion"))
        residual = _num(_campo(d, "residual"))
        n = _num(_campo(d, "n", "muestras"), 0)
        min_compra = _num(_campo(d, "min_compra"))
        fase = _num(_campo(d, "fase"))
        req = _campo(d, "requiere_venta", "requiereVenta")
        if not isinstance(req, bool):
            req = bool(req) if req is not None else False
        return cls(
            id=_str_o_none(_campo(d, "id", "item_id")),
            nombre=_str_o_none(_campo(d, "nombre", "name")),
            costo=int(costo) if costo is not None else None,
            slot=_str_o_none(_campo(d, "slot")),
            score=score,
            residual=residual,
            n=int(n) if n is not None else 0,
            razones=[str(x) for x in _lista(d.get("razones"))],
            mejora=d.get("mejora") if "mejora" in d else _campo(d, "mejora"),
            min_compra=min_compra,
            fase=fase,
            requiere_venta=bool(req),
            icono=_str_o_none(_campo(d, "icono", "icon")),
        )

    def a_dict(self):
        return asdict(self)


@dataclass
class Evento:
    tipo: Optional[str] = None
    t: Optional[float] = None
    datos: Any = None
    fuente: Optional[str] = None
    ts: Optional[float] = None
    notas: list = field(default_factory=list)

    @classmethod
    def desde_dict(cls, d):
        if not isinstance(d, dict):
            d = {}
        t = _num(d.get("t"))
        ts = _num(d.get("ts"))
        return cls(
            tipo=_str_o_none(d.get("tipo", d.get("type"))),
            t=t,
            datos=d.get("datos", d.get("data")) if ("datos" in d or "data" in d) else None,
            fuente=_str_o_none(d.get("fuente", d.get("source"))),
            ts=ts,
            notas=[str(x) for x in _lista(d.get("notas"))],
        )

    def a_dict(self):
        return asdict(self)


@dataclass
class Partida:
    match_id: Optional[int] = None
    inicio: Optional[str] = None
    fin: Optional[str] = None
    duracion_s: Optional[int] = None
    heroe: Optional[str] = None
    resultado: Optional[str] = None
    video: Optional[str] = None
    fuente: Optional[str] = None
    confianza: float = 1.0
    t: float = 0.0
    yo: Jugador = field(default_factory=Jugador)
    aliados: list = field(default_factory=list)
    enemigos: list = field(default_factory=list)
    notas: list = field(default_factory=list)

    @classmethod
    def desde_dict(cls, d):
        if not isinstance(d, dict):
            d = {}
        match_id = _num(d.get("match_id", d.get("matchId")))
        duracion = _num(d.get("duracion_s", d.get("duracion")))
        confianza = _num(d.get("confianza"), 1.0)
        t = _num(d.get("t"), 0.0)
        return cls(
            match_id=int(match_id) if match_id is not None else None,
            inicio=_str_o_none(d.get("inicio", d.get("start"))),
            fin=_str_o_none(d.get("fin", d.get("end"))),
            duracion_s=int(duracion) if duracion is not None else None,
            heroe=_str_o_none(d.get("heroe")),
            resultado=_str_o_none(d.get("resultado", d.get("result"))),
            video=_str_o_none(d.get("video")),
            fuente=(_str_o_none(d.get("fuente", d.get("source"))) or "manual"),
            confianza=confianza if confianza is not None else 1.0,
            t=t if t is not None else 0.0,
            yo=_jugador(d.get("yo")),
            aliados=[_jugador(x) for x in _lista(d.get("aliados")) if isinstance(x, dict)],
            enemigos=[_jugador(x) for x in _lista(d.get("enemigos")) if isinstance(x, dict)],
            notas=[str(x) for x in _lista(d.get("notas"))],
        )

    def a_dict(self):
        return asdict(self)


@dataclass
class EstadoPartida:
    t: float = 0.0
    yo: Jugador = field(default_factory=Jugador)
    aliados: list = field(default_factory=list)
    enemigos: list = field(default_factory=list)
    fuente: str = "manual"
    confianza: float = 1.0
    notas: list = field(default_factory=list)
    slots: dict = field(default_factory=lambda: {"weapon": 4, "vitality": 4, "spirit": 4})

    @classmethod
    def desde_dict(cls, d):
        if not isinstance(d, dict):
            d = {}
        t = _num(d.get("t"), 0.0)
        confianza = _num(d.get("confianza"), 1.0)
        fuente = d.get("fuente")
        fuente = str(fuente) if fuente is not None else "manual"
        slots = d.get("slots")
        if isinstance(slots, dict):
            slots_val = {k: int(_num(v, 0) or 0) for k, v in slots.items()}
        else:
            slots_val = {"weapon": 4, "vitality": 4, "spirit": 4}
        return cls(
            t=t if t is not None else 0.0,
            yo=_jugador(d.get("yo")),
            aliados=[_jugador(x) for x in _lista(d.get("aliados")) if isinstance(x, dict)],
            enemigos=[_jugador(x) for x in _lista(d.get("enemigos")) if isinstance(x, dict)],
            fuente=fuente,
            confianza=confianza if confianza is not None else 1.0,
            notas=[str(x) for x in _lista(d.get("notas"))],
            slots=slots_val,
        )

    def a_dict(self):
        return asdict(self)
