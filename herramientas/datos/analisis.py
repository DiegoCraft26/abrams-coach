#!/usr/bin/env python3
import json, math, os

# Este script vive en herramientas/datos/: la raíz del repo está 3
# niveles arriba, no en el directorio del archivo.
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
D=os.path.join(RAIZ,"data")
items=json.load(open(f"{D}/items.json")); items={int(k):v for k,v in items.items()}
hs=json.load(open(f"{D}/hero-stats.json"))[0]
BASE=hs["wins"]/hs["matches"]
pairs=json.load(open(f"{D}/perm-2.json"))
cnt=json.load(open(f"{D}/counters.json"))

def nombre(i): return items.get(i,{}).get("name",str(i))
def costo(i): return items.get(i,{}).get("cost") or 0
def slot(i): return items.get(i,{}).get("item_slot_type")
def tier(i): return items.get(i,{}).get("item_tier")

def z(w,n,p0=BASE):
    if not n: return 0
    p=w/n; return (p-p0)/math.sqrt(p0*(1-p0)/n)

rows=[]
for r in pairs:
    a,b=r["item_ids"]; n=r["matches"]; w=r["wins"]
    if n<20000: continue
    c=costo(a)+costo(b)
    rows.append(dict(a=a,b=b,n=n,wr=w/n,lift=w/n-BASE,z=z(w,n),cost=c,
                     na=nombre(a),nb=nombre(b)))

print(f"BASELINE Abrams: {BASE*100:.2f}% ({hs['matches']:,} partidas)")
print(f"pares tras filtro n>=20k: {len(rows)}")
print(f"costo total: min={min(r['cost'] for r in rows)} max={max(r['cost'] for r in rows)}")

bandas=[(0,4000,"barato (<=4k)"),(4000,8000,"medio (4-8k)"),(8000,14000,"caro (8-14k)"),(14000,999999,"muy caro (>14k)")]
print("\n### Top parejas por lift DENTRO de cada banda de costo")
for lo,hi,txt in bandas:
    sub=[r for r in rows if lo<=r["cost"]<hi]
    if not sub: continue
    sub.sort(key=lambda r:-r["lift"])
    media=sum(r["lift"] for r in sub)/len(sub)
    print(f"\n-- {txt}: {len(sub)} pares · lift medio {media*100:+.2f}pp")
    for r in sub[:5]:
        print(f"   {r['lift']*100:+6.2f}pp  {r['wr']*100:5.2f}%  z={r['z']:5.1f}  n={r['n']:>9,}  {r['na']} + {r['nb']}")
    print("   peores:")
    for r in sub[-3:]:
        print(f"   {r['lift']*100:+6.2f}pp  {r['wr']*100:5.2f}%  z={r['z']:5.1f}  n={r['n']:>9,}  {r['na']} + {r['nb']}")
