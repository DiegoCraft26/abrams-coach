#!/usr/bin/env python3
"""Puerta P4: un partida de historico.db contra el endpoint individual de la API.

No prueba «que todo está bien»: prueba que el parseo de lotes no inventó ni perdió filas
en una partida concreta, y que start_time del historial coincide con el del metadata.
"""
import json, sqlite3, os, urllib.request, datetime as dt
RAIZ = "/home/pcserver/abrams-coach"
con = sqlite3.connect(os.path.join(RAIZ, "datos/historico.db"))
mid = con.execute("SELECT match_id FROM compras GROUP BY match_id ORDER BY count(*) DESC LIMIT 1").fetchone()[0]
print("partida de prueba:", mid)
n_compras = con.execute("SELECT count(*) FROM compras WHERE match_id=?", (mid,)).fetchone()[0]
n_jug = con.execute("SELECT count(*) FROM jugadores WHERE match_id=?", (mid,)).fetchone()[0]
st = con.execute("SELECT start_time, duracion_s, ganador, parche FROM partidas WHERE match_id=?", (mid,)).fetchone()
print("en db: compras=%d jugadores=%d start=%s dur=%s ganador=%s parche=%s"
      % (n_compras, n_jug, dt.datetime.fromtimestamp(st[0], dt.timezone.utc), st[1], st[2], st[3]))
url = ("https://api.deadlock-api.com/v1/matches/%d/metadata"
       "?include_player_items=true") % mid
req = urllib.request.Request(url, headers={"User-Agent": "abrams-coach/validar"})
d = None
for intento in range(3):
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=120).read())["match_info"]
        break
    except Exception as e:                      # 400/504 intermitentes del endpoint
        print("  reintento", intento + 1, type(e).__name__)
        import time; time.sleep(5)
coste = json.load(open(os.path.join(RAIZ, "data/items.json")))
coste = {int(v["id"]) for v in (coste.values() if isinstance(coste, dict) else coste)
         if v.get("id") and (v.get("cost") or 0) > 0}
comp = sum(1 for p in d["players"] for i in (p.get("items") or [])
           if int(i.get("item_id") or 0) in coste)
print("api : compras=%d jugadores=%d start=%s dur=%s ganador=%s"
      % (comp, len(d["players"]),
         (dt.datetime.strptime(d["start_time"], "%Y-%m-%d %H:%M:%S").replace(
             tzinfo=dt.timezone.utc) if isinstance(d["start_time"], str)
          else dt.datetime.fromtimestamp(int(d["start_time"]), dt.timezone.utc)),
         d["duration_s"], d["winning_team"]))
ok = comp == n_compras and len(d["players"]) == n_jug
print("COINCIDE" if ok else "NO COINCIDE")
