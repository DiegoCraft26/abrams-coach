# Contribuir a Abrams Coach

Gracias por tomarte el tiempo. El proyecto es pequeño y las reglas son cortas.

## Antes de abrir un PR

- Corre la suite completa: `python3 -m pytest -q`. Tiene que quedar en verde (las
  pruebas que necesitan capturas reales se saltan solas y lo dicen).
- Compila todo: `python3 -m compileall -q coach herramientas tests run.py panel_nativo.py`.
- Si tocas el motor, mide antes y después con
  `python3 herramientas/evaluar_motor.py --partidas 60` y pega los números en el PR.
- Si tocas la UI, adjunta una captura de los cuatro tamaños:
  `python3 herramientas/capturar_ui.py`.

## Reglas del proyecto

1. **Español** en código, comentarios, mensajes y documentación.
2. **Nada de memoria del juego, inyección, overlays ni macros.** Solo píxeles de la
   pantalla y APIs públicas. Un PR que cruce esa línea se cierra.
3. **Nada de datos personales ni arte de Valve** en el repo: ni cuentas, ni match_id
   propios, ni capturas de escritorio, ni iconos. Todo eso se genera o se descarga en
   la máquina de quien usa la app.
4. **Nada de dependencias nuevas** sin justificarlo: el objetivo es que instalar sea
   aburrido.
5. Los comentarios explican **por qué**, no qué. Si un número está medido, di cómo se
   midió.

## Cómo probar sin el juego

```bash
python3 run.py --fuente simulado --acelerar 0    # estado congelado para la UI
python3 -m pytest -q
python3 herramientas/capturar_ui.py --tamanos 960x1080,1280x720
```

Para la lectura real hacen falta capturas propias en `verdad/`; el formato está en
`tests/test_lectura.py`.

## Estilo

- 4 espacios, líneas de 88–100 columnas, sin imports sin usar.
- Los módulos de `coach/` no abren ventanas; la UI vive en `coach/ui/`.
- Un cambio por PR. Los refactors grandes, en su propio PR y con la suite en verde.

## Issues

Incluye sistema (KDE/Wayland o X11), resolución, si había broadcast y qué decía el pie
de latencia. Sin eso no se puede reproducir.
