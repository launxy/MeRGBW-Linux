#!/usr/bin/env python3
"""MeRGBW para Linux — CLI BLE.

Ejemplos:
  mergbw scan
  mergbw --mac AA:BB:CC:DD:EE:FF status
  mergbw --mac AA:BB:CC:DD:EE:FF --type 1 on
  mergbw --mac AA:BB:CC:DD:EE:FF --type 6 color --rgb FF8000
  mergbw --mac AA:BB:CC:DD:EE:FF --type 1 color --rgb FF8000     # convierte a HSV como la app
  mergbw --mac ... brightness --value 80
  mergbw --mac ... scene --index 4 --speed 50
  mergbw --mac ... music --mode 2 --sens 80
  mergbw --mac ... lednum --value 60
  mergbw --mac ... timer --open 07:30 --close 23:00 --days lun,mar,mie,jue,vie
  mergbw --mac ... white --value 70
  mergbw --mac ... sync-time
  mergbw --mac ... firmware
"""
from __future__ import annotations
import argparse
import asyncio
import sys

from mergbw import protocol as P
from mergbw.device import scan as ble_scan, MeRGBWDevice


def parse_rgb(s: str) -> tuple[int, int, int]:
    s = s.strip().lstrip("#")
    if len(s) == 6:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    raise ValueError("RGB debe ser hex de 6 dígitos, ej. FF8000")


def parse_color_int(s: str) -> int:
    s = s.strip().lstrip("#")
    if len(s) == 6:
        return int(s, 16)
    if len(s) == 8:  # AARRGGBB android
        return int(s[2:], 16)
    raise ValueError("color hex de 6 u 8 dígitos")


DAYS = {"lun": 0, "mar": 1, "mie": 2, "jue": 3, "vie": 4, "sab": 5, "dom": 6}


def parse_days(s: str) -> int:
    sel = {d.strip().lower()[:3] for d in s.split(",") if d.strip()}
    # weekmask(mon..sun)
    order = ["lun", "mar", "mie", "jue", "vie", "sab", "dom"]
    kw = {d: (d in sel) for d in order}
    # weekmask firma: (mon,tue,wed,thu,fri,sat,sun)
    return P.weekmask(kw["lun"], kw["mar"], kw["mie"], kw["jue"],
                      kw["vie"], kw["sab"], kw["dom"])


def parse_hm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


async def cmd_scan(args):
    devs = await ble_scan(timeout=args.timeout)
    if not devs:
        print("Sin resultados. Acerca el equipo, actívate el Bluetooth y reintenta.")
        return
    print(f"{'MAC':17}  {'RSSI':>4}  {'?':1}  Nombre  [tipo/modelo]")
    for d in devs:
        mark = "*" if d.probable_mergbw else " "
        extra = ""
        if d.device_type is not None:
            extra = f"  [type={d.device_type}" + (f" model={d.model}" if d.model else "") + "]"
            if d.device_type is not None:
                extra += f" -> usa --type {d.device_type}"
        print(f"{d.address:17}  {d.rssi:>4}  {mark}  {d.name}{extra}")
    print("\n* = probable MeRGBW. Usa --mac <MAC> --type <1-8> para conectar.")


async def with_device(args, fn):
    dev = MeRGBWDevice(args.mac, device_type=args.type)
    notifications: list = []

    def on_n(cmd, pkt):
        notifications.append((cmd, pkt))
        print(f"  <- notify CMD={cmd} len={len(pkt)} {P.hexs(pkt)}")
    dev.on_notify = on_n
    print(f"Conectando a {args.mac} (type {args.type}) ...")
    await dev.connect()
    print("Conectado. Bind + sincronizando estado + hora ...")
    try:
        # HomeViewModel.deviceInitData: tipos 1/4 -> CMD 14 con ID antes del estado;
        # tipos 6/7 -> CMD 14 vacío; tipos 2/3/5 -> directo.
        if args.type in (1, 4):
            bind = P.cmd_check_bind_android_id_hex12("010203040506")
            print(f"  -> BIND {P.hexs(bind)}")
            await dev.write(bind)
            await asyncio.sleep(1.0)
        elif args.type in (6, 7):
            bind = P.cmd_check_bind_android_id_hex12(None)
            print(f"  -> BIND {P.hexs(bind)}")
            await dev.write(bind)
            await asyncio.sleep(1.0)
        await dev.sync()
        await asyncio.sleep(2.0)
        if dev.last_status:
            print("Estado:", dev.last_status)
        else:
            print("(sin estado parseado; ver notifies arriba — si no hay ninguno, el equipo no responde)")
        await fn(dev)
    finally:
        await dev.disconnect()
        print("Desconectado.")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="mergbw", description="Control MeRGBW desde Linux (BLE)")
    ap.add_argument("--mac", help="MAC del equipo (requerido salvo scan)")
    ap.add_argument("--type", type=int, default=1, choices=list(range(1, 9)),
                    help="deviceType 1-8 (default 1). Ver PROTOCOL.md")
    ap.add_argument("--timeout", type=float, default=8.0, help="timeout escaneo")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("scan", help="escanear BLE")

    p = sub.add_parser("status", help="leer estado (CMD 0)")
    p = sub.add_parser("on", help="encender")
    p = sub.add_parser("off", help="apagar")
    p = sub.add_parser("sync-time", help="sincronizar hora (CMD 12)")
    p = sub.add_parser("firmware", help="pedir versión firmware (CMD 2)")

    p = sub.add_parser("color", help="fijar color")
    p.add_argument("--rgb", required=True, help="hex, ej FF8000")

    p = sub.add_parser("brightness", help="brillo 0-100")
    p.add_argument("--value", type=int, required=True)

    p = sub.add_parser("scene", help="escena/modo")
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--speed", type=int, default=None)

    p = sub.add_parser("music", help="modo música")
    p.add_argument("--mode", type=int, required=True)
    p.add_argument("--sens", type=int, default=None)

    p = sub.add_parser("lednum", help="nº de LEDs")
    p.add_argument("--value", type=int, required=True)

    p = sub.add_parser("white", help="brillo blanco (CMD 17)")
    p.add_argument("--value", type=int, required=True)

    p = sub.add_parser("timer", help="alarma on/off (CMD 10)")
    p.add_argument("--open", default=None, help="HH:MM o 'off'")
    p.add_argument("--close", default=None, help="HH:MM o 'off'")
    p.add_argument("--days", default="lun,mar,mie,jue,vie,sab,dom")
    return ap


