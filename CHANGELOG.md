# Cambios

## v0.2 — 2026-11-09

- Panel nativo GTK4 en cuatro tamaños, con colocación automática en el monitor secundario.
- Modo pantalla: con el juego en ranked y sin broadcast, lee el reloj del HUD y publica
  el plan de apertura desde el minuto 0.
- El id de partida se lee del HUD, así que el broadcast se puede enganchar **sin cuenta**.
- Si no hay cuenta, `--mi-heroe` identifica tu columna cuando el héroe es único.
- Lectura del HUD a 7.9 Hz con captura KWin compartida; sin tirones en partida.
- Motor con componentes, frescura de datos y filtro por oro; 4.5 ms por decisión.
- Base SQLite con archivado idempotente e informe de partida.
- Repo público: fuera datos personales, cuentas y arte de Valve; iconos en runtime.
- CI real: GTK bajo Xvfb, suite completa, motor sobre muestra anonimizada.

## v0.1 — 2026-11-07

- Primera versión: lector de marcador, motor con invariantes, modo en vivo y panel demo.
