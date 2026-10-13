#!/usr/bin/env python3
"""Autoclick: al presionar F6 hace N clicks izquierdos en el tiempo indicado.

También se dispara con Ctrl+R (macro del botón 6 del Naga X).
Al iniciar pregunta cuántos clicks y en cuánto tiempo (ms o s).
También emula una rueda libre (F7 la activa/desactiva): si soltás la rueda
girando rápido, el scroll sigue por inercia y frena solo.
Funciona en Wayland y X11: lee teclado y mouse vía evdev (grupo `input`) y
emite los clicks y el scroll con un mouse virtual propio vía /dev/uinput.
Ctrl+C para salir.
"""
import math
import re
import selectors
import time
from collections import deque

import evdev
from evdev import UInput, ecodes as e

DEFAULT_CLICKS = 250
DEFAULT_DURATION = 0.5
MIN_INTERVAL = 0.002  # por debajo de 2 ms por click se pierden clicks
HOTKEY = e.KEY_F6
CHORD_KEY = e.KEY_R  # Ctrl+R también dispara la ráfaga
CTRL_KEYS = {e.KEY_LEFTCTRL, e.KEY_RIGHTCTRL}

# Rueda libre (inercia de scroll)
FREEWHEEL_KEY = e.KEY_F7
WHEEL_WINDOW = 0.2   # s de ticks recientes usados para medir la velocidad
WHEEL_IDLE = 0.05    # s sin ticks para considerar que se soltó la rueda
MIN_TICKS = 4        # ticks mínimos en la ventana para lanzar la inercia
MIN_SPEED = 25       # ticks/s mínimos para lanzar la inercia
FRICTION = 4.0       # 1/s; más alto = frena antes (recorrido extra = velocidad / FRICTION)
STOP_SPEED = 3       # ticks/s a los que se corta la inercia
FRAME = 0.008        # s entre pasos de la inercia
HI_RES = 120         # unidades REL_WHEEL_HI_RES por tick


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


def input_devices():
    """Teclados (para F6/F7/Ctrl+R) y mice con rueda, sin contar los virtuales."""
    devs = []
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        if "ydotoold" in dev.name or "autoclick" in dev.name:
            continue
        caps = dev.capabilities()
        keys = caps.get(e.EV_KEY, [])
        if HOTKEY in keys or CHORD_KEY in keys or e.REL_WHEEL in caps.get(e.EV_REL, []):
            devs.append(dev)
    return devs


