"""Capa BLE para Linux con bleak — port de RGBDeviceManager + AddDeviceViewModel.

- Escaneo: filtra candidatos MeRGBW por AD (tipo 0x02 con UUID 0x3519) o por
  manufacturer data con deviceType/modelo, y por nombre BLE típico.
  En Linux BlueZ no siempre expone el scanRecord crudo, así que el filtro es
  best-effort: muestra todo y marca probables MeRGBW.
- Conexión: BleakClient, MTU negociado por el sistema, notify en FFF4,
  write-without-response en FFF3.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field

try:
    from bleak import BleakScanner, BleakClient
    from bleak.backends.device import BLEDevice
    from bleak.backends.scanner import AdvertisementData
except ImportError:  # permite importar protocol/tests sin bleak instalado
    BleakScanner = BleakClient = None  # type: ignore

from . import protocol as P


@dataclass
class FoundDevice:
    address: str
    name: str
    rssi: int
    probable_mergbw: bool = False
    manufacturer: dict = field(default_factory=dict)
    service_uuids: list = field(default_factory=list)
    device_type: int | None = None
    model: str | None = None


def parse_mergbw_manufacturer(data: bytes) -> tuple[int | None, str | None, int | None]:
    """Payload manufacturer de bleak (sin company ID).
    Java ve [10]=tipo, [11:21]=modelo, [23:27]=factoryID sobre el AD completo
    (que incluye 2 bytes de company ID); en bleak el índice se desplaza -2:
    [8]=tipo, [9:19]=modelo, [21:25]=factoryID."""
    try:
        if len(data) >= 9:
            dtype = data[8] & 0xFF
            model = None
            factory = None
            if len(data) >= 19:
                model = bytes(data[9:19]).split(b"\x00")[0].decode("utf-8", errors="ignore").strip()
            if len(data) >= 25:
                factory = (data[21] << 24) | (data[22] << 16) | (data[23] << 8) | data[24]
            return dtype, model or None, factory
    except Exception:
        pass
    return None, None, None


def _looks_like_mergbw(name: str, adv_manuf: dict, uuids: list) -> tuple[bool, int | None, str | None]:
    for u in uuids or []:
        if "3519" in str(u).lower():
            # confirma con manufacturer si existe
            for _c, data in (adv_manuf or {}).items():
                dt, model, _f = parse_mergbw_manufacturer(bytes(data))
                if dt is not None:
                    return True, dt, model
            return True, None, None
    for _c, data in (adv_manuf or {}).items():
        dt, model, _f = parse_mergbw_manufacturer(bytes(data))
        if dt is not None and 1 <= dt <= 8 and model and any(
                k in model.upper() for k in ("TG", "LED", "RGB", "MERGBW")):
            return True, dt, model
    n = (name or "").upper()
    # "LED Lights" solo es indicativo; sin UUID 3519 ni manufacturer válido no marcamos
    if any(k in n for k in ("MERGBW", "ME-RGB", "TG201", "TG609", "TG610")):
        return True, None, None
    return False, None, None


async def scan(timeout: float = 8.0) -> list[FoundDevice]:
    if BleakScanner is None:
        raise RuntimeError("bleak no instalado: pip install bleak")
    # discover() es fiable en bleak 3.x; el modo callback start/stop
    # pierde dispositivos en algunas versiones de BlueZ.
    seen = await BleakScanner.discover(timeout=timeout, return_adv=True)
    found: list[FoundDevice] = []
    for _addr, (device, adv) in seen.items():
        uuids = list(getattr(adv, "service_uuids", []) or [])
        manuf = dict(getattr(adv, "manufacturer_data", {}) or {})
        flag, dtype, model = _looks_like_mergbw(device.name or "", manuf, uuids)
        found.append(FoundDevice(
            address=device.address, name=device.name or "(sin nombre)",
            rssi=int(getattr(adv, "rssi", 0) or 0), probable_mergbw=flag,
            manufacturer=manuf, service_uuids=uuids,
            device_type=dtype, model=model))
    found.sort(key=lambda d: (not d.probable_mergbw, -(d.rssi or -999)))
    return found


class MeRGBWDevice:
    """Conexión a un equipo. Port simplificado de RGBDeviceManager."""

    def __init__(self, address: str, device_type: int = 1):
        self.address = address
        self.device_type = device_type
        self.client: BleakClient | None = None
        self.last_status: dict | None = None
        self._notify_buf = bytearray()
        self.on_notify = None  # callback(cmd:int, packet:bytes)

    async def connect(self, timeout: float = 15.0):
        if BleakClient is None:
            raise RuntimeError("bleak no instalado: pip install bleak")
        self.client = BleakClient(self.address, timeout=timeout)
        await self.client.connect()
        try:
            await self.client.start_notify(P.CHAR_NOTIFY, self._handle_notify)
        except Exception as e:
            print(f"[!] no se pudo activar notify en {P.CHAR_NOTIFY}: {e}")
        return True

    async def disconnect(self):
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None

    def _handle_notify(self, _char, data: bytearray):
        pkt = bytes(data)
        if len(pkt) >= 5 and pkt[0] in (P.CMD_HEAD, P.CMD_HEAD_RX):
            cmd = pkt[1]
            if not P.check_valid(pkt):
                pass  # checksum distinto en fragmentados; igual intentamos parsear
            if cmd == P.CMD_SYNC_STATUS:
                try:
                    self.last_status = P.parse_sync_status(self.device_type, pkt)
                except Exception:
                    pass
            if self.on_notify:
                try:
                    self.on_notify(cmd, pkt)
                except Exception:
                    pass
        else:
            # algunos firmwares fragmentan; acumulamos best-effort
            self._notify_buf += pkt

    async def write(self, packet: bytes, with_response: bool = True):
        assert self.client and self.client.is_connected, "no conectado"
        # La app Android (FastBLE) no fija WRITE_TYPE: Android usa por defecto
        # Write With Response. El char anuncia ambas, pero el firmware Telink
        # solo contesta al With Response. Probamos True primero.
        try:
            await self.client.write_gatt_char(P.CHAR_WRITE, packet, response=with_response)
        except Exception as e:
            if with_response:
                await self.client.write_gatt_char(P.CHAR_WRITE, packet, response=False)
            else:
                raise e

    async def sync(self) -> bytes:
        """Pide estado (CMD 0) + hora (CMD 12), como HomeViewModel.syncInfo."""
        await self.write(P.cmd_sync_status())
        await asyncio.sleep(0.3)
        await self.write(P.cmd_sync_time())
        return P.cmd_sync_time()
