# autoclick

Autoclicker para Linux: al presionar **F6** hace una ráfaga de clicks izquierdos
en la posición actual del mouse. La cantidad de clicks y el tiempo total se
eligen al iniciar.

Funciona en **Wayland** y **X11**: lee el teclado con `evdev` y genera los clicks
con un mouse virtual propio (`/dev/uinput`), sin `xdotool` ni `ydotool`.

## Requisitos

- Python 3 y `python3-evdev`:
  ```sh
  sudo apt install python3-evdev
  ```
- Tu usuario en el grupo `input` y `/dev/uinput` con permisos para ese grupo:
  ```sh
  groups                  # debe incluir "input"
  ls -l /dev/uinput       # debe ser crw-rw---- root input
  ```
  Si falta el grupo: `sudo usermod -aG input $USER` y cerrá sesión.

## Cómo ejecutar

```sh
cd ~/Github/autoclick
python3 autoclick.py
```

Al iniciar pregunta (Enter usa el valor por defecto):

```
Configuración (Enter para usar el valor por defecto)
¿Cuántos clicks? [100]: 50
¿En cuánto tiempo? (ej: 500ms, 0,5s, 2s) [0.5s]: 300ms
F6 -> 50 clicks en 0.3 s (1 cada 6 ms). Escuchando en 17 dispositivos. Ctrl+C para salir.
```

Formatos de tiempo aceptados: `500ms`, `500 ms`, `0,5s`, `0.5s`, `2s`.
Un número sin unidad se toma como segundos.

Después:

1. Dejá la terminal abierta (podés minimizarla).
2. Poné el mouse donde querés los clicks.
3. Presioná **F6**.
4. **Ctrl+C** en la terminal para salir.

## Notas

- El mínimo es 2 ms por click; si pedís más clicks de los que entran en ese
  tiempo, vuelve a preguntar.
- F6 también llega a la aplicación enfocada (el teclado no se bloquea).
- Las pulsaciones de F6 durante una ráfaga se ignoran.
- A intervalos muy cortos algunas apps o juegos no registran todos los clicks.
