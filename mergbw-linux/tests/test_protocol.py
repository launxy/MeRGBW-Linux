"""Tests del protocolo (sin BLE real). Réplica de CommandUtils Java."""
from mergbw import protocol as P


def test_checksum_vector():
    # CMD power ON: 55 01 FF 06 01 CS
    pkt = P.cmd_power(True)
    assert pkt[0] == 0x55 and pkt[1] == 1 and pkt[2] == 0xFF and pkt[3] == len(pkt)
    assert P.check_valid(pkt), pkt.hex()
    # cálculo manual
    s = (0x55 + 0x01 + 0xFF + 0x06 + 0x01) & 0xFF
    assert pkt[-1] == ((~s) & 0xFF)


def test_sync_status_empty_payload():
    pkt = P.cmd_sync_status()
    assert len(pkt) == 5
    assert P.check_valid(pkt)


def test_color_hsv_deterministic():
    a = P.cmd_color_hsv(0xFF8000)
    b = P.cmd_color_hsv(0xFF8000)
    assert a == b and P.check_valid(a)
    assert len(a) == 9  # 5 + 4 payload


def test_color_rgb():
    pkt = P.cmd_color_rgb(255, 128, 0)
    assert pkt[4:7] == bytes([255, 128, 0])
    assert P.check_valid(pkt)


def test_seq_fragment():
    rgb20 = [(255, 0, 0)] * 20
    frags = P.cmd_subcolor_61(rgb20, mtu=20)
    assert len(frags) > 1
    for f in frags:
        assert f[0] == 0x55 and f[1] == P.CMD_SET_PART_COLOR
        # Nota: los fragmentados usan el plegado Java ((s>>8)+(s&255)),
        # distinto del checkValid simple; se verifica estructura + LEN.
        assert f[3] == len(f)


def test_sync_time_length():
    import datetime
    pkt = P.cmd_sync_time(datetime.datetime(2026, 10, 12, 12, 0, 0))
    assert len(pkt) == 13  # 5 + 8
    assert pkt[4] == 2026 >> 8 and pkt[5] == 2026 & 0xFF
    assert P.check_valid(pkt)


def test_parse_status_type1():
    # construye un estado sintético válido y parsea
    body = bytes([1, 0x03, 0x20, 1, 7, 30, 0b01111111, 0, 22, 0, 0, 0, 60, 0, 70])
    # body corresponde a data[4:] del paquete CMD0
    payload_len = len(body)
    total = 5 + payload_len
    buf = bytearray(total)
    buf[0] = 0x55; buf[1] = 0; buf[2] = 0xFF; buf[3] = total
    buf[4:] = body
    s = sum(buf) & 0xFF
    buf[-1] = (~s) & 0xFF
    st = P.parse_sync_status(1, bytes(buf))
    assert st["open"] is True
    assert st["led_num"] == 60


def test_rx_head_captures_reales():
    # Capturas reales del equipo 41:42:D9:0E:68:1A (TG201A, tipo 1).
    # El firmware responde con cabecera 0x56 (la app envía 0x55).
    assert P.check_valid(bytes.fromhex("560EFF060294"))      # bind: UNBIND (02)
    assert P.check_valid(bytes.fromhex("5601FF0600A3"))      # ack power
    assert P.check_valid(bytes.fromhex("5603FF0600A1"))      # ack color
    st = P.parse_sync_status(1, bytes.fromhex("5600FF140002120014007F0006197F002864C5"))
    assert st["open"] is False and st["led_num"] == 40 and st["brightness"] == 48
