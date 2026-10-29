"""BLE transport (no root needed on macOS).

The DP305P exposes a PingDong PDBT33F serial bridge:

    ff02  write / write-without-response   -> printer
    ff01  notify                           <- one complete protocol reply per
                                             notification, no 0x1e header
    ff03  notify                           <- status frames; ``01 01`` after
                                             every accepted write = flow credit

The command bodies are byte-identical to USB; only the 0x1e report header is
missing because a serial link has no report ids.

Bandwidth is the reason this exists next to USB: the printer consumes roughly
4.9 KB/s over BLE, so a 76 x 130 mm label takes ~6 s and fine detail is softer.
"""

from __future__ import annotations

import asyncio
import time

from .protocol import mgmt

__all__ = ["BlePrinter", "CH_WRITE", "CH_REPLY", "CH_EVENT", "DEFAULT_NAME_HINTS"]

CH_WRITE = "0000ff02-0000-1000-8000-00805f9b34fb"
CH_REPLY = "0000ff01-0000-1000-8000-00805f9b34fb"
CH_EVENT = "0000ff03-0000-1000-8000-00805f9b34fb"

DEFAULT_NAME_HINTS = ("dp305", "dp27", "detong", "dt20")
CHUNK = 512  # ATT MTU 515 minus ATT header


class BlePrinter:
    def __init__(self, name_hints: tuple[str, ...] = DEFAULT_NAME_HINTS,
                 scan_timeout: float = 8.0):
        self.name_hints = tuple(h.lower() for h in name_hints)
        self.scan_timeout = scan_timeout
        self.client = None
        self.device_name = ""
        self.replies: list[bytes] = []
        self.events: list[bytes] = []
        self.credits = 0
        self.credit_evt: asyncio.Event | None = None

    @staticmethod
    async def scan(timeout: float = 8.0) -> list[tuple[str, str]]:
        from bleak import BleakScanner
        found = await BleakScanner.discover(timeout=timeout, return_adv=True)
        out = []
        for _, (dev, adv) in found.items():
            out.append((dev.name or adv.local_name or "?", dev.address))
        return sorted(out)

    async def connect(self) -> None:
        from bleak import BleakClient, BleakScanner
        found = await BleakScanner.discover(timeout=self.scan_timeout, return_adv=True)
        dev = None
        for _, (d, adv) in found.items():
            name = (d.name or adv.local_name or "").lower()
            if any(hint in name for hint in self.name_hints):
                dev = d
                break
        if dev is None:
            raise SystemExit(
                "printer not found over BLE - is it powered on and not connected "
                "to a phone? (try `dzpost scan`)")
        self.device_name = dev.name or ""
        self.client = BleakClient(dev.address, timeout=20.0)
        await self.client.connect()
        await self.client.start_notify(CH_REPLY, self._on_reply)
        await self.client.start_notify(CH_EVENT, self._on_event)

    @property
    def mtu(self) -> int:
        try:
            return int(self.client.mtu_size)
        except Exception:
            return 0

    def _on_reply(self, _ch, data: bytearray) -> None:
        self.replies.append(bytes(data))

    def _on_event(self, _ch, data: bytearray) -> None:
        frame = bytes(data)
        self.events.append(frame)
        if len(frame) == 2 and frame[0] == 0x01 and frame[1] == 0x01:
            self.credits += 1
            if self.credit_evt is not None:
                self.credit_evt.set()

    async def disconnect(self) -> None:
        try:
            await self.client.stop_notify(CH_REPLY)
            await self.client.stop_notify(CH_EVENT)
            await self.client.disconnect()
        except Exception:
            pass

    async def query(self, typ: int, timeout: float = 1.5) -> bytes | None:
        self.replies.clear()
        await self.client.write_gatt_char(CH_WRITE, mgmt(0x1F, typ), response=True)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.replies:
                return self.replies[0]
            await asyncio.sleep(0.02)
        return None

    async def send(self, stream: bytes, window: int = 8) -> float:
        """Send with credit-window flow control; returns elapsed seconds.

        Pushing the whole stream without credits silently truncates the print:
        CoreBluetooth accepts the writes but the printer's UART buffer overflows.
        """
        if self.client is None:
            raise RuntimeError("not connected")
        self.credit_evt = asyncio.Event()
        chunks = [stream[o:o + CHUNK] for o in range(0, len(stream), CHUNK)]
        outstanding = 0
        t0 = time.monotonic()
        for chunk in chunks:
            while outstanding >= window:
                self.credit_evt.clear()
                try:
                    await asyncio.wait_for(self.credit_evt.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    pass
                outstanding = max(0, outstanding - 1)
            await self.client.write_gatt_char(CH_WRITE, chunk, response=False)
            outstanding += 1
        deadline = time.monotonic() + 5.0
        while outstanding > 0 and time.monotonic() < deadline:
            self.credit_evt.clear()
            try:
                await asyncio.wait_for(self.credit_evt.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                break
            outstanding -= 1
        return time.monotonic() - t0

    async def wait_idle(self, timeout: float = 60.0, interval: float = 0.25) -> int | None:
        """Poll 0x70 until the printer reports code 0x00 again."""
        deadline = time.monotonic() + timeout
        code = None
        while time.monotonic() < deadline:
            status = await self.query(0x70)
            if status and len(status) > 3:
                code = status[3]
                if code == 0x00:
                    return code
            await asyncio.sleep(interval)
        return code
