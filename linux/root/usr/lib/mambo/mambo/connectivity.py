"""HTTPS probes distinguish a local listener from actual VPN traffic."""
import socket
import ssl
import time

TARGETS = ('example.com', 'www.gstatic.com')
STAGES = {
    'local': 'локальный прокси', 'socks': 'ответ SOCKS',
    'proxy': 'соединение через VPN', 'tls': 'согласование TLS',
    'http': 'ответ HTTPS', 'dns': 'системный DNS', 'https': 'системный HTTPS',
}


def read_exact(sock, count):
    data = bytearray()
    while len(data) < count:
        block = sock.recv(count-len(data))
        if not block:
            raise OSError('Connection closed')
        data.extend(block)
    return bytes(data)


def failed(stage, target, exc=None):
    if isinstance(exc, ssl.SSLCertVerificationError):
        message = 'Сертификат TLS не прошёл проверку. Проверь дату системы и параметры профиля.'
    elif isinstance(exc, (TimeoutError, socket.timeout)):
        message = 'Нет ответа: '+STAGES[stage]+'.'
    elif stage == 'local':
        message = 'Локальный прокси недоступен.'
    else:
        message = 'Проверка не прошла: '+STAGES[stage]+'.'
    return dict(ok=False, checked_at=time.time(), target=target, stage=stage, message=message)


def check_https(port, host='example.com', *, timeout=4, target_port=443, context=None, path='/'):
    begin = time.monotonic()
    stage = 'local'
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            stage = 'socks'
            sock.sendall(b'\x05\x01\x00')
            if read_exact(sock, 2) != b'\x05\x00':
                raise OSError('SOCKS authentication')
            domain = host.encode('idna')
            if not 1 <= len(domain) <= 255:
                raise ValueError('Host length')
            stage = 'proxy'
            sock.sendall(b'\x05\x01\x00\x03'+bytes([len(domain)])+domain+target_port.to_bytes(2, 'big'))
            reply = read_exact(sock, 4)
            if reply[:3] != b'\x05\x00\x00':
                result = failed(stage, host)
                result['socks_code'] = reply[1]
                return result
            if reply[3] == 1:
                read_exact(sock, 4)
            elif reply[3] == 4:
                read_exact(sock, 16)
            elif reply[3] == 3:
                read_exact(sock, read_exact(sock, 1)[0])
            else:
                raise OSError('SOCKS address')
            read_exact(sock, 2)
            stage = 'tls'
            with (context or ssl.create_default_context()).wrap_socket(sock, server_hostname=host) as tls:
                stage = 'http'
                tls.sendall(('GET '+path+' HTTP/1.1\r\nHost: '+host+'\r\nConnection: close\r\n\r\n').encode('ascii'))
                response = b''
                while b'\r\n' not in response and len(response) < 4096:
                    block = tls.recv(1024)
                    if not block:
                        break
                    response += block
                parts = response.split(b'\r\n', 1)[0].split()
                if len(parts) < 2 or not parts[0].startswith(b'HTTP/') or not 200 <= int(parts[1]) < 400:
                    raise OSError('HTTPS status')
        return dict(ok=True, checked_at=time.time(), ms=round((time.monotonic()-begin)*1000), target=host)
    except (OSError, ValueError) as exc:
        return failed(stage, host, exc)


def check_access(port):
    attempts = []
    for host in TARGETS:
        result = check_https(port, host)
        attempts.append(result)
        if result['ok'] or result.get('stage') in ('local', 'socks'):
            break
    return {**result, 'attempts': attempts}


def check_system_https():
    """OS DNS/routes, deliberately without proxy environment variables."""
    import urllib.request
    import urllib.error
    start = time.monotonic()
    attempts = []
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for host in TARGETS:
        try:
            with opener.open('https://'+host+'/', timeout=4) as response:
                response.read(1)
            return dict(ok=True, ms=round((time.monotonic()-start)*1000), target=host)
        except urllib.error.URLError as exc:
            result = failed('dns' if isinstance(exc.reason, socket.gaierror) else 'https', host, exc.reason)
        except (OSError, ValueError) as exc:
            result = failed('https', host, exc)
        attempts.append(result)
    return {**result, 'attempts': attempts}


def access_ok(result, scope):
    return bool(result and result.get('ok') and (scope != 'tun' or result.get('system', {}).get('ok')))


def health_summary(result):
    pieces = ['Прокси: '+('доступ есть' if result.get('ok') else result.get('message', 'нет ответа'))]
    if 'xray' in result:
        x = result['xray']
        pieces.append('Xray: '+('доступ есть' if x.get('ok') else x.get('message', 'нет ответа')))
    if 'system' in result:
        s = result['system']
        pieces.append('Системный маршрут: '+('доступ есть' if s.get('ok') else s.get('message', 'нет ответа')))
    if result.get('core_message'):
        pieces.append(result['core_message'])
    if result.get('wireguard_hint'):
        pieces.append(result['wireguard_hint'])
    return '\n'.join(pieces)