class FreeWheel:
    """Inercia para la rueda: al soltarla girando rápido sigue scrolleando y frena sola.

    Los ticks reales pasan igual a las apps; esto sólo agrega scroll después.
    """

    def __init__(self, mouse):
        self.mouse = mouse
        self.enabled = False
        self.ticks = deque()  # (tiempo, valor) de los ticks recientes
        self.speed = 0.0      # ticks/s con signo; distinto de 0 mientras hay inercia
        self.last = 0.0
        self.pending = 0.0    # fracción de unidad hi-res aún no emitida
        self.legacy = 0       # unidades hi-res aún no emitidas como tick entero

    def toggle(self):
        self.enabled = not self.enabled
        self.reset()
        return self.enabled

    def reset(self):
        self.ticks.clear()
        self.stop()

    def stop(self):
        self.speed = 0.0
        self.pending = 0.0
        self.legacy = 0

    def on_tick(self, value, now):
        self.stop()  # tocar la rueda frena la inercia
        if self.ticks and (self.ticks[-1][1] > 0) != (value > 0):
            self.ticks.clear()  # cambió de sentido
        self.ticks.append((now, value))
        while now - self.ticks[0][0] > WHEEL_WINDOW:
            self.ticks.popleft()

    def timeout(self, now):
        """Segundos hasta el próximo paso pendiente, o None si no hay nada."""
        if self.speed:
            return max(0.0, self.last + FRAME - now)
        if self.ticks:
            return max(0.0, self.ticks[-1][0] + WHEEL_IDLE - now)
        return None

    def update(self, now):
        if self.speed:
            self._step(now)
        elif self.ticks and now - self.ticks[-1][0] >= WHEEL_IDLE:
            self._launch(now)

    def _launch(self, now):
        ticks = list(self.ticks)
        self.ticks.clear()
        if not self.enabled or len(ticks) < MIN_TICKS:
            return
        span = ticks[-1][0] - ticks[0][0]
        if span <= 0:
            return
        speed = sum(v for _, v in ticks) / span
        if abs(speed) >= MIN_SPEED:
            self.speed = speed
            self.last = now

    def _step(self, now):
        dt = now - self.last
        self.last = now
        self.speed *= math.exp(-FRICTION * dt)
        if abs(self.speed) < STOP_SPEED:
            self.stop()
            return
        self.pending += self.speed * dt * HI_RES
        units = int(self.pending)
        if not units:
            return
        self.pending -= units
        self.legacy += units
        self.mouse.write(e.EV_REL, e.REL_WHEEL_HI_RES, units)
        whole = int(self.legacy / HI_RES)
        if whole:
            self.legacy -= whole * HI_RES
            self.mouse.write(e.EV_REL, e.REL_WHEEL, whole)
        self.mouse.syn()


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
        {e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT],
         e.EV_REL: [e.REL_X, e.REL_Y, e.REL_WHEEL, e.REL_WHEEL_HI_RES]},
        name="autoclick",
    )
    time.sleep(0.5)  # el compositor necesita detectar el dispositivo nuevo

    sel = selectors.DefaultSelector()
    wheel = FreeWheel(mouse)
    devs = input_devices()
    for dev in devs:
        sel.register(dev, selectors.EVENT_READ)
    ctrl = set()  # (dispositivo, tecla) de los Ctrl apretados
    print(f"F6 o Ctrl+R -> {clicks} clicks en {duration:g} s "
          f"(1 cada {duration / clicks * 1000:g} ms). "
          f"F7 -> rueda libre (desactivada). "
          f"Escuchando en {len(devs)} dispositivos. Ctrl+C para salir.")

    try:
        while True:
            for key, _ in sel.select(wheel.timeout(time.monotonic())):
                try:
                    events = list(key.fileobj.read())
                except BlockingIOError:
                    continue  # lo vació el drenaje posterior a una ráfaga
                for ev in events:
                    if ev.type == e.EV_REL and ev.code == e.REL_WHEEL:
                        wheel.on_tick(ev.value, time.monotonic())
                        continue
                    if ev.type != e.EV_KEY:
                        continue
                    if ev.code in CTRL_KEYS:
                        if ev.value:
                            ctrl.add((key.fileobj.path, ev.code))
                        else:
                            ctrl.discard((key.fileobj.path, ev.code))
                    if ev.value != 1:
                        continue
                    if ev.code == HOTKEY or (ev.code == CHORD_KEY and ctrl):
                        wheel.reset()
                        took = burst(mouse, clicks, duration)
                        print(f"{clicks} clicks en {took:.3f} s")
                        # Descarta F6/Ctrl+R que se hayan acumulado durante la ráfaga
                        # y resincroniza los Ctrl con el estado real del teclado.
                        ctrl.clear()
                        for d in devs:
                            try:
                                list(d.read())
                            except BlockingIOError:
                                pass
                            ctrl.update((d.path, k) for k in d.active_keys()
                                        if k in CTRL_KEYS)
                        break
                    elif ev.code == FREEWHEEL_KEY:
                        state = "activa" if wheel.toggle() else "desactivada"
                        print(f"Rueda libre {state}")
                    elif e.BTN_MOUSE <= ev.code < e.BTN_JOYSTICK:
                        wheel.stop()  # un click frena la inercia
            wheel.update(time.monotonic())
    except KeyboardInterrupt:
        pass
    finally:
        mouse.close()


if __name__ == "__main__":
    main()
