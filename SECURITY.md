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
hay telemetría y no se guardan credenciales. `~/.config/abrams-coach/credenciales.yaml` solo lo usa el
generador de informes opcional y nunca se sube.

## Lo que no se publica (y cómo se comprueba)

| Dato | Dónde vive | Cómo se mantiene fuera |
|---|---|---|
| Cuenta de Steam (`account_id`) | `.cuenta` | ignorada por git **y excluida del paquete** |
| Base local (`lab.db`, `historico.db`) | `datos/` | ignorada y excluida |
| Notas y salida de uso | `salida/` | ignorada y excluida |
| Informes con partidas propias | `informes/` | ignorados salvo los de laboratorio |
| Clave de la API | `~/.config/abrams-coach/api_key` | fuera del repo por diseño |

**Puerta automática:** `herramientas/empaquetar.sh` borra el tarball y falla si encuentra
`.cuenta`, `datos/`, `salida/` o `.git/` dentro. Se añadió el 2026-11-18, cuando un paquete
de prueba incluía el account_id sin que nadie lo notara: `tar` no lee `.gitignore`.

Las pruebas no llevan datos personales: los ids de cuenta que aparecen son ficticios
(se sustituyó el real por `123456789` el mismo día).
