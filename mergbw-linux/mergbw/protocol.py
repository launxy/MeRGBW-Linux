"""MeRGBW BLE protocol — port fiel de com.mergbw.core.ble.CommandUtils / CommandList / Constants.

Formato de paquete (ingeniería inversa de MeRGBW 1.6.3, package com.mergbw.android):
    [0x55, CMD, SEQ, LEN, PAYLOAD..., CHECKSUM]
    - 0x55       : cabecera fija (CMD_HEAD = 85)
    - CMD        : un byte (ver CMD_*)
    - SEQ        : 0xFF (-1) para comandos simples, o nº de secuencia para fragmentados
    - LEN        : longitud total del paquete (5 + len(payload))
    - CHECKSUM   : (~(suma & 0xFF)) & 0xFF, donde suma = suma de todos los bytes previos como unsigned.
                   La suma se pliega con `while s > 255: s &= 255` (equivale a s & 0xFF).
                   Validación: ((~(suma_sin_ultimo + ultimo_con_signo)) & 0xFF) == 0

GATT:
    Servicio  : 0000fff0-0000-1000-8000-00805f9b34fb
    Escritura : 0000fff3-0000-1000-8000-00805f9b34fb  (write without response)
    Notify    : 0000fff4-0000-1000-8000-00805f9b34fb  (las respuestas llegan aquí, data[1] = CMD)
"""
from __future__ import annotations
import colorsys
import datetime

GATT_SERVICE = "0000fff0-0000-1000-8000-00805f9b34fb"
CHAR_WRITE = "0000fff3-0000-1000-8000-00805f9b34fb"
CHAR_NOTIFY = "0000fff4-0000-1000-8000-00805f9b34fb"

CMD_HEAD = 0x55
CMD_HEAD_RX = 0x56  # el firmware responde con 0x56; la app envía 0x55
CMD_SEQ_DEFAULT = 0xFF

# --- CommandList (com.mergbw.core.ble.CommandList), valores unsigned 0-255 ---
CMD_SYNC_STATUS = 0
CMD_POWER = 1
CMD_FIRMWARE_INFO = 2
CMD_SET_COLOR = 3
CMD_SET_PART_COLOR = 4
CMD_SET_BRIGHTNESS = 5
CMD_SET_MODE = 6
CMD_SET_MUSIC_MODE = 7
CMD_SET_MUSIC_SENS = 8
CMD_SET_DIY_MODE = 9
CMD_SET_TIMER = 10
CMD_SET_LED_NUM = 11
CMD_SYNC_TIME = 12
CMD_CONFIG_MODE = 13
CMD_CHECK_BIND = 14
CMD_SET_MODE_SPEED = 15
CMD_SET_WHITE_LIGHT = 16
CMD_SET_WHITE_BRIGHTNESS = 17
CMD_SET_COLD_WARM = 18
CMD_CONFIG_REMOTE = 242
CMD_CONFIG_INFO = 243
CMD_CONFIG_RGB_ORDER = 244
CMD_CONFIG_LIMIT = 245
CMD_CONFIG_COMPLETE = 246

DEVICE_TYPES = {
    1: "letras / tira direccionable",
    2: "RGB line",
    3: "star lights",
    4: "handle lights",
    5: "sunset",
    6: "bulb",
    7: "ceiling colorful",
    8: "ceiling RGB",
}

MIN_SENSITIVE = 60


def _fold(s: int) -> int:
    while s > 255:
        s &= 255
    return s


def checksum(data_without_checksum: bytes) -> int:
    s = _fold(sum(data_without_checksum) & 0xFFFFFFFF)
    # réplica exacta del bucle java: suma ya plegada, checksum = (~s) & 0xFF
    return (~s) & 0xFF


def check_valid(packet: bytes) -> bool:
    """Port de CommandUtils.checkValid, aceptando TX (0x55) y RX (0x56)."""
    if len(packet) < 5:
        return False
    if packet[0] not in (CMD_HEAD, CMD_HEAD_RX):
        return False
    s = _fold(sum(b for b in packet[:-1]))
    last = packet[-1] if packet[-1] < 128 else packet[-1] - 256  # byte con signo como en Java
    return (((~(s + last)) & 255) == 0)


def get_command(cmd: int, payload: bytes | None = None) -> bytes:
    """Port de CommandUtils.getCommand(byte cmdCode, byte[] value)."""
    p = payload or b""
    length = 5 + len(p)
    buf = bytearray(length)
    buf[0] = CMD_HEAD
    buf[1] = cmd & 0xFF
    buf[2] = CMD_SEQ_DEFAULT
    buf[3] = length & 0xFF
    if p:
        buf[4:4 + len(p)] = p
    # el último byte de momento es 0; se incluye en la suma igual que en Java
    # (Java suma el array con el último byte a 0, luego lo sobrescribe)
    s = _fold(sum(buf))
    buf[length - 1] = ((~s) & 0xFF)
    return bytes(buf)


