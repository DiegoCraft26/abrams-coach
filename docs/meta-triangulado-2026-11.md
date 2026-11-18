# Meta de Abrams: lo que dicen las fuentes y lo que dicen nuestras 25 000 partidas

_2026-11-15. Comparación entre lo que se publica en las webs de builds y lo que sale de los
timelines de partidas que tenemos en `data/archivo/`. La pregunta que responde: ¿el camino
que derivamos se parece al que juega la gente o estamos midiendo otra cosa?_

## Cómo se obtuvo cada columna

- **Nuestro dato**: `herramientas/camino_heroe.py --heroe abrams`, derivado de **25 274
  partidas** de Abrams descargadas del archivo público (`/v1/matches/metadata`), con la
  compra de cada ítem y su segundo. Filtra habilidades (el metadata las mezcla con los
  ítems) y cuenta una compra por partida.
- **Las fuentes**: build de deadlocklabs.gg, dodge.gg, blitz.gg, SteamDB y
  deadlockitembuilder, recogidas con `/research` el mismo día. Cada una mide algo distinto
  (builds publicadas, partidas rastreadas, popularidad de build), así que coincidir con
  ellas es más fuerte que coincidir con una sola.

## Apertura (0-10 min)

| Nuestro dato (n=25 274) | Comunidad |
|---|---|
| Close Quarters (20 569) | Close Quarters (SteamDB) · Bullet Resist Shredder (blitz.gg) |
| Melee Lifesteal (19 740) | Melee Lifesteal (dodge.gg, SteamDB) |
| Melee Charge (18 692) | Melee Charge (blitz.gg, SteamDB) · «casi todas las builds lo incluyen» |
| Restorative Shot (15 608) | — (deadlocklabs lo vende en midgame) |
| Stalker (12 018) | Stalker: «casi todas las builds lo incluyen» |
| Extra Regen, Spirit Strike (más abajo) | Extra Regen y Spirit Strike (SteamDB) |

**Coincidencia en los tres primeros puestos.** Lo que no aparece en nuestro top y sí en
las guías: Headshot Booster y Sprint Boots (dodge.gg). Son ítems baratos que se compran
mucho, pero nuestro dato —que cuenta compras reales— los tiene por debajo del top 5.

## Medio juego (10-20 min)

Nuestro: Bullet Resist Shredder (11 950), Hunter's Aura (10 714), Lifestrike (9 372),
Warp Stone (6 646), Stalker (6 021).

Comunidad: Bullet Lifesteal, Mystic Burst, Enduring Speed (dodge.gg) · Hunter's Aura y
Warp Stone aparecen como situacionales en deadlocklabs.gg.

## Tarde (20+ min)

| Nuestro dato | Comunidad |
|---|---|
| Crushing Fists (9 970) | Crushing Fists (blitz.gg, dodge.gg) |
| Superior Duration (6 274 en 20-30) | — (no la citan) |
| Spirit Resilience | Spirit Resilience (deadlocklabs, como reemplazo) |
| Phantom Strike (4 039 en 30+) | Phantom Strike (blitz.gg) |
| Colossus (3 999) | Colossus (blitz.gg, dodge.gg) |
| Spellbreaker (3 388), Witchmail (2 557) | Spellbreaker, Witchmail (blitz.gg, SteamDB) |

**Cinco de los seis ítems de late que cita blitz.gg están en nuestro top**: Crushing
Fists, Phantom Strike, Colossus, Witchmail y Spellbreaker.

## Lo que la comparación deja claro

1. **El método vale**: derivar de compras reales reproduce las builds publicadas en los
   ítems que importan, sin haberlas leído. Eso respalda usar el mismo método para héroes
   sin guía.
2. **Donde no coincidimos, hay una razón**: las webs ordenan por build publicada y
   popularidad; nosotros por compras reales de cada partida. Un ítem puede estar en todas
   las builds y comprarse tarde.
3. **Superior Duration sale en nuestro top y en ninguna guía.** Lo comprobé en vez de
   dejarlo como duda: **10 815 partidas, 54.8 % de winrate contra 51.0 % de base
   (+3.8 pp)**, compra mediana al minuto 25. Sale mejor que Crushing Fists (+3.3 pp), que
   sí está en todas las guías. No es un síntoma de partida perdida: es un ítem que
   funciona y que la comunidad no lista.
4. **Contra Graves y Rat King, la comunidad no da nada concreto** (la subpregunta quedó
   abierta). Ahí nuestro dato es el que manda: 3 718 partidas del par con winrate 38 %.

## Cómo repetir esto

```bash
python3 herramientas/archivo_abrams.py --con-items --atras --desde <id> --objetivo 20000
python3 herramientas/camino_heroe.py --heroe abrams
python3 herramientas/camino_heroe.py --heroe abrams --ganadoras
```

El informe completo de la corrida quedó en
`~/.dsh/research/runs/20261115-190538-6336.md` (parcial: se interrumpió a los 53 000
tokens, con las dos primeras subpreguntas cerradas).
