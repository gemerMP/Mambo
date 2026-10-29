"""Shared profile parsing, storage, configuration and Xray lifecycle."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager


class MamboError(ValueError):
    pass


def decode64(value):
    try:
        return base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True).decode('utf-8-sig')
    except (ValueError, UnicodeError) as exc:
        raise MamboError('Не удалось прочитать Base64.') from exc


def parse_uri(uri):
    """Conservative import: unsupported parameters fail instead of disappearing."""
    uri = uri.strip().lstrip("\ufeff")
    if uri.lower().startswith(("wg://", "wireguard://")) or "[interface]" in uri.lower():
        from .wireguard import parse
        return parse(uri)
    if not uri or len(uri) > 16384:
        raise MamboError('Пустая или слишком длинная ссылка.')
    try:
        u = urllib.parse.urlsplit(uri)
        if u.scheme not in ('vless', 'trojan'):
            raise MamboError('В этой альфе поддерживаются ссылки VLESS и Trojan.')
        if not u.hostname or not u.port or not u.username or u.password is not None:
            raise MamboError('В ссылке нужны ключ, адрес и порт сервера.')
        if u.path not in ('', '/'):
            raise MamboError('Путь транспорта задаётся параметром path.')
        pairs = urllib.parse.parse_qs(u.query, keep_blank_values=True)
        allowed = {'type', 'security', 'encryption', 'flow', 'sni', 'fp', 'pbk', 'sid', 'spx', 'path', 'host', 'serviceName', 'alpn', 'mode', 'extra', 'x_padding_bytes'}
        if pairs.get('type', ['tcp'])[0] not in ('tcp', 'raw', 'ws', 'grpc', 'xhttp', 'httpupgrade'):
            raise MamboError('Транспорт не поддерживается: доступны TCP, WebSocket, gRPC и XHTTP.')
        if set(pairs) - allowed or any(len(v) != 1 for v in pairs.values()):
            raise MamboError('Ссылка содержит неподдерживаемые или повторяющиеся параметры. Импорт отменён.')
        q = {k: v[0] for k, v in pairs.items()}
        transport = q.get('type', 'tcp')
        if transport != 'xhttp' and set(q) & {'mode','extra','x_padding_bytes'}:
            raise MamboError('Параметры XHTTP указаны для другого транспорта.')
        security = q.get('security', 'tls' if u.scheme == 'trojan' else 'none')
        if transport not in ('tcp', 'raw', 'ws', 'grpc', 'xhttp', 'httpupgrade'):
            raise MamboError('Поддерживаются TCP, WebSocket, gRPC и XHTTP.')
        if security not in ('none', 'tls', 'reality') or (u.scheme == 'trojan' and security == 'none'):
            raise MamboError('Неподдерживаемая защита транспорта.')
        if security == 'reality' and (not q.get('pbk') or not q.get('sni') or transport == 'ws'):
            raise MamboError('Для REALITY нужны pbk и sni; WebSocket не поддерживается.')
        if q.get('flow', '') not in ('', 'xtls-rprx-vision') or (q.get('flow') and (transport not in ('tcp', 'raw') or security == 'none' or u.scheme != 'vless')):
            raise MamboError('Несовместимый flow или транспорт.')
        if q.get('encryption', 'none') != 'none':
            raise MamboError('Эта версия поддерживает VLESS encryption=none.')
        secret = urllib.parse.unquote(u.username)
        if u.scheme == 'vless':
            secret = str(uuid.UUID(secret))
        name = urllib.parse.unquote(u.fragment) or u.hostname
        if any(ord(c) < 32 for c in name + u.hostname):
            raise MamboError('Недопустимые символы в имени или адресе.')
        stream = {'network': 'tcp' if transport == 'raw' else transport, 'security': security}
        if security == 'tls':
            stream['tlsSettings'] = {'serverName': (q.get('sni') or u.hostname), 'allowInsecure': False}
            if q.get('fp'):
                stream['tlsSettings']['fingerprint'] = q['fp']
            if q.get('alpn'):
                stream['tlsSettings']['alpn'] = q['alpn'].split(',')
        if security == 'reality':
            stream['realitySettings'] = {'serverName': q['sni'], 'fingerprint': q.get('fp', 'chrome'), 'publicKey': q['pbk'], 'shortId': q.get('sid', ''), 'spiderX': q.get('spx', '/')}
        if transport == 'ws':
            stream['wsSettings'] = {'path': (q.get('path') or '/'), 'headers': {'Host': (q.get('host') or q.get('sni') or u.hostname)}}
        elif transport == 'httpupgrade':
            stream['httpupgradeSettings']={'path':q.get('path','/'),'host':q.get('host') or q.get('sni') or u.hostname}
        elif transport == 'xhttp':
            from .xhttp import settings as xhttp_settings
            stream['xhttpSettings'] = xhttp_settings(q)
        elif transport == 'grpc':
            stream['grpcSettings'] = {'serviceName': q.get('serviceName', '')}
        if u.scheme == 'vless':
            user = {'id': secret, 'encryption': 'none'}
            if q.get('flow'):
                user['flow'] = q['flow']
            settings = {'vnext': [{'address': u.hostname, 'port': u.port, 'users': [user]}]}
        else:
            settings = {'servers': [{'address': u.hostname, 'port': u.port, 'password': secret}]}
        return {'id': hashlib.sha256(uri.split('#')[0].encode()).hexdigest()[:16], 'name': name[:120], 'host': u.hostname, 'port': u.port, 'protocol': u.scheme, 'transport': transport, 'security': security, 'uri': uri, 'outbound': {'tag': 'proxy', 'protocol': u.scheme, 'settings': settings, 'streamSettings': stream}}
    except MamboError:
        raise
    except (ValueError, TypeError) as exc:
        raise MamboError('Некорректный адрес, UUID или порт в ссылке.') from exc


def parse_bundle(text):
    if not isinstance(text, str) or len(text.encode()) > 1024 * 1024:
        raise MamboError('Допустимо до 1 МБ текста.')
    text = text.strip().lstrip('\ufeff')
    if '[interface]' in text.lower():
        return [parse_uri(text)]
    if '://' not in text:
        text = decode64(''.join(text.split()))
    if '[interface]' in text.lower():return [parse_uri(text)]
    lines = [x.strip() for x in text.splitlines() if x.strip() and not x.strip().startswith('#')]
    if not 1 <= len(lines) <= 200:
        raise MamboError('Нужно от 1 до 200 ссылок.')
    return [parse_uri(line) for line in lines]


class HTTPSOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != 'https':
            raise MamboError('Подписка перенаправляет на незащищённый адрес.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_subscription(url):
    u = urllib.parse.urlsplit(url)
    if u.scheme != 'https' or not u.hostname or u.username or u.password:
        raise MamboError('Для подписки нужен HTTPS-адрес без логина в URL.')
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), HTTPSOnly())
        with opener.open(urllib.request.Request(url, headers={'User-Agent': 'Mambo/0.3'}), timeout=15) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise MamboError('Подписка больше 1 МБ.')
        return raw.decode('utf-8-sig')
    except MamboError:
        raise
    except Exception as exc:
        raise MamboError('Не удалось скачать подписку. Проверьте адрес и доступность провайдера.') from exc


def default_home():
    root = os.environ.get('LOCALAPPDATA') if os.name == 'nt' else os.environ.get('XDG_CONFIG_HOME')
    return Path(root or Path.home() / '.config') / 'mambo'


class Store:
    def __init__(self, home=None):
        self.home = Path(home) if home else default_home()
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.home / 'profiles.sqlite3'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS profiles (id TEXT PRIMARY KEY, data TEXT NOT NULL, favorite INTEGER NOT NULL DEFAULT 0)')
            db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def import_text(self, text):
        profiles = parse_bundle(text)  # All-or-nothing validation before writes.
        with self.connect() as db:
            for p in profiles:
                db.execute('INSERT INTO profiles(id,data) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data', (p['id'], json.dumps(p)))
        return len({p['id'] for p in profiles})

    def import_subscription(self, text):
        if not isinstance(text, str) or len(text.encode()) > 1024 * 1024:
            raise MamboError('Допустимо до 1 МБ текста.')
        text = text.strip().lstrip('\ufeff')
        if '[interface]' in text.lower():
            return {'count': self.import_text(text), 'skipped': []}
        if '://' not in text:
            text = decode64(''.join(text.split()))
        if '[interface]' in text.lower():return {'count':self.import_text(text),'skipped':[]}
        lines = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith('#')]
        if not 1 <= len(lines) <= 200:
            raise MamboError('Нужно от 1 до 200 ссылок.')
        accepted, skipped = [], []
        for index, line in enumerate(lines, 1):
            try:
                parse_uri(line)
                accepted.append(line)
            except MamboError as exc:
                skipped.append({'index': index, 'reason': str(exc)})
        if not accepted:
            raise MamboError('Нет совместимых профилей. ' + skipped[0]['reason'])
        return {'count': self.import_text('\n'.join(accepted)), 'skipped': skipped}

    def list(self):
        with self.connect() as db:
            return [{**json.loads(data), 'favorite': bool(fav)} for data, fav in db.execute('SELECT data,favorite FROM profiles ORDER BY favorite DESC,rowid')]

    def public(self):
        return [{k: v for k, v in p.items() if k not in ('uri', 'outbound')} for p in self.list()]

    def get(self, ident):
        for p in self.list():
            if p['id'] == ident:
                # Rebuild cached configuration so parser fixes apply to existing profiles.
                return {**parse_uri(p['uri']), 'favorite': p['favorite']}
        raise MamboError('Сервер не найден.')

    def favorite(self, ident, enabled):
        self.get(ident)
        with self.connect() as db:
            db.execute('UPDATE profiles SET favorite=? WHERE id=?', (int(bool(enabled)), ident))

    def delete(self, ident):
        self.get(ident)
        with self.connect() as db:
            db.execute('DELETE FROM profiles WHERE id=?', (ident,))

    def rules(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key='rules'").fetchone()
        return json.loads(row[0]) if row else {'direct': [], 'block': []}

    def save_rules(self, value):
        from .routing import validate
        value = validate(value)
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES ('rules',?)", (json.dumps(value),))


def make_config(profile, port=10808, rules=None):
    from .routing import config
    return config(profile, port, rules)


def probe(profile, timeout=2):
    if profile['protocol'] == 'wireguard':
        return {'id':profile['id'], 'tcp_ms':None,'reachable':False,'reason':'TCP неприменим к WireGuard (UDP). Используй Proxy GET/HEAD.'}
    start = time.monotonic()
    try:
        with socket.create_connection((profile['host'], profile['port']), timeout=timeout):
            return {'id': profile['id'], 'tcp_ms': round((time.monotonic() - start) * 1000), 'reachable': True}
    except OSError:
        return {'id': profile['id'], 'tcp_ms': None, 'reachable': False}


class Engine:
    def __init__(self, store, executable=None, port=10808):
        if not isinstance(port, int) or not 1024 <= port <= 65535:
            raise MamboError('SOCKS-порт должен быть от 1024 до 65535.')
        self.store, self.executable, self.port = store, executable, port
        self.process = None
        self.runtime = None
        self.active = None
        self.started = None
        self.started_monotonic = None
        self.error = None
        self.tun = None
        self.scope = 'socks'
        self.internet = None
        self.lock = threading.RLock()
        from .traffic import Traffic
        self.traffic = Traffic()
        self.output = None

    def event(self, text):
        from .journal import append
        append(self.store.home, text)

    def refresh_traffic(self):
        with self.lock:
            source = self.tun.bridge.traffic if self.tun and self.tun.bridge else self.traffic
            if self.process or (self.tun and self.tun.running()):
                result = source.read()
                self.traffic.values = result.copy()
            return self.traffic.values.copy()

    def binary(self):
        candidate = self.executable or os.environ.get('MAMBO_XRAY')
        if candidate:
            return shutil.which(candidate)
        if os.name == 'nt':
            from .windows import core_binary
            bundled = core_binary('xray')
            if bundled:
                return bundled
        bundled = Path(__file__).resolve().parents[1] / 'bin' / 'xray'
        if bundled.is_file(): return str(bundled)
        local = self.store.home / 'bin' / ('xray.exe' if os.name == 'nt' else 'xray')
        return shutil.which(str(local)) or shutil.which('xray')

    def status(self):
        with self.lock:
            if os.name == 'nt':
                from .windows_tun import available
            else:
                from .tun_client import available
            if self.tun and getattr(self.tun, 'bridge', None) and self.tun.bridge.process and self.tun.bridge.process.poll() is not None:
                self.stop()
                self.error = 'Ядро Xray завершило работу.'
            if self.tun and self.tun.process and self.tun.process.poll() is not None:
                message = self.tun.error or 'Ядро VPN завершило работу.'
                self.stop()
                self.error = message
            if self.process and self.process.poll() is not None:
                self.stop()
                self.error = 'Ядро завершило работу. Проверьте профиль и повторите подключение.'
            pending = bool(self.tun and not self.tun.ready)
            running = self.process is not None or bool(self.tun and self.tun.running())
            uptime = max(0.0, time.monotonic() - self.started_monotonic) if running and self.started_monotonic is not None else 0.0
            return {'running': running, 'active': self.active, 'uptime_seconds': uptime,
                    'started': self.started, 'socks_port': self.port, 'engine_available': bool(self.binary()),
                    'error': self.error, 'scope': self.scope, 'tun_available': available(), 'tun_pending': pending,
                    'internet': self.internet, 'system_dns': getattr(self.tun, 'system_dns', None),
                    'traffic': self.traffic.values.copy()}

    def start(self, ident, mode='socks'):
        if mode == 'tun':
            return self.start_tun(ident)
        with self.lock:
            if self.process or self.tun is not None:
                raise MamboError('Сначала отключите текущий сервер.')
            profile = self.store.get(ident)
            if mode not in ('socks', 'tun'):
                raise MamboError('Неизвестный режим подключения.')
            self.internet = None
            self.scope = mode
            binary = self.binary()
            if not binary:
                raise MamboError('Xray не найден. Установите ядро и задайте MAMBO_XRAY или добавьте его в PATH.')
            # Detect a busy port before starting. No global proxy settings changed.
            from .net_utils import check_local_port
            check_local_port(self.port)
            if profile['protocol'] == 'wireguard':
                from .endpoints import pin_wireguard
                profile = pin_wireguard(profile)
                self.event('WireGuard: Endpoint разрешён до запуска туннеля · пиров '+str(len(profile['outbound']['settings']['peers']))+' · MTU '+str(profile['outbound']['settings']['mtu']))
            self.runtime = tempfile.TemporaryDirectory(prefix='mambo-', dir=self.store.home)
            config = Path(self.runtime.name) / 'config.json'
            config.write_text(json.dumps(self.traffic.configure(make_config(profile, self.port, self.store.rules()))), encoding='utf-8')
            os.chmod(config, 0o600)
            self.event('Запуск SOCKS · '+profile['protocol'].upper())
            try:
                result = subprocess.run([binary, 'run', '-test', '-config', str(config)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=12)
                if result.returncode:
                    raise MamboError('Xray не принял конфигурацию. Проверьте совместимость версии ядра и параметров ссылки.')
                self.process = subprocess.Popen([binary, 'run', '-config', str(config)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True, creationflags=0x08000000 if os.name == 'nt' else 0)
                from .diagnostics import CoreOutput
                self.output = CoreOutput(self.process.stdout, 'Xray', self.event)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if self.process.poll() is not None:
                        raise MamboError('Xray завершился при запуске.')
                    try:
                        with socket.create_connection(('127.0.0.1', self.port), timeout=0.15) as s:
                            s.settimeout(0.3)
                            s.sendall(b'\x05\x01\x00')
                            if s.recv(2) == b'\x05\x00':
                                self.active, self.started, self.error = ident, time.time(), None
                                self.started_monotonic = time.monotonic()
                                self.event('SOCKS запущен · порт '+str(self.port))
                                return self.status()
                    except OSError:
                        pass
                    time.sleep(0.05)
                raise MamboError('Локальный SOCKS-прокси не запустился вовремя.')
            except Exception:
                self.stop()
                raise

    def start_tun(self, ident):
        if os.name == 'nt':
            from .windows_tun import TunClient
        else:
            from .tun_client import TunClient
        with self.lock:
            if self.process or self.tun is not None:
                raise MamboError('Сначала отключите текущий сервер.')
            if self.port != 10808:
                raise MamboError('TUN использует локальный порт 10808.')
            profile = self.store.get(ident)
            controller = TunClient()
            controller.event = self.event
            self.tun = controller
            self.scope, self.internet = 'tun', None
        # Do not hold the state lock while the user answers the Polkit dialog.
        try:
            self.event('Запуск системного VPN · '+profile['protocol'].upper())
            controller.start({**profile, '_xray_binary': self.binary()}, self.store.rules())
        except Exception:
            with self.lock:
                if self.tun is controller and controller.process is None:
                    self.tun = None
            raise
        with self.lock:
            if self.tun is not controller or not controller.running():
                controller.stop()
                raise MamboError('Подключение отменено.')
            self.active, self.started, self.error = ident, time.time(), None
            self.started_monotonic = time.monotonic()
            self.traffic.reset()
            self.event('TUN запущен · '+profile['protocol'].upper()+' · DNS: '+str(getattr(controller, 'system_dns', None)))
            return self.status()

    def stop(self):
        with self.lock:
            was_running = self.process is not None or self.tun is not None
            elapsed = max(0, int(time.monotonic()-self.started_monotonic)) if self.started_monotonic else 0
            if was_running:
                self.refresh_traffic()
            if self.tun:
                self.tun.stop()
                self.tun = None
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
                    self.output = None
                if self.process.stdout:
                    self.process.stdout.close()
                self.process = None
            if self.runtime:
                self.runtime.cleanup()
                self.runtime = None
            self.active = self.started = self.started_monotonic = None
            self.error = None
            self.internet = None
            self.traffic.values.update(upload_rate=0, download_rate=0)
            if was_running:
                t = self.traffic.values
                self.event(f"VPN остановлен · {elapsed} с · загружено {t['downloaded']} Б · выгружено {t['uploaded']} Б")

    def check_internet(self):
        from .connectivity import check_access, check_system_https
        with self.lock:
            if not self.status()['running']:
                raise MamboError('Сначала подключитесь к серверу.')
            active = (self.active, self.started)
            scope = self.scope
            controller = self.tun
        if scope == 'tun':
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=2) as pool:
                system = pool.submit(check_system_https)
                result = check_access(self.port)
                # Same Xray process, including WireGuard. Never create a second
                # tunnel with the same WireGuard key to diagnose a live VPN.
                if not result['ok'] and controller and getattr(controller, 'bridge', None):
                    result['xray'] = check_access(10809)
                result['system'] = system.result()
            if controller:
                message = getattr(controller, 'diagnostic', lambda: None)()
                if message and not (result['ok'] and result['system'].get('ok')):
                    result['core_message'] = message
        else:
            result = check_access(self.port)
        with self.lock:
            if active == (self.active, self.started) and self.scope == scope:
                self.internet = result
            else:
                result['stale'] = True
        if not result.get('stale') and not result.get('ok') and controller and getattr(controller, 'bridge', None):
            profile = self.store.get(active[0])
            if profile['protocol'] == 'wireguard':
                result['wireguard_hint'] = 'WireGuard: нет подтверждённого ответа. Проверь Endpoint/UDP, ключи, PSK и Reserved; попробуй MTU 1280 во вкладке маршрутизации.'
                self.event(result['wireguard_hint'])
        return result