def get_seq_command(cmd: int, chunk: bytes, seq: int) -> bytes:
    """Port de CommandUtils.getSeqCommand(cmd, value, seq, length)."""
    length = len(chunk)
    total = length + 5
    buf = bytearray(total)
    buf[0] = CMD_HEAD
    buf[1] = cmd & 0xFF
    buf[2] = seq & 0xFF
    buf[3] = total & 0xFF
    buf[4:4 + length] = chunk
    s = 0
    for b in buf:
        s += b
    while s > 255:
        s = (s >> 8) + (s & 255)
    buf[length + 4] = ((~s) & 0xFF)
    return bytes(buf)


def get_byte_array_u16be(value: int) -> bytes:
    return bytes([(value >> 8) & 0xFF, value & 0xFF])


# ---------- builders de payload (puertos de los ViewModel) ----------

def cmd_power(on: bool) -> bytes:
    return get_command(CMD_POWER, bytes([1 if on else 0]))


def cmd_sync_status() -> bytes:
    return get_command(CMD_SYNC_STATUS, None)


def cmd_firmware_info() -> bytes:
    return get_command(CMD_FIRMWARE_INFO, None)


def cmd_color_hsv(color_int: int) -> bytes:
    """DeviceDetailViewModel1/7.setColor: int Android -> HSV [hue_hi,hue_lo,sat_hi,sat_lo].
    hue = grados 0-360, sat = s*1000 como u16be."""
    r = (color_int >> 16) & 0xFF
    g = (color_int >> 8) & 0xFF
    b = color_int & 0xFF
    h, s, _v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    hue = int(h * 360.0) % 360
    sat = int(s * 1000.0)
    return get_command(CMD_SET_COLOR, bytes([hue >> 8, hue & 0xFF, sat >> 8, sat & 0xFF]))


def cmd_color_rgb(r: int, g: int, b: int) -> bytes:
    """DeviceDetailViewModel5/6.setColor (bulb, sunset, star): RGB directo."""
    return get_command(CMD_SET_COLOR, bytes([r & 0xFF, g & 0xFF, b & 0xFF]))


def cmd_brightness_type1(percent_0_100: int) -> bytes:
    """Tira direccionable tipo 1: payload u16be((i+5)*10)."""
    return get_command(CMD_SET_BRIGHTNESS, get_byte_array_u16be((percent_0_100 + 5) * 10))


def cmd_brightness_simple(percent_0_100: int) -> bytes:
    """Tipos 5/6/7: un byte (i+5)."""
    return get_command(CMD_SET_BRIGHTNESS, bytes([(percent_0_100 + 5) & 0xFF]))


def cmd_brightness_raw(value: int) -> bytes:
    return get_command(CMD_SET_BRIGHTNESS, bytes([value & 0xFF]))


def cmd_scene(index: int) -> bytes:
    return get_command(CMD_SET_MODE, get_byte_array_u16be(index) if index > 255 else bytes([index & 0xFF]))


def cmd_scene_index_byte(index: int) -> bytes:
    return get_command(CMD_SET_MODE, bytes([index & 0xFF]))


def cmd_scene_speed(speed: int) -> bytes:
    return get_command(CMD_SET_MODE_SPEED, bytes([speed & 0xFF]))


def cmd_music_mode(mode: int) -> bytes:
    return get_command(CMD_SET_MUSIC_MODE, bytes([mode & 0xFF]))


def cmd_music_sens(percent_0_100: int) -> bytes:
    v = int((percent_0_100 / 100.0) * (100 - MIN_SENSITIVE) + MIN_SENSITIVE)
    return get_command(CMD_SET_MUSIC_SENS, bytes([v & 0xFF]))


def cmd_led_num(n: int) -> bytes:
    return get_command(CMD_SET_LED_NUM, get_byte_array_u16be(n))


def cmd_sync_time(now: datetime.datetime | None = None) -> bytes:
    now = now or datetime.datetime.now()
    week = now.isoweekday()  # 1=Lun..7=Dom, igual que StringUtils.getWeekInt()
    payload = bytes([
        (now.year >> 8) & 0xFF, now.year & 0xFF,
        now.month & 0xFF, now.day & 0xFF,
        now.hour & 0xFF, now.minute & 0xFF, now.second & 0xFF,
        week & 0xFF,
    ])
    return get_command(CMD_SYNC_TIME, payload)


def cmd_check_bind_android_id_hex12(hex12: str | None = None) -> bytes:
    """CMD 14. En Android: AppUtils.getUniId() = 12 chars hex del android_id -> bytes.
    En Linux pasamos 12 hex chars o None (payload vacío)."""
    if not hex12:
        return get_command(CMD_CHECK_BIND, None)
    hex12 = hex12[:12].lower()
    return get_command(CMD_CHECK_BIND, bytes.fromhex(hex12))


def cmd_white_brightness(v: int) -> bytes:
    return get_command(CMD_SET_WHITE_BRIGHTNESS, bytes([v & 0xFF]))


def cmd_cold_warm_18(cold_bri: int, warm_bri: int, cold_pct: int, warm_pct: int) -> bytes:
    return get_command(CMD_SET_COLD_WARM, bytes([
        cold_bri & 0xFF, warm_bri & 0xFF, cold_pct & 0xFF, warm_pct & 0xFF]))


