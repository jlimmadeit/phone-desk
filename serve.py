"""Run the local dashboard and reload it when its server or capture code changes."""
import fcntl
import os
from pathlib import Path
import socket
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
NATIVE = ('capture/main.swift', 'capture/Info.plist', 'build-capture.sh')


def revision():
    paths = [ROOT / 'app.py', *(ROOT / name for name in NATIVE),
             *(ROOT / 'server').glob('*.py'), *(ROOT / 'server/skills').glob('*.md')]
    return {p: p.stat().st_mtime_ns for p in paths if p.is_file()}


def stop(child):
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def listener(port):
    result = subprocess.run(['/usr/sbin/lsof', '-nP', '-a', f'-iTCP:{port}',
                             '-sTCP:LISTEN', '-Fp'], capture_output=True, text=True)
    pids = [int(line[1:]) for line in result.stdout.splitlines() if line.startswith('p')]
    if len(pids) > 1:
        raise RuntimeError(f'Multiple services use port {port}.')
    return pids[0] if pids else None


def prepare_port(port):
    pid = listener(port)
    if pid is None:
        return
    files = subprocess.run(['/usr/sbin/lsof','-p',str(pid),'-Fn'], capture_output=True,
                           text=True).stdout.splitlines()
    if 'n'+str(ROOT/'build/history.sqlite') not in files:
        raise RuntimeError(f'Another application owns port {port} (PID {pid}).')
    # Verify that this launch context can listen before retiring a working server.
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        probe.listen()
    if listener(port) != pid:
        raise RuntimeError('Port ownership changed during startup. Run the launcher again.')
    print(f'Restarting the existing Phone Desk on port {port}…', flush=True)
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        owner = listener(port)
        if owner is None:
            return
        if owner != pid:
            break
        time.sleep(.1)
    raise RuntimeError(f'Port {port} is still occupied.')


def main():
    port = int(os.getenv('PORT','8766'))
    (ROOT/'build').mkdir(exist_ok=True)
    with (ROOT/'build'/f'launcher-{port}.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f'Phone Desk launcher is already running at http://127.0.0.1:{port}')
            return 0
        prepare_port(port)
        return supervise()


def supervise():
    current = revision()
    child = subprocess.Popen([sys.executable, 'app.py'], cwd=ROOT)
    try:
        while child.poll() is None:
            time.sleep(.5)
            new = revision()
            if new == current:
                continue
            # Editors may save several files together.
            time.sleep(.5)
            new = revision()
            try:
                for p in new:
                    if p.suffix == '.py':
                        compile(p.read_bytes(), str(p), 'exec')
                if any(new.get(ROOT / n) != current.get(ROOT / n) for n in NATIVE):
                    subprocess.run([str(ROOT / 'build-capture.sh')], cwd=ROOT, check=True)
            except (SyntaxError, OSError, subprocess.CalledProcessError) as exc:
                print(f'Reload deferred: {exc}', file=sys.stderr, flush=True)
                # Retry after the next source edit; keep serving the current process.
                while child.poll() is None and revision() == new:
                    time.sleep(.5)
                continue
            stop(child)
            print('Reloading Phone Desk…', flush=True)
            current = new
            child = subprocess.Popen([sys.executable, 'app.py'], cwd=ROOT)
        return child.returncode
    finally:
        stop(child)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        sys.exit(main())
    except (OSError, RuntimeError) as exc:
        sys.exit(f'Phone Desk startup: {exc}')
    except KeyboardInterrupt:
        pass
