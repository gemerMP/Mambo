"""Windows sing-box controller. No Linux helper or global proxy settings."""
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
from .core import MamboError
from .tun_config import build_tun_config
from .windows import core_binary, is_admin
from .net_utils import check_local_port
from .diagnostics import CoreOutput


def available():
    return bool(core_binary('sing-box'))


def windows_config(profile, rules, server_ip, server_ips=None):
    config = build_tun_config({'uri': profile['uri'], 'rules': rules,'server_ips':server_ips or [server_ip]}, server_ip)
    tun = config['inbounds'][0]
    tun.pop('auto_redirect', None)  # Linux nftables only.
    tun['interface_name'] = 'Mambo'
    if True:
        config['outbounds'][0].pop('bind_interface', None)  # No Linux "lo" on Windows.
    return config


class TunClient:
    def __init__(self):
        self.process = None
        self.job = None
        self.bridge = None
        self.runtime = None
        self.ready = False
        self.error = None
        self.system_dns = None
        self.cancelled = False
        self.lock = threading.RLock()
        self.output = None

    def start(self, profile, rules):
        # Serializes shutdown with configuration and process startup.
        with self.lock:
            if self.cancelled:
                raise MamboError('Подключение отменено.')
            binary = core_binary('sing-box')
            if not binary:
                raise MamboError('Рядом с приложением отсутствует bin/sing-box.exe. Распакуй весь архив.')
            if not is_admin():
                raise MamboError('Для TUN запусти Mambo от имени администратора.')
            try:
                check_local_port(10808)
                check_local_port(10810)
                from .endpoints import resolve
                ips=resolve(profile);server_ip=ips[0]
                config = windows_config(profile, rules, server_ip, ips)
                self.runtime = tempfile.TemporaryDirectory(prefix='mambo-tun-')
                path = Path(self.runtime.name) / 'config.json'
                path.write_text(json.dumps(config), encoding='utf-8')
                checked = subprocess.run([binary, 'check', '-c', str(path)],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
                if checked.returncode:
                    raise MamboError('sing-box не принял конфигурацию Windows. Проверь параметры сервера.')
                if True:
                    from .xray_bridge import XrayBridge
                    self.bridge = XrayBridge(getattr(self, 'event', None))
                    self.bridge.start({**profile,'_endpoint_ips':ips}, server_ip, profile.get('_xray_binary'), rules)
                # Dedicated console allows a graceful CTRL_BREAK on shutdown.
                startup = subprocess.STARTUPINFO()
                startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startup.wShowWindow = subprocess.SW_HIDE
                self.process = subprocess.Popen([binary, 'run', '-c', str(path)],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                    creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=startup)
                self.output = CoreOutput(self.process.stdout, 'sing-box', getattr(self, 'event', None))
                from .windows_process import ChildJob
                self.job = ChildJob(self.process)
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if self.process.poll() is not None:
                        raise MamboError('Ядро VPN завершилось при запуске. Закрой другие VPN и проверь наличие wintun.dll.')
                    try:
                        with socket.create_connection(('127.0.0.1', 10808), timeout=.2) as s:
                            s.settimeout(.3)
                            s.sendall(b'\x05\x01\x00')
                            if s.recv(2) == b'\x05\x00':
                                self.ready = True
                                self.system_dns = 'windows-tun'
                                return
                    except OSError:
                        pass
                    time.sleep(.1)
                raise MamboError('Ядро VPN не запустилось вовремя.')
            except BaseException:
                self._stop()
                raise

    def _stop(self):
        self.ready = False
        if self.process:
            if self.process.poll() is None:
                from .windows_process import stop_console_process
                stop_console_process(self.process)
            if self.output:
                self.output.close()
                self.output = None
            if self.process.stdout:
                self.process.stdout.close()
            self.process = None
        if self.job:
            self.job.close()
            self.job = None
        if self.bridge:
            self.bridge.stop()
            self.bridge = None
        if self.runtime:
            self.runtime.cleanup()
            self.runtime = None

    def stop(self):
        with self.lock:
            self.cancelled = True
            self._stop()

    def running(self):
        return self.ready and self.process is not None and self.process.poll() is None

    def diagnostic(self):
        return (self.bridge.diagnostic() if self.bridge else None) or (self.output.reason() if self.output else None) or self.error
