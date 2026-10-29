"""Check listeners without treating closed TCP connections as a running VPN."""
import errno
import os
import socket
from .core import MamboError


def check_local_port(port):
    if os.name == 'nt':
        # A closed Windows TCP connection may keep bind() in TIME_WAIT.
        # Probe for an actual listener; the core performs the authoritative bind.
        with socket.socket() as sock:
            sock.settimeout(.3)
            result = sock.connect_ex(('127.0.0.1', port))
        if result in (10061, errno.ECONNREFUSED):
            return
        if result == 0:
            raise MamboError(f'Локальный порт {port} занят работающим приложением. Отключи другой VPN или закрой вторую копию Mambo.')
        raise MamboError(f'Не удалось проверить локальный порт {port} (код {result}). Проверь разрешения сети.')
    try:
        with socket.socket() as sock:
            # Match Go listeners for TIME_WAIT; a live listener still fails.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('127.0.0.1', port))
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE or getattr(exc, 'winerror', None) == 10048:
            raise MamboError(f'Локальный порт {port} занят работающим приложением. Отключи другой VPN или закрой вторую копию Mambo.') from exc
        raise MamboError(f'Не удалось открыть локальный порт {port} (код {exc.errno}). Проверь разрешения сети.') from exc
