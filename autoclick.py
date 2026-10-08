#!/usr/bin/env python3
"""Autoclick: al presionar F6 hace N clicks izquierdos en el tiempo indicado.

Al iniciar pregunta cuántos clicks y en cuánto tiempo (ms o s).
Funciona en Wayland y X11: lee el teclado vía evdev (grupo `input`) y emite
los clicks con un mouse virtual propio vía /dev/uinput.
Ctrl+C para salir.
"""
import re
import selectors
import time

import evdev
from evdev import UInput, ecodes as e

DEFAULT_CLICKS = 100
DEFAULT_DURATION = 0.5
MIN_INTERVAL = 0.002  # por debajo de 2 ms por click se pierden clicks
HOTKEY = e.KEY_F6


def parse_duration(text):
    """'500ms', '500 ms', '0,5s', '2 s', '1.5' (sin unidad = segundos) -> segundos."""
    m = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*(ms|s|seg)?\s*", text.lower())
    if not m:
        raise ValueError
    value = float(m.group(1).replace(",", "."))
    if m.group(2) == "ms":
        value /= 1000
    if value <= 0:
        raise ValueError
    return value


def ask(prompt, default, parse):
    while True:
        text = input(f"{prompt} [{default}]: ").strip()
        if not text:
            return parse(str(default))
        try:
            return parse(text)
        except ValueError:
            print("  Valor inválido, probá de nuevo.")


def positive_int(text):
    value = int(text)
    if value <= 0:
        raise ValueError
    return value


def ask_config():
    print("Configuración (Enter para usar el valor por defecto)")
    while True:
        clicks = ask("¿Cuántos clicks?", DEFAULT_CLICKS, positive_int)
        duration = ask("¿En cuánto tiempo? (ej: 500ms, 0,5s, 2s)",
                       f"{DEFAULT_DURATION}s", parse_duration)
        if duration / clicks >= MIN_INTERVAL:
            return clicks, duration
        max_clicks = int(duration / MIN_INTERVAL)
        print(f"  Demasiado rápido: en {duration:g} s el máximo es {max_clicks} clicks "
              f"(1 cada {MIN_INTERVAL * 1000:g} ms).")


def keyboards():
    devs = []
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        if "ydotoold" in dev.name or "autoclick" in dev.name:
            continue
        if HOTKEY in dev.capabilities().get(e.EV_KEY, []):
            devs.append(dev)
    return devs


def burst(mouse, clicks, duration):
    interval = duration / clicks
    half = interval / 2  # mitad apretado, mitad suelto
    start = time.perf_counter()
    for i in range(clicks):
        mouse.write(e.EV_KEY, e.BTN_LEFT, 1)
        mouse.syn()
        time.sleep(half)
        mouse.write(e.EV_KEY, e.BTN_LEFT, 0)
        mouse.syn()
        # Se agenda contra el reloj absoluto para no acumular desfase.
        delay = start + (i + 1) * interval - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
    return time.perf_counter() - start


def main():
    try:
        clicks, duration = ask_config()
    except (KeyboardInterrupt, EOFError):
        print()
        return

    mouse = UInput(
        {e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT], e.EV_REL: [e.REL_X, e.REL_Y]},
        name="autoclick",
    )
    time.sleep(0.5)  # el compositor necesita detectar el dispositivo nuevo

    sel = selectors.DefaultSelector()
    devs = keyboards()
    for dev in devs:
        sel.register(dev, selectors.EVENT_READ)
    print(f"F6 -> {clicks} clicks en {duration:g} s "
          f"(1 cada {duration / clicks * 1000:g} ms). "
          f"Escuchando en {len(devs)} dispositivos. Ctrl+C para salir.")

    try:
        while True:
            for key, _ in sel.select():
                for ev in key.fileobj.read():
                    if ev.type == e.EV_KEY and ev.code == HOTKEY and ev.value == 1:
                        took = burst(mouse, clicks, duration)
                        print(f"{clicks} clicks en {took:.3f} s")
                        # Descarta F6 que se haya acumulado durante la ráfaga.
                        for d in devs:
                            try:
                                list(d.read())
                            except BlockingIOError:
                                pass
    except KeyboardInterrupt:
        pass
    finally:
        mouse.close()


if __name__ == "__main__":
    main()
