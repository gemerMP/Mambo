"""Root-owned helper invoked by pkexec. No user-supplied executable/config paths."""
import fcntl
import json
import os
from pathlib import Path
import select
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from .core import MamboError, parse_uri
from .tun_config import build_tun_config
from . import system_dns
from .diagnostics import CoreOutput, core_reason
from .net_utils import check_local_port

EVENT_LOCK = threading.Lock()


def trusted_file(path):
    path = Path(path).resolve()
    for item in (path, *path.parents):
        info = item.stat()
        if info.st_uid != 0 or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            return False
    return path.is_file()


def emit(event, **values):
    with EVENT_LOCK:
        print(json.dumps({'event': event, **values}), flush=True)


def main():
    child = None
    output = None
    try:
        if os.geteuid() != 0 or not os.environ.get('PKEXEC_UID', '').isdigit() or int(os.environ['PKEXEC_UID']) == 0:
            raise MamboError('TUN запускается через системное окно авторизации.')
        binary = '/usr/lib/mambo/bin/sing-box' if Path('/usr/lib/mambo/bin/sing-box').is_file() else '/usr/bin/sing-box'
        if not trusted_file(binary) or not trusted_file(__file__):
            raise MamboError('Установите Mambo и sing-box в системные каталоги.')
        # One TUN owner on this machine. Other Mambo instances cannot stop it.
        lock_fd = os.open('/run/mambo-tun.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(lock_fd, 'w') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise MamboError('VPN Mambo уже запущен в другой сессии.')
            line = sys.stdin.buffer.readline(65537)
            if len(line) > 65536 or not line.endswith(b'\n'):
                raise MamboError('Некорректный запрос TUN.')
            request = json.loads(line)
            profile = parse_uri(request['uri'])
            addresses = socket.getaddrinfo(profile['host'], profile['port'], type=socket.SOCK_STREAM) if 'server_ip' not in request else [(socket.AF_INET,0,0,'',(request['server_ip'],profile['port']))]
            if not addresses:
                raise MamboError('Не удалось определить адрес сервера.')
            # Resolve before switching routes; prefer IPv4 when both exist.
            addresses.sort(key=lambda a: a[0] != socket.AF_INET)
            config = build_tun_config(request, addresses[0][4][0])
            check_local_port(10808)
            check_local_port(10810)
            if Path('/sys/class/net/mambo0').exists():
                raise MamboError('Интерфейс mambo0 уже существует.')
            def stop_signal(*_):
                raise KeyboardInterrupt
            signal.signal(signal.SIGTERM, stop_signal)
            signal.signal(signal.SIGINT, stop_signal)
            with tempfile.TemporaryDirectory(prefix='mambo-tun-', dir='/run') as runtime:
                config_file = Path(runtime) / 'config.json'
                config_file.write_text(json.dumps(config), encoding='utf-8')
                config_file.chmod(0o600)
                env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}
                result = subprocess.run([binary, 'check', '-c', str(config_file)], stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, timeout=15, env=env)
                if result.returncode:
                    raise MamboError(core_reason(result.stdout, 'sing-box') or 'sing-box не принял профиль. Переустанови полный пакет Mambo.')
                child = subprocess.Popen([binary, 'run', '-c', str(config_file)], stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, bufsize=1,
                                         stdin=subprocess.DEVNULL, start_new_session=True, env=env)
                output = CoreOutput(child.stdout, 'sing-box', lambda message: emit('diagnostic', message=message))
                try:
                    deadline = time.monotonic() + 12
                    while time.monotonic() < deadline:
                        if child.poll() is not None:
                            output.close()
                            raise MamboError(output.reason() or 'Ядро завершилось при создании TUN. Проверьте другой VPN и /dev/net/tun.')
                        if Path('/sys/class/net/mambo0').exists():
                            try:
                                with socket.create_connection(('127.0.0.1', 10808), timeout=.2) as s:
                                    s.settimeout(.2)
                                    s.sendall(b'\x05\x01\x00')
                                    if s.recv(2) == b'\x05\x00':
                                        break
                            except OSError:
                                pass
                        time.sleep(.1)
                    else:
                        raise MamboError('TUN не запустился вовремя.')
                    dns_status = system_dns.configure()
                    emit('ready', system_dns=dns_status)
                    # A pipe is the lease: EOF, STOP, or a dead child means cleanup.
                    while child.poll() is None:
                        readable, _, _ = select.select([sys.stdin.buffer], [], [], .5)
                        if readable and os.read(sys.stdin.fileno(), 4096) != b'PING\n':
                            break
                    if child.poll() is not None:
                        output.close()
                        emit('error', message=output.reason() or 'Ядро VPN завершило работу.')
                finally:
                    system_dns.revert()
                    if child.poll() is None:
                        child.terminate()
                        try:
                            child.wait(timeout=8)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait()
                    output.close()
                    child.stdout.close()
                    child = None
            emit('stopped')
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        message = str(exc) if isinstance(exc, MamboError) else 'Не удалось запустить TUN. Проверьте sing-box, сеть и свободный порт 10808.'
        emit('error', message=message)
        return 1
    finally:
        if child:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            if output:
                output.close()
            if child.stdout:
                child.stdout.close()
    return 0
