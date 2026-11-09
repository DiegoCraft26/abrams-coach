"""Construye data/componentes.json: qué ítems componen a cada ítem.

Por qué existe: el motor recomendaba el tier 1 de un ítem que el jugador ya tenía en tier 3
(p. ej. *Sprint Boots* teniendo *Shadow Weave*), porque el catálogo no traía la cadena.
`data/items.json` sí la trae, pero en `component_items` por **class_name** y pesa 2 MB:
cargarlo en cada lectura rompería el presupuesto de RAM.

Así que se resuelve una vez aquí y se guarda un índice de ~10 KB con ids ya resueltos.

Uso:  python3 herramientas/construir_componentes.py
"""
import json
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ITEMS = os.path.join(RAIZ, "data", "items.json")
CATALOGO = os.path.join(RAIZ, "data", "catalogo.json")
SALIDA = os.path.join(RAIZ, "data", "componentes.json")


def main():
    items = json.load(open(ITEMS, encoding="utf-8"))
    cat = json.load(open(CATALOGO, encoding="utf-8"))

    # class_name -> id del ítem
    por_clase = {}
    for iid, it in items.items():
        clase = it.get("class_name")
        if clase:
            por_clase[clase] = str(it.get("id", iid))

    comp = {}
    resueltos = 0
    for iid, it in items.items():
        lista = []
        for clase in it.get("component_items") or []:
            destino = por_clase.get(clase)
            if destino and destino != str(iid):
                lista.append(destino)
        if lista:
            comp[str(it.get("id", iid))] = lista
            resueltos += 1

    json.dump(comp, open(SALIDA, "w", encoding="utf-8"), separators=(",", ":"))
    tam = os.path.getsize(SALIDA)
    print(f"{resueltos} ítems con componentes -> {SALIDA} ({tam/1024:.1f} KB)")

    # comprobación con los casos que encontró QA
    nombre = {v["nombre"]: str(v["id"]) for v in cat.values() if v.get("nombre")}
    for alto, bajo in (("Shadow Weave", "Sprint Boots"),
                       ("Divine Barrier", "Grit"),
                       ("Lifestrike", "Melee Lifesteal"),
                       ("Superior Cooldown", "Compress Cooldown")):
        ia, ib = nombre.get(alto), nombre.get(bajo)
        if not ia or not ib:
            print(f"  ? {alto} / {bajo}: no están en el catálogo")
            continue
        print(f"  {bajo:20s} componente de {alto:20s}: "
              f"{'SÍ' if ib in comp.get(ia, []) else 'NO'}")


if __name__ == "__main__":
    main()
