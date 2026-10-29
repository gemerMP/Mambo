"""Unprivileged controller of the fixed, installed TUN helper."""
import json
from pathlib import Path
import queue
import shutil
import socket
import subprocess
import threading
from .core import MamboError

HELPER = '/usr/lib/mambo/mambo-tun-helper'


def available():
    return bool(Path(HELPER).is_file() and (Path('/usr/lib/mambo/bin/sing-box').is_file() or Path('/usr/bin/sing-box').is_file()) and shutil.which('pkexec'))


class TunClient:
    def __init__(self):
        self.process = None
        self.ready = False
        self.error = None
        self.system_dns = None
        self.bridge = None
        self.events = queue.Queue()
        self.reader = None
        self.lock = threading.RLock()
        self.cancelled = False
        self.core_message = None

    def start(self, profile, rules):
        with self.lock:
            if self.cancelled:
                raise MamboError('Подключение отменено.')
            if not available():
                raise MamboError('Установи системный пакет Mambo и Polkit; затем открой приложение в графической сессии.')
            request = {'uri': profile['uri'], 'rules': rules}
            try:
                from .xray_bridge import XrayBridge
                from .endpoints import resolve
                ips=resolve(profile)
                request['server_ip']=ips[0];request['server_ips']=ips
                self.bridge=XrayBridge(getattr(self, 'event', None))
                self.bridge.start({**profile,'_endpoint_ips':ips},ips[0],profile.get('_xray_binary'),rules)
                self.process = subprocess.Popen(['/usr/bin/pkexec', '--disable-internal-agent', HELPER], stdin=subprocess.PIPE,
                                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1, start_new_session=True)
            except Exception:
                if self.bridge:self.bridge.stop()
                raise
            process = self.process
        def read_events():
            for line in process.stdout:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get('event') == 'error':
                    self.error = event.get('message', 'Ошибка TUN.')
                if event.get('event') == 'diagnostic':
                    self.core_message = event.get('message')
                    if getattr(self, 'event', None):
                        self.event(self.core_message)
                else:
                    self.events.put(event)
            self.ready = False
            self.events.put({'event': 'exit'})
        try:
            with self.lock:
                if self.cancelled:
                    raise MamboError('Подключение отменено.')
                self.reader = threading.Thread(target=read_events, daemon=True)
                self.reader.start()
                process.stdin.write(json.dumps(request) + '\n')
                process.stdin.flush()
            try:
                event = self.events.get(timeout=120)
            except queue.Empty:
                raise MamboError('Не получено подтверждение запуска VPN. Проверь окно авторизации Polkit.')
            if event.get('event') != 'ready':
                raise MamboError(self.error or 'Запуск VPN отменён или нет агента Polkit. Нужна графическая сессия с окном авторизации.')
            with self.lock:
                if self.cancelled or process.poll() is not None:
                    raise MamboError('Подключение отменено.')
                self.system_dns = event.get('system_dns')
                self.ready = True
        except Exception:
            self.stop()
            raise

    def stop(self):
        with self.lock:
            self.cancelled = True
            self._stop()
            if self.bridge:
                self.bridge.stop()
                self.bridge = None

    def _stop(self):
        if not self.process:
            return
        process = self.process
        try:
            if process.stdin:
                try:
                    process.stdin.close()  # EOF asks the privileged owner to stop gracefully.
                except (OSError, ValueError):
                    pass
            process.wait(timeout=20)
        except subprocess.TimeoutExpired as exc:
            raise MamboError('Остановка VPN ещё не подтверждена. Не закрывайте приложение; повторите отключение.') from exc
        finally:
            self.ready = False
        if self.reader:
            self.reader.join(timeout=1)
        if process.stdout:
            process.stdout.close()
        self.process = None

    def running(self):
        return self.ready and self.process is not None and self.process.poll() is None

    def diagnostic(self):
        return (self.bridge.diagnostic() if self.bridge else None) or self.core_message or self.error
