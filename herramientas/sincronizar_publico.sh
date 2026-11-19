#!/usr/bin/env bash
# Copia el tronco de desarrollo al repo público sin arrastrar datos ni rutas de casa.
#
# Por qué existe. El 2026-11-18 la copia pública llevaba nueve días de retraso y el
# repo compartido para pedir acceso a la API mostraba una v0.2 de un solo héroe. Una
# sincronización a mano además arrastra tres cosas que no deben viajar:
#
#   - `datos/` (523 MB de corpus y lab.db), `grabaciones/` (5 GB), `salida/`, `dist/`,
#     `informes/` y `experimentos/`: material de trabajo, no código;
#   - `data/items.json`: el catálogo se regenera con herramientas/datos/mineria.py;
#   - tu IP de LAN y las rutas /home de tu máquina, que aparecen en comentarios.
#
# Lo que sí se publica de `data/`: lo que ya está versionado, más el pozo por héroe
# (`data/meta/`, `data/meta_abrams.json`, `data/heroes/`), que las pruebas necesitan.
#
# Uso:
#   herramientas/sincronizar_publico.sh            # sincroniza y deja el cambio sin commitear
#   herramientas/sincronizar_publico.sh --dry-run  # sólo enseña qué haría
#
# Nunca hace push: eso se revisa con `git -C <público> diff` primero.
set -euo pipefail

PRIV=${ABRAMS_PRIVADO:-$HOME/Desktop/Chat/abrams-coach}
PUB=${ABRAMS_PUBLICO:-$HOME/Desktop/Chat/abrams-coach-publico}
SECO=0
[ "${1:-}" = "--dry-run" ] && SECO=1

[ -d "$PRIV/.git" ] || { echo "no parece el repo privado: $PRIV" >&2; exit 1; }
[ -d "$PUB/.git" ] || { echo "no parece el repo público: $PUB" >&2; exit 1; }

RSYNC=(rsync -a --delete --exclude='__pycache__/' --exclude='*.pyc' --exclude='*.pyo')
[ "$SECO" = 1 ] && RSYNC+=(--dry-run --itemize-changes)

echo "privado : $PRIV ($(git -C "$PRIV" log -1 --format='%h %ad' --date=short))"
echo "público : $PUB ($(git -C "$PUB" log -1 --format='%h %ad' --date=short))"
echo

# 1. Código, pruebas, documentación y capturas: se copian enteros.
for d in coach herramientas tests docs config capturas; do
    [ -d "$PRIV/$d" ] || continue
    "${RSYNC[@]}" "$PRIV/$d/" "$PUB/$d/"
done

# 2. Archivos de la raíz, uno por uno (un directorio necesita su propia forma).
RAIZ=(arrancar.sh panel_nativo.py run.py instalar.sh requirements.txt pytest.ini LICENSE
      NOTICE README.md README.es.md CHANGELOG.md CALIDAD.md CONTRIBUTING.md POLITICA.md ROADMAP.md
      SECURITY.md)
for f in "${RAIZ[@]}"; do
    [ -e "$PRIV/$f" ] && "${RSYNC[@]}" "$PRIV/$f" "$PUB/$f"
done
if [ -d "$PRIV/.github" ]; then
    "${RSYNC[@]}" "$PRIV/.github/" "$PUB/.github/"
fi
[ -e "$PRIV/.gitignore" ] && cp "$PRIV/.gitignore" "$PUB/.gitignore"

# 3. `data/`: lo ya versionado en el público, más el pozo por héroe.
while IFS= read -r f; do
    [ -e "$PRIV/$f" ] && cp "$PRIV/$f" "$PUB/$f"
done < <(git -C "$PUB" ls-files data)
for f in meta_abrams.json heroes meta; do
    [ -e "$PRIV/data/$f" ] || continue
    if [ "$SECO" = 1 ]; then echo "data/$f (pozo por héroe)"; else cp -r "$PRIV/data/$f" "$PUB/data/$f"; fi
done

# 4. Nada de tu máquina ni de tu red en un repo público.
if [ "$SECO" = 0 ]; then
    grep -rIl "192\.168\.1\.81\|/home/<usuario>" --exclude-dir=.git --exclude-dir=capturas "$PUB" 2>/dev/null |
    while IFS= read -r f; do
        sed -i 's|192\.168\.1\.81|<pc-auxiliar>|g; s|/home/<usuario>|/home/<usuario>|g' "$f"
        echo "saneado: ${f#"$PUB"/}"
    done
fi

echo
if [ "$SECO" = 1 ]; then
    echo "dry-run: no se tocó nada."
else
    echo "cambios sin commitear en el público:"
    git -C "$PUB" status --porcelain | awk '{print "  " $1}' | sort | uniq -c
    echo
    echo "revisa con:  git -C $PUB diff --stat"
    echo "y luego:     git -C $PUB add -A && git -C $PUB commit -m '...' && git -C $PUB push origin main"
fi
