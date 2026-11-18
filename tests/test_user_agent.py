"""Una sola identidad en todas las peticiones salientes.

El 2026-11-18 la app mandaba seis cadenas distintas y una ruta —el watcher del live
en `ui/app.py`— iba sin `User-Agent`, o sea como `Python-urllib/3.x`. Para el que
miraba sus registros eran siete clientes, uno anónimo, y ninguno se podía contactar.

(Ojo: `tests/test_identidad.py` es otra cosa — de dónde sale el id de la partida.)
"""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

from coach import identidad  # noqa: E402

# `aplicacion/version (+contacto)` — lo que cualquier operador espera leer.
FORMATO = re.compile(r"^[a-z0-9][a-z0-9-]*/\d+\.\d+ \(\+\S+\)$")


def test_el_agente_tiene_forma_de_contacto():
    assert FORMATO.match(identidad.AGENTE), identidad.AGENTE
    assert identidad.REPO in identidad.AGENTE


def test_cabeceras_llevan_el_agente_y_respetan_lo_extra():
    c = identidad.cabeceras(Accept="application/json")
    assert c["User-Agent"] == identidad.AGENTE
    assert c["Accept"] == "application/json"
    # No muta la base: llamar dos veces no arrastra lo de la anterior.
    assert "Accept" not in identidad.cabeceras()


def test_ningun_modulo_hardcodea_el_agente():
    """El literal solo puede vivir en `identidad.py`, y solo si es el agente."""
    culpables = []
    for p in sorted((RAIZ / "coach").rglob("*.py")):
        if "__pycache__" in p.parts or p.name == "identidad.py":
            continue
        for n, linea in enumerate(p.read_text(errors="ignore").splitlines(), 1):
            if '"User-Agent": "' in linea:
                culpables.append(f"{p.relative_to(RAIZ).as_posix()}:{n}")
    assert culpables == [], culpables


def test_toda_peticion_saliente_lleva_agente():
    """Si el módulo construye un Request, pone cabecera o usa cabeceras()."""
    sin_agente = []
    for p in sorted((RAIZ / "coach").rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        texto = p.read_text(errors="ignore")
        if "urllib.request.Request(" not in texto:
            continue
        if "User-Agent" not in texto and "identidad.cabeceras" not in texto:
            sin_agente.append(p.relative_to(RAIZ).as_posix())
    assert sin_agente == [], sin_agente
