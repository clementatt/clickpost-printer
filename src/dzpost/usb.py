"""USB transport (HID interrupt interface 1).

macOS refuses non-HID claims from unprivileged processes, so this path needs
``sudo``; Linux needs the usual udev rule::

    SUBSYSTEM=="usb", ATTRS{idVendor}=="3533", ATTRS{idProduct}=="5c32", MODE="0666"
"""

from __future__ import annotations

import time

from .protocol import mgmt, usb_reports, varbytes

__all__ = ["UsbPrinter", "VID", "PID", "MAX_REPORT_PAYLOAD"]

VID, PID = 0x3533, 0x5C32
MAX_REPORT_PAYLOAD = 62  # 64-byte HID report minus the 0x1e id and length byte


class UsbPrinter:
    def __init__(self, vid: int = VID, pid: int = PID):
        import usb.core
        import usb.util

        self.usb = usb.core
        self.util = usb.util
        self.dev = usb.core.find(idVendor=vid, idProduct=pid)
        if self.dev is None:
            raise SystemExit(
                f"printer {vid:04x}:{pid:04x} not found on USB "
                "(on macOS run with sudo)")
        self.dev.set_configuration()
        self.iface_no = self._pick_interface()
        self.iface = self.dev.get_active_configuration()[self.iface_no]
        self.ep_out = next(e for e in self.iface if not e.bEndpointAddress & 0x80)
        self.ep_in = next(e for e in self.iface if e.bEndpointAddress & 0x80)
        try:
            if self.dev.is_kernel_driver_active(self.iface_no):
                self.dev.detach_kernel_driver(self.iface_no)
        except Exception:
            pass
        usb.util.claim_interface(self.dev, self.iface_no)
        self._drain()

    def _pick_interface(self) -> int:
        """Only the HID interrupt interface answers the protocol (interface 1)."""
        util = self.util
        for setting in self.dev.get_active_configuration():
            endpoints = list(setting)
            if not endpoints:
                continue
            if all(util.endpoint_type(e.bmAttributes) == util.ENDPOINT_TYPE_INTR
                   for e in endpoints):
                return setting.bInterfaceNumber
        raise SystemExit("no interrupt interface on this device")

    def _drain(self, timeout: int = 50) -> None:
        while True:
            try:
                if not self.ep_in.read(64, timeout=timeout):
                    break
            except self.usb.core.USBError:
                break

    def _write(self, payload: bytes, retries: int = 3) -> None:
        for attempt in range(retries):
            try:
                self.ep_out.write(b"\x1e" + varbytes(len(payload)) + payload,
                                  timeout=8000)
                return
            except self.usb.core.USBTimeoutError:
                if attempt == retries - 1:
                    raise
                time.sleep(0.05)

    def send(self, stream: bytes) -> float:
        t0 = time.monotonic()
        for report in usb_reports(stream, MAX_REPORT_PAYLOAD):
            self.ep_out.write(report, timeout=8000)
        return time.monotonic() - t0

    def query(self, typ: int, timeout: int = 600) -> bytes | None:
        self._drain()
        self._write(mgmt(0x1F, typ))
        data = b""
        while True:
            try:
                chunk = self.ep_in.read(64, timeout=timeout)
            except self.usb.core.USBError:
                break
            if not chunk:
                break
            data += bytes(chunk)
        off = 0
        while off < len(data):
            if data[off] != 0x1E:
                off += 1
                continue
            head = data[off + 1]
            if head & 0xC0 == 0xC0:
                length, nb = ((head & 0x3F) << 8) | data[off + 2], 2
            else:
                length, nb = head, 1
            start = off + 1 + nb
            if start + length > len(data):
                break
            return data[start:start + length]
        return None

    def close(self) -> None:
        try:
            self.util.release_interface(self.dev, self.iface_no)
        except Exception:
            pass
        try:
            self.util.dispose_resources(self.dev)
        except Exception:
            pass
