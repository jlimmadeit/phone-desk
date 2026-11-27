"""Dispatch one browser gesture through the selected phone's paired tunnel."""
import asyncio
import sys

from pymobiledevice3.remote.core_device.hid_service import (
    HID_BUTTON_STATE_DOWN, HID_BUTTON_STATE_UP, IndigoHIDService,
    TOUCHSCREEN_STATE_CONTACT, TOUCHSCREEN_STATE_RELEASE, UniversalHIDServiceService,
)
from pymobiledevice3.tunneld.api import get_tunneld_device_by_udid


async def dispatch(uid, kind, duration, coords):
    rsd = await get_tunneld_device_by_udid(uid)
    if rsd is None:
        raise ValueError("No paired tunnel for the selected iPhone. Start tunneld on the Mac.")
    try:
        service = IndigoHIDService if kind == "home" else UniversalHIDServiceService
        if rsd.udid != uid or service.SERVICE_NAME not in rsd.peer_info["Services"]:
            raise ValueError("The selected phone does not advertise the requested HID service on this tunnel.")
        async with service(rsd) as hid:
            if kind == "home":
                await hid.send_button(0x0C, 0x40, HID_BUTTON_STATE_DOWN)
                try:
                    await asyncio.sleep(.05)
                finally:
                    await hid.send_button(0x0C, 0x40, HID_BUTTON_STATE_UP)
                await asyncio.sleep(.2)
                return
            x, y = coords[:2]
            try:
                await hid.send_touchscreen(TOUCHSCREEN_STATE_CONTACT, x, y)
                if kind == "drag":
                    steps = max(2, round(duration * 30))
                    for step in range(1, steps + 1):
                        await asyncio.sleep(duration / steps)
                        x = round(coords[0] + (coords[2] - coords[0]) * step / steps)
                        y = round(coords[1] + (coords[3] - coords[1]) * step / steps)
                        await hid.send_touchscreen(TOUCHSCREEN_STATE_CONTACT, x, y)
                else:
                    await asyncio.sleep(.08)
            finally:
                await hid.send_touchscreen(TOUCHSCREEN_STATE_RELEASE, x, y)
    finally:
        await rsd.close()


if __name__ == "__main__":
    try:
        asyncio.run(dispatch(sys.argv[1], sys.argv[2], float(sys.argv[3]), list(map(int, sys.argv[4:]))))
    except Exception as exc:
        sys.exit(str(exc) or type(exc).__name__)