def cmd_timer(open_en: bool, open_h: int, open_m: int, open_week: int,
             close_en: bool, close_h: int, close_m: int, close_week: int) -> bytes:
    """CMD 10. week = bitmask 1 bit por día, bit0=0, bits1-7 = Lun..Dom
    (construido en la app como "0"+Dom..Lun)."""
    payload = bytes([
        1 if open_en else 0, open_h & 0xFF, open_m & 0xFF, open_week & 0xFF,
        1 if close_en else 0, close_h & 0xFF, close_m & 0xFF, close_week & 0xFF,
    ])
    return get_command(CMD_SET_TIMER, payload)


def weekmask(mon=False, tue=False, wed=False, thu=False, fri=False, sat=False, sun=False) -> int:
    bits = [0, 1 if sun else 0, 1 if sat else 0, 1 if fri else 0,
            1 if thu else 0, 1 if wed else 0, 1 if tue else 0, 1 if mon else 0]
    s = "".join(str(x) for x in bits)
    return int(s, 2)


def cmd_subcolor_61(chunks_rgb20: list[tuple[int, int, int]], mtu: int = 20) -> list[bytes]:
    """CMD 4 fragmentado. 20 LEDs -> 61 bytes [0x01, R1,G1,B1, ...].
    Replica DeviceDetailViewModel1.setSubColor (MTU-8 por fragmento)."""
    buf = bytearray(61)
    buf[0] = 1
    for i, (r, g, b) in enumerate(chunks_rgb20[:20]):
        buf[1 + i * 3] = r & 0xFF
        buf[1 + i * 3 + 1] = g & 0xFF
        buf[1 + i * 3 + 2] = b & 0xFF
    frag = mtu - 8
    if frag <= 0:
        frag = 12
    out: list[bytes] = []
    if 61 > frag:
        import math
        n = math.ceil(61 / frag)
        for i in range(n):
            if i == n - 1:
                start = i * frag
                chunk = bytes(buf[start:])
                out.append(get_seq_command(CMD_SET_PART_COLOR, chunk, 0xFF))
            else:
                chunk = bytes(buf[i * frag:(i + 1) * frag])
                out.append(get_seq_command(CMD_SET_PART_COLOR, chunk, i + 1))
    else:
        out.append(get_seq_command(CMD_SET_PART_COLOR, bytes(buf), 0xFF))
    return out


def parse_sync_status(device_type: int, data: bytes) -> dict:
    """Port de ViewDataUtils.analyseSyncData. data = paquete completo de notify (CMD 0).
    data[0]=0x55, data[1]=0, data[2]=seq, data[3]=len, data[4:]=campos."""
    if len(data) < 6 or data[1] != CMD_SYNC_STATUS:
        raise ValueError("no es un paquete de estado (CMD 0)")
    d = data  # índices iguales que en Java
    out: dict = {"device_type": device_type, "open": d[4] == 1}

    def week(b: int) -> list[bool]:
        return [(b >> i) & 1 == 1 for i in range(7, -1, -1)]

    if device_type in (1, 2, 4):
        out.update({
            "brightness": (((d[5] << 8) | d[6]) // 10) - 5,
            "open_alarm": {"set": d[7] == 1, "h": d[8], "m": d[9], "week": week(d[10])},
            "close_alarm": {"set": d[11] == 1, "h": d[12], "m": d[13], "week": week(d[14])},
            "led_num": (d[15] << 8) | d[16],
            "sensitive": d[17],
        })
    elif device_type == 3:
        out.update({
            "brightness": d[5] - 5,
            "open_alarm": {"set": d[6] == 1, "h": d[7], "m": d[8], "week": week(d[9])},
            "close_alarm": {"set": d[10] == 1, "h": d[11], "m": d[12], "week": week(d[13])},
            "star_brightness": d[14],
            "motor_speed": d[15],
        })
    elif device_type == 5:
        out.update({
            "brightness": d[5] - 5,
            "open_alarm": {"set": d[6] == 1, "h": d[7], "m": d[8], "week": week(d[9])},
            "close_alarm": {"set": d[10] == 1, "h": d[11], "m": d[12], "week": week(d[13])},
        })
    elif device_type == 6:
        out.update({
            "brightness": d[5] - 5,
            "white_open": d[6] == 1,
            "white_brightness": d[7] - 5,
            "open_alarm": {"set": d[8] == 1, "h": d[9], "m": d[10], "week": week(d[11])},
            "close_alarm": {"set": d[12] == 1, "h": d[13], "m": d[14], "week": week(d[15])},
        })
    elif device_type in (7, 8):
        out.update({
            "brightness": d[5] - 5,
            "open_alarm": {"set": d[6] == 1, "h": d[7], "m": d[8], "week": week(d[9])},
            "close_alarm": {"set": d[10] == 1, "h": d[11], "m": d[12], "week": week(d[13])},
        })
        if len(d) >= 18:
            out.update({"cold_brightness": d[14], "warm_brightness": d[15],
                        "cold_pct": d[16], "warm_pct": d[17]})
        if len(d) >= 19:
            out["sensitive"] = d[18]
    return out


def hexs(b: bytes) -> str:
    return b.hex().upper()
