# Seguridad

## Qué reportar

- Que la app lea o escriba fuera de su carpeta sin que se lo pidas.
- Que las capturas de pantalla se suban a algún sitio.
- Que se ejecute código venido de la API o de un archivo de partida.
- Cualquier cosa que toque el proceso del juego (no debe pasar nunca).

## Cómo reportarlo

Usa **Security → Report a vulnerability** en GitHub, no un issue público. Incluye
versión, sistema y pasos para reproducirlo. Respondo en lo que pueda; esto es un
proyecto personal, sin SLA.

## Alcance

La app lee píxeles de la pantalla y llama a APIs públicas. No hay servidor propio, no
hay telemetría y no se guardan credenciales. `~/.dsh/.credentials.yaml` solo lo usa el
generador de informes opcional y nunca se sube.
