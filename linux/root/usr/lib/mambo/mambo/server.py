"""Loopback-only UI; bearer token + exact Host/Origin validation."""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import mimetypes
import os
from pathlib import Path
import secrets
import signal
import urllib.parse
import webbrowser
from .core import Engine, MamboError, fetch_subscription, probe

WEB = Path(__file__).parent / 'web'


def make_server(store, engine, port=0):
    token = secrets.token_urlsafe(32)
    if os.name == 'nt':
        from .windows_sounds import SoundPlayer
    else:
        from .sounds import SoundPlayer
    sounds = SoundPlayer(WEB / 'assets')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log imported URLs or bearer tokens.

        def respond(self, status, value, mime='application/json; charset=utf-8'):
            body = json.dumps(value, ensure_ascii=False).encode() if not isinstance(value, bytes) else value
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'private, max-age=3600' if mime.startswith('image/') else 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def valid_host(self):
            return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

        def authenticated(self):
            origin = self.headers.get('Origin')
            expected = f'http://127.0.0.1:{self.server.server_port}'
            return self.valid_host() and (origin is None or origin == expected) and hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token)

        def do_GET(self):
            if not self.valid_host():
                return self.respond(403, {'error': 'Недопустимый Host.'})
            path = urllib.parse.urlsplit(self.path).path
            if path == '/api/state':
                if not self.authenticated():
                    return self.respond(401, {'error': 'Откройте адрес из терминала Mambo.'})
                return self.respond(200, {'profiles': store.public(), 'status': engine.status(), 'rules': store.rules()})
            relative = 'index.html' if path == '/' else urllib.parse.unquote(path).lstrip('/')
            target = (WEB / relative).resolve()
            if not target.is_relative_to(WEB.resolve()) or not target.is_file():
                return self.respond(404, {'error': 'Не найдено.'})
            self.respond(200, target.read_bytes(), mimetypes.guess_type(target)[0] or 'application/octet-stream')

        def do_POST(self):
            if not self.authenticated():
                return self.respond(403, {'error': 'Нет доступа. Откройте адрес из терминала Mambo.'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 2 * 1024 * 1024:
                    return self.respond(413, {'error': 'Запрос слишком большой или пустой.'})
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    return self.respond(415, {'error': 'Ожидается JSON.'})
                self.connection.settimeout(20)
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise MamboError('Ожидается объект JSON.')
                path = self.path
                if path == '/api/sound':
                    result = sounds.play(data.get('index'), data.get('volume'))
                elif path == '/api/sound/stop':
                    sounds.stop()
                    result = {}
                elif path == '/api/import':
                    result = {'count': store.import_text(data.get('text'))}
                elif path == '/api/subscribe':
                    result = store.import_subscription(fetch_subscription(str(data.get('url', ''))))
                elif path == '/api/connect':
                    result = engine.start(data.get('id'), data.get('mode', 'socks'))
                elif path == '/api/internet-check':
                    result = engine.check_internet()
                elif path == '/api/disconnect':
                    engine.stop()
                    result = engine.status()
                elif path == '/api/engine/install':
                    from .installer import install_xray
                    with engine.lock:
                        if engine.status()['running']:
                            raise MamboError('Отключите прокси перед установкой ядра.')
                        result = install_xray(store)
                elif path == '/api/favorite':
                    store.favorite(data.get('id'), data.get('enabled'))
                    result = {}
                elif path == '/api/delete':
                    with engine.lock:
                        if engine.status()['active'] == data.get('id'):
                            raise MamboError('Отключите сервер перед удалением.')
                        store.delete(data.get('id'))
                    result = {}
                elif path == '/api/check':
                    with ThreadPoolExecutor(max_workers=8) as pool:
                        result = {'results': list(pool.map(probe, store.list()))}
                elif path == '/api/rules':
                    store.save_rules(data)
                    result = {'reconnect': engine.status()['running']}
                else:
                    return self.respond(404, {'error': 'Неизвестная команда.'})
                self.respond(200, result)
            except MamboError as exc:
                self.respond(400, {'error': str(exc)})
            except (ValueError, TypeError, KeyError):
                self.respond(400, {'error': 'Некорректные данные запроса.'})
            except Exception:
                self.respond(500, {'error': 'Операция не выполнена. Проверьте ядро и права доступа.'})

    class MamboServer(ThreadingHTTPServer):
        def server_close(self):
            sounds.close()
            super().server_close()
    server = MamboServer(('127.0.0.1', port), Handler)
    return server, token


def serve(store, executable=None, socks_port=10808, port=0, browser=True):
    engine = Engine(store, executable, socks_port)
    server, token = make_server(store, engine, port)
    url = f'http://127.0.0.1:{server.server_port}/#token={token}'
    print('Mambo: ' + url, flush=True)
    print('Ctrl+C завершит интерфейс и локальный прокси.', flush=True)
    if browser:
        webbrowser.open(url)
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        engine.stop()
