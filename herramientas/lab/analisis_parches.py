#!/usr/bin/env python3
"""Cuentas del informe PARCHES: serie por parche y picks de Abrams."""
from __future__ import annotations
import json, os, sqlite3, sys, datetime as dt

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.path.join(RAIZ, "datos", "historico.db")
ITEMS = os.path.join(RAIZ, "data", "items.json")
ABRAMS = 6

def nombre_items():
    with open(ITEMS, encoding="utf-8") as f:
        d = json.load(f)
    vals = d.values() if isinstance(d, dict) else d
    return {int(v["id"]): (v.get("name") or str(v["id"])) for v in vals if v.get("id")}

def main():
    con = sqlite3.connect(DB)
    nom = nombre_items()
    print("== global ==")
    print(con.execute("SELECT count(*), min(start_time), max(start_time) FROM partidas").fetchone())
    f = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
    tot, a, b = con.execute("SELECT count(*), min(start_time), max(start_time) FROM partidas").fetchone()
    print("partidas %d  de %s a %s UTC" % (tot, f(a), f(b)))
    print("jugadores", con.execute("SELECT count(*) FROM jugadores").fetchone()[0])
    print("compras", con.execute("SELECT count(*) FROM compras").fetchone()[0])
    print("modos:", con.execute("SELECT game_mode, match_mode, count(*) FROM partidas "
                                "GROUP BY 1,2 ORDER BY 3 DESC").fetchall())
    print()
    print("== por parche ==")
    filas = con.execute("""
        SELECT p.parche, count(*) n,
               min(p.start_time), max(p.start_time),
               sum(CASE WHEN p.ganador IS NULL THEN 1 ELSE 0 END) sin_ganador,
               (SELECT count(*) FROM jugadores j JOIN partidas q ON q.match_id=j.match_id
                 WHERE q.parche=p.parche AND j.hero_id=?) abrams
        FROM partidas p GROUP BY p.parche ORDER BY 3""", (ABRAMS,)).fetchall()
    print("%-22s %5s %-16s %-16s %4s %5s" % ("parche", "n", "desde", "hasta", "s/g", "Abr"))
    for pa, n, x, y, sg, ab in filas:
        print("%-22s %5d %s %s %4d %5d" % (pa, n,
              dt.datetime.fromtimestamp(x, dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
              dt.datetime.fromtimestamp(y, dt.timezone.utc).strftime("%Y-%m-%d %H:%M"), sg, ab))
    print()
    print("== parche(titulo) vs parche_feed(pub_date) ==")
    for pa, pf, n in con.execute("SELECT parche, parche_feed, count(*) FROM partidas "
                                 "GROUP BY 1,2 ORDER BY min(start_time)").fetchall():
        print("  %-22s <- feed %s  n=%d" % (pa, pf, n))
    print()
    print("== top 5 items de Abrams por parche (n = partidas donde Abra lo compro) ==")
    parches = [r[0] for r in filas]
    for pa in parches:
        base = con.execute("SELECT count(*) FROM jugadores j JOIN partidas p USING(match_id) "
                           "WHERE j.hero_id=? AND p.parche=?", (ABRAMS, pa)).fetchone()[0]
        top = con.execute("""
            SELECT c.item_id, count(DISTINCT c.match_id) n
            FROM compras c JOIN jugadores j ON j.match_id=c.match_id
                             AND j.player_slot=c.player_slot
            JOIN partidas p ON p.match_id=c.match_id
            WHERE j.hero_id=? AND p.parche=?
            GROUP BY c.item_id ORDER BY n DESC, c.item_id LIMIT 5""", (ABRAMS, pa)).fetchall()
        txt = ", ".join("%s (%d)" % (nom.get(i, i), n) for i, n in top) or "(sin datos)"
        print("%-22s n_abra=%3d | %s" % (pa, base, txt))
    print()
    print("== partidas de Abrams por parche (heroe en la partida) ==")
    for pa in parches:
        q = con.execute("""SELECT count(*) FROM jugadores j JOIN partidas p USING(match_id)
                           WHERE j.hero_id=? AND p.parche=?""", (ABRAMS, pa)).fetchone()[0]
        print("  %-22s %d" % (pa, q))
    return 0

if __name__ == "__main__":
    sys.exit(main())
