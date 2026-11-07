"""Basura de entrada: el motor nunca debe caerse ni tardar."""
import os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from coach.motor_api import Motor

def main():
    random.seed(3)
    fallos = 0
    m = Motor()
    casos = [
        {},
        {"t": -5},
        {"t": 99999, "yo": {"almas": 10**9}},
        {"t": 1200, "yo": {"items": ["no-existe", "123", None]}},
        {"t": 1200, "enemigos": [{} for _ in range(12)]},
        {"t": 1200, "yo": {"almas": "muchas"}},
        {"t": 1200, "enemigos": "no es lista"},
        {"t": 1200, "yo": {"almas": 5000}, "slots": {"weapon": 0, "vitality": 0, "spirit": 0}},
    ]

    fallos = 0
    for c in casos:
        try:
            t0 = time.perf_counter()
            m.analizar_dict(c)
            ms = (time.perf_counter()-t0)*1000
            if ms > 200:
                print(f"  lento {ms:.0f} ms con {c}")
                fallos += 1
        except Exception as e:
            print(f"  EXCEPCIÓN con {c}: {type(e).__name__}: {e}")
            fallos += 1

    for _ in range(300):
        d = {"t": random.uniform(0, 4000),
             "yo": {"heroe": "Abrams", "almas": random.choice([0, 500, 3000, 30000, None]),
                    "items": random.sample(list(m.conoc["items"]), k=random.randint(0, 6))},
             "enemigos": [{"heroe": random.choice(["haze","lash","seven","viscous",None]),
                           "almas": random.choice([None, 1000, 5000])} for _ in range(random.randint(0,5))]}
        try:
            m.analizar_dict(d)
        except Exception as e:
            print("  EXCEPCIÓN aleatoria:", type(e).__name__, e, d)
            fallos += 1
            break

    print("robustez:", "OK" if fallos == 0 else f"{fallos} problemas")
    return fallos


def test_suite():
    """Entrada para `pytest -q`: la suite devuelve el número de fallos."""
    assert main() == 0

if __name__ == "__main__":
    sys.exit(main())