async def amain(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.cmd == "scan":
        return await cmd_scan(args)
    if not args.mac:
        ap.error("--mac es requerido para este comando")
        return

    async def run(dev: MeRGBWDevice):
        c = args.cmd
        if c == "status":
            await dev.write(P.cmd_sync_status())
            await asyncio.sleep(1.0)
            print(dev.last_status or "(sin respuesta todavía; espera notify)")
        elif c == "on":
            await dev.write(P.cmd_power(True))
            print("-> ON", P.hexs(P.cmd_power(True)))
        elif c == "off":
            await dev.write(P.cmd_power(False))
            print("-> OFF", P.hexs(P.cmd_power(False)))
        elif c == "sync-time":
            pkt = P.cmd_sync_time()
            await dev.write(pkt)
            print("-> SYNC_TIME", P.hexs(pkt))
        elif c == "firmware":
            await dev.write(P.cmd_firmware_info())
            print("-> FIRMWARE_REQ (respuesta en notify CMD 2)")
            await asyncio.sleep(1.0)
        elif c == "color":
            if args.type == 1:
                ci = parse_color_int(args.rgb)
                pkt = P.cmd_color_hsv(ci)
                print(f"-> COLOR HSV(type1) {args.rgb} =", P.hexs(pkt))
            else:
                r, g, b = parse_rgb(args.rgb)
                pkt = P.cmd_color_rgb(r, g, b)
                print(f"-> COLOR RGB(type{args.type}) =", P.hexs(pkt))
            await dev.write(pkt)
        elif c == "brightness":
            v = args.value
            pkt = P.cmd_brightness_type1(v) if args.type in (1, 2, 4) else P.cmd_brightness_simple(v)
            await dev.write(pkt)
            print("-> BRIGHTNESS", P.hexs(pkt))
        elif c == "scene":
            pkt = P.cmd_scene_index_byte(args.index)
            await dev.write(pkt)
            print("-> SCENE", P.hexs(pkt))
            if args.speed is not None:
                pkt2 = P.cmd_scene_speed(args.speed)
                await dev.write(pkt2)
                print("-> SPEED", P.hexs(pkt2))
        elif c == "music":
            await dev.write(P.cmd_music_mode(args.mode))
            print("-> MUSIC_MODE", args.mode)
            if args.sens is not None:
                pkt2 = P.cmd_music_sens(args.sens)
                await dev.write(pkt2)
                print("-> MUSIC_SENS", P.hexs(pkt2))
        elif c == "lednum":
            pkt = P.cmd_led_num(args.value)
            await dev.write(pkt)
            print("-> LEDNUM", P.hexs(pkt))
        elif c == "white":
            pkt = P.cmd_white_brightness(args.value)
            await dev.write(pkt)
            print("-> WHITE", P.hexs(pkt))
        elif c == "timer":
            wm = parse_days(args.days)
            if args.open and args.open != "off":
                oh, om = parse_hm(args.open)
                oe = True
            else:
                oh, om, oe = 0, 0, False
            if args.close and args.close != "off":
                ch, cm = parse_hm(args.close)
                ce = True
            else:
                ch, cm, ce = 0, 0, False
            pkt = P.cmd_timer(oe, oh, om, wm, ce, ch, cm, wm)
            await dev.write(pkt)
            print("-> TIMER", P.hexs(pkt))
        else:
            print("comando no implementado")

    await with_device(args, run)


def main():
    asyncio.run(amain())


if __name__ == "__main__":
    main()
