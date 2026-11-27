import asyncio
from collections import deque
import io
import json
import math
import os
import shutil
import re
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / 'build/phone-capture'


async def command(*args, timeout=12, env=None):
    proc = await asyncio.create_subprocess_exec(*map(str, args), stdout=-1, stderr=-1, env=env)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
    if proc.returncode:
        detail = err.decode(errors='replace')
        description = re.search(r"['\"]NSLocalizedDescription['\"]\s*:\s*['\"]([^'\"\r\n]+)", detail)
        if description:
            raise ValueError(description[1][:250])
        lines = [line.strip() for line in detail.splitlines() if line.strip() and '\\x' not in line]
        raise ValueError(lines[-1][-250:] if lines else 'Device command failed.')
    return out


def gesture(kind, points, duration=.3):
    count = {'home': 0, 'tap': 2, 'drag': 4}.get(kind)
    if count is None or not isinstance(points, list) or len(points) != count:
        raise ValueError('Invalid gesture.')
    if any(type(v) not in (int, float) or not 0 <= v <= 1 for v in points):
        raise ValueError('Touch is outside the screen.')
    if type(duration) not in (float, int) or not .05 <= duration <= 2:
        raise ValueError('Invalid drag duration.')
    return [str(round(v*65535)) for v in points]


class TouchUnavailable(ValueError):
    """The device explicitly rejected this input method for its OS version."""


class Phone:
    def __init__(self, uid, name, source=None, demo=False):
        self.uid, self.name, self.source, self.demo = uid, name, source, demo
        self.session = uuid.uuid4().hex
        self.frame = b''
        self.samples = deque(maxlen=3)
        self.frame_event = asyncio.Event()
        self.frame_at = 0
        self.connected = True
        self.index = 1
        self.screen = 'Home'
        self.touch_blocker = ''
        self.touch_state = 'Demo' if demo else 'Untested'
        self.lock = asyncio.Lock()
        self.capture_task = None
        self.error = ''
        if demo:
            self.render()

    def render(self):
        from PIL import Image, ImageDraw, ImageFont
        im = Image.new('RGB', (360, 720), '#12282c')
        d = ImageDraw.Draw(im)
        def label(x, y, s, size, fill='white'):
            try:
                font = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', size)
            except OSError:
                font = ImageFont.load_default()
            d.text((x, y), s, font=font, fill=fill)
        label(24, 24, 'SANDBOX PHONE', 13, '#9ef2bf')
        label(24, 95, self.screen, 38)
        if self.screen == 'Home':
            for y, title in [(245,'First video'), (485,'Shorts')]:
                d.rounded_rectangle((24,y,336,y+106), radius=18, fill='#285054')
                label(46,y+34,title,25)
        else:
            for i in range(7):
                y = 235 + i*33
                x = 30 + round(18*math.sin(i+self.index))
                d.rounded_rectangle((x,y,330-x//2,y+20), 10, fill=['#49918c','#e4aa67','#78b780'][(self.index+i)%3])
            label(24, 547, f'Clip {self.index:02d}' if self.screen=='Shorts' else 'Playing video', 31)
            label(24, 654, 'Back to home', 18, '#9ef2bf')
        buf = io.BytesIO()
        im.save(buf, format='JPEG', quality=82)
        self.frame, self.frame_at = buf.getvalue(), time.monotonic()

    def fresh(self):
        return self.connected and bool(self.frame) and (self.demo or time.monotonic()-self.frame_at < 3)

    async def control(self, kind, points, duration=.3):
        if self.touch_blocker:
            raise TouchUnavailable(self.touch_blocker)
        coords = gesture(kind, points, duration)
        if not self.fresh():
            raise ValueError('Waiting for a fresh phone preview.')
        if self.demo:
            if kind=='home':
                self.screen = 'Home'
            elif kind=='tap':
                if self.screen=='Home':
                    self.screen = 'Shorts' if points[1]>.55 else 'Video'
                elif points[1]>.83:
                    self.screen='Home'
            elif self.screen=='Shorts':
                self.index=max(1, self.index+(1 if points[3]<points[1] else -1))
            self.render()
            return
        if kind not in ('home', 'tap', 'drag') or not self.source:
            raise ValueError('Choose a visible target on the connected iPhone.')
        import sys
        station_python = Path.home() / 'iphone-station/.venv/bin/python'
        python = station_python if station_python.is_file() else sys.executable
        await command(python, ROOT / 'server/hid_input.py', self.uid, kind,
                      str(duration), *coords, timeout=25)
        self.touch_state = 'Sent'

    async def observe(self, after=None):
        while self.connected and (not self.fresh() or (after is not None and self.frame_at <= after)):
            self.frame_event.clear()
            await self.frame_event.wait()
        if not self.connected:
            raise ValueError('Phone disconnected.')
        return self.frame

    async def capture(self):
        while self.connected:
            try:
                await self.capture_stream()
            except (OSError, ValueError, asyncio.TimeoutError, asyncio.IncompleteReadError):
                self.frame_at = 0
                self.samples.clear()
                self.error = 'Reconnecting the live screen…'
                await asyncio.sleep(1)

    async def capture_stream(self):
        proc = await asyncio.create_subprocess_exec(str(CAPTURE),'stream',self.source, stdout=-1)
        try:
            while True:
                length = int.from_bytes(await asyncio.wait_for(proc.stdout.readexactly(4),12),'big')
                if not 0 < length <= 8_000_000:
                    raise ValueError('Invalid capture frame')
                self.frame = await asyncio.wait_for(proc.stdout.readexactly(length),4)
                self.frame_at = time.monotonic()
                if not self.samples or self.frame_at-self.samples[-1][0] >= 1:
                    self.samples.append((self.frame_at, self.frame))
                self.error = ''
                self.frame_event.set()
        finally:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()


async def discover(active, diagnostics):
    report = await command('/usr/sbin/ioreg', '-r', '-c', 'IOUSBHostDevice', '-d', '1', '-l', '-w0')
    phones = {}
    for device in report.decode(errors='replace').split('+-o ')[1:]:
        name = re.search(r'"USB Product Name" = "(iPhone|iPad|iPod[^"]*)"', device)
        serial = re.search(r'"USB Serial Number" = "([a-fA-F0-9-]+)"', device)
        if name and serial:
            uid = serial[1]
            if len(uid) == 24 and '-' not in uid:
                uid = uid[:8] + '-' + uid[8:]
            phones[uid] = (name[1], active.get(uid))
    if all(source for _, source in phones.values()):
        return phones
    try:
        sources = json.loads(await command(CAPTURE, 'list'))
    except (ValueError, OSError, asyncio.TimeoutError) as exc:
        diagnostics.append(str(exc) or 'Screen discovery timed out.')
        return phones
    overrides = json.loads(os.getenv('PHONE_CAPTURE_MAP', '{}'))
    normalize = lambda s: s.replace('-', '').lower()
    used = set()
    for uid, (name, source) in phones.items():
        expected = normalize(overrides.get(uid, uid))
        matches = [s for s in sources if normalize(s['id']) == expected]
        if len(matches) == 1:
            source = matches[0]['id']
            phones[uid] = (matches[0]['name'], source)
        if source:
            if source in used:
                raise ValueError('Duplicate wired screen binding.')
            used.add(source)
    return phones
