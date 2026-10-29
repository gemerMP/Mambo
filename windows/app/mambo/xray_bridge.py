"""Unprivileged Xray bridge for VPN; root helper only runs sing-box."""
import copy
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from .core import MamboError, make_config
from .diagnostics import CoreOutput, core_reason
from .net_utils import check_local_port


class XrayBridge:
    def __init__(self, callback=None):
        self.job = None
        self.process = None
        self.runtime = None
        self.output = None
        self.callback = callback
        from .traffic import Traffic
        self.traffic = Traffic()

    def start(self, profile, server_ip, binary, rules=None):
        if not binary:
            raise MamboError('Ядро Xray не найдено. Переустанови полный пакет Mambo.')
        try:
            check_local_port(10809)
            p = copy.deepcopy(profile)
            settings = p['outbound']['settings']
            if p['protocol'] == 'vless':
                settings['vnext'][0]['address'] = server_ip
            elif p['protocol'] == 'wireguard':
                for peer, ip in zip(settings['peers'], profile.get('_endpoint_ips', [server_ip])):
                    from .wireguard import endpoint
                    _, port = endpoint(peer['endpoint'])
                    peer['endpoint'] = ('['+ip+']' if ':' in ip else ip)+':'+str(port)
            else:
                settings['servers'][0]['address'] = server_ip
            self.runtime = tempfile.TemporaryDirectory(prefix='mambo-xhttp-')
            config = make_config(p, 10809, rules)
            self.traffic.configure(config)
            config['log'] = {'loglevel': 'warning'}
            config['outbounds'][1] = {'tag': 'direct', 'protocol': 'socks', 'settings': {
                'servers': [{'address': '127.0.0.1', 'port': 10810}]}}
            file = Path(self.runtime.name)/'config.json'
            file.write_text(json.dumps(config))
            file.chmod(0o600)
            checked = subprocess.run([binary, 'run', '-test', '-config', str(file)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=12)
            if checked.returncode:
                raise MamboError(core_reason(checked.stdout, 'Xray') or 'Xray не принял VPN-профиль. Проверь параметры ссылки.')
            self.process = subprocess.Popen([binary, 'run', '-config', str(file)],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, start_new_session=True,
                creationflags=0x08000000 if os.name == 'nt' else 0)
            self.output = CoreOutput(self.process.stdout, 'Xray', self.callback)
            if os.name == 'nt':
                from .windows_process import ChildJob
                self.job = ChildJob(self.process)
            deadline = time.monotonic()+5
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    break
                try:
                    with socket.create_connection(('127.0.0.1', 10809), timeout=.2) as sock:
                        sock.settimeout(.3)
                        sock.sendall(b'\x05\x01\x00')
                        if sock.recv(2) == b'\x05\x00':
                            return
                except OSError:
                    pass
                time.sleep(.05)
            raise MamboError(self.diagnostic() or 'Не удалось запустить внутренний VPN-прокси Xray.')
        except BaseException:
            self.stop()
            raise

    def diagnostic(self):
        return self.output.reason() if self.output else None

    def stop(self):
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            if self.output:
                self.output.close()
            if self.process.stdout:
                self.process.stdout.close()
            self.process = None
        if self.job:
            self.job.close()
            self.job = None
        if self.runtime:
            self.runtime.cleanup()
            self.runtime = None
