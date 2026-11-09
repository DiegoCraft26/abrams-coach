# Cambios

## v0.2 — 2026-11-09

- Panel nativo GTK4 en cuatro tamaños, con colocación automática en el monitor secundario.
- Modo pantalla: con el juego en ranked y sin broadcast, lee el reloj del HUD y publica
  el plan de apertura desde el minuto 0.
- El id de partida se lee del HUD, así que el broadcast se puede enganchar **sin cuenta**.
- Si no hay cuenta, `--mi-heroe` identifica tu columna cuando el héroe es único.
- Lectura del HUD a 7.9 Hz con captura KWin compartida; sin tirones en partida.
- Motor con componentes, frescura de datos y filtro por oro; 4.5 ms por decisión.
- Build como camino apertura → core → spike, con estado COMPRAR/AHORRAR/VENDER, ETA y
  componentes del objetivo. Baja de 4–5 a 1.4 ítems de 800 en los primeros 10 minutos.
- El objetivo ya no retrocede a la apertura a los 30 minutos ni ignora los upgrades de
  lo que llevas; la rama cambia con la composición enemiga cuando los datos la apoyan.
- Ventas con nombre y slot; huecos de inventario por categoría.
- Captura compartida a 2 Hz (antes 5.5) y menos trabajo de OCR por segundo.
- Bonus de categoría de 4,800: progreso visible y empujón suave, sin volver el build
  genérico.
- Base SQLite con archivado idempotente e informe de partida.
- Repo público: fuera datos personales, cuentas y arte de Valve; iconos en runtime.
- CI real: GTK bajo Xvfb, suite completa, motor sobre muestra anonimizada.

## v0.1 — 2026-11-07

- Primera versión: lector de marcador, motor con invariantes, modo en vivo y panel demo.
