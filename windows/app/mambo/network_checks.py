"""Explicit, bounded network checks; failures never assert that DPI is present."""
from contextlib import contextmanager
import ipaddress
import os
import socket
import ssl
import statistics
import struct
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from .core import Engine, Store, MamboError
from .probes import connect_https, request, exact
from .routing import dns_ips, validate

MODES = ['Доступ и возможная фильтрация', 'DNS через VPN · UDP',
         'Стабильность · 5 HTTPS-запросов', 'WireGuard · параметры и доступ']


@contextmanager
def proxy_for(profile, engine, cancel):
    state = engine.status()
    if state['running'] and state['active'] == profile['id']:
        yield engine.port, state
        return
    if profile['protocol'] == 'wireguard' and (state['running'] or state['tun_pending']):
        raise MamboError('WireGuard: отключи VPN перед проверкой другого профиля.')
    with tempfile.TemporaryDirectory(prefix='mambo-diagnostic-') as folder:
        store = Store(Path(folder))
        store.import_text(profile['uri'])
        store.save_rules({'lan': False, 'dns': engine.store.rules().get('dns', ''), 'mtu': engine.store.rules().get('mtu', 1500)})
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        owned = Engine(store, engine.binary(), port)
        try:
            cancel.check()
            owned.start(profile['id'])
            yield port, state
        finally:
            owned.stop()


def https(url, port, timeout, cancel):
    if port is not None:
        sock, parsed, start = connect_https(url, port, timeout, cancel)
    else:
        import time
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or any(ord(x) <= 32 for x in url):
            raise MamboError('Для проверки нужен корректный HTTPS URL.')
        start = time.monotonic()
        sock = socket.create_connection((parsed.hostname, parsed.port or 443), timeout)
        cancel.socket = sock
        try:
            cancel.check()
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=parsed.hostname)
            cancel.socket = sock
        except BaseException:
            sock.close()
            raise
    try:
        return request(sock, parsed, 'GET', False, start, cancel)
    finally:
        sock.close()
        cancel.socket = None


def reason(exc):
    if isinstance(exc, ssl.SSLError):
        return 'ошибка TLS/сертификата'
    if isinstance(exc, socket.gaierror):
        return 'нет ответа DNS'
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return 'тайм-аут'
    if isinstance(exc, MamboError):
        return str(exc)
    return 'нет ответа ('+type(exc).__name__+')'


def comparison(direct_ok, proxy_ok):
    if proxy_ok and not direct_ok:
        return 'Через прокси доступ есть, напрямую — нет. Возможны фильтрация или сбой прямого маршрута.'
    if direct_ok and not proxy_ok:
        return 'Напрямую доступ есть. Проверь VPN-сервер и правила маршрутизации.'
    if proxy_ok and direct_ok:
        return 'Оба пути отвечают. Признаков ограничения для этого адреса в этой проверке нет.'
    return 'Оба пути не отвечают. По этому тесту причину определить нельзя.'


def dns_udp(port, server, hostname, timeout, cancel, qtype=1):
    """SOCKS UDP ASSOCIATE and an actual DNS answer, not a UDP connect()."""
    with socket.create_connection(('127.0.0.1', port), timeout) as control:
        cancel.socket = control
        control.settimeout(timeout)
        cancel.check()
        control.sendall(b'\x05\x01\x00')
        if exact(control, 2) != b'\x05\x00':
            raise MamboError('Прокси отклонил UDP.')
        control.sendall(b'\x05\x03\x00\x01'+b'\0'*6)
        head = exact(control, 4)
        if head[:3] != b'\x05\x00\x00':
            raise MamboError('UDP ASSOCIATE недоступен.')
        if head[3] == 1:
            host = socket.inet_ntop(socket.AF_INET, exact(control, 4))
        elif head[3] == 4:
            host = socket.inet_ntop(socket.AF_INET6, exact(control, 16))
        elif head[3] == 3:
            host = exact(control, exact(control, 1)[0]).decode('ascii')
        else:
            raise MamboError('Некорректный ответ UDP ASSOCIATE.')
        relay_port = int.from_bytes(exact(control, 2), 'big')
        host = '127.0.0.1' if host in ('0.0.0.0', '::') else host
        address = ipaddress.ip_address(server)
        target = (b'\x01' if address.version == 4 else b'\x04')+address.packed+b'\x00\x35'
        ident = os.urandom(2)
        labels = hostname.encode('idna').split(b'.')
        if not labels or any(not 1 <= len(x) <= 63 for x in labels):
            raise MamboError('Некорректное DNS-имя.')
        query = ident+b'\x01\x00\x00\x01'+b'\0'*6+b''.join(bytes([len(x)])+x for x in labels)+b'\0'+struct.pack('!HH', qtype, 1)
        with socket.socket(socket.AF_INET6 if ':' in host else socket.AF_INET, socket.SOCK_DGRAM) as udp:
            udp.settimeout(timeout)
            udp.connect((host, relay_port))
            cancel.socket = udp
            cancel.check()
            udp.send(b'\0\0\0'+target+query)
            reply = udp.recv(65535)
            if len(reply) < 10 or reply[:3] != b'\0\0\0':
                raise MamboError('Некорректный UDP-ответ.')
            offset = 10 if reply[3] == 1 else 22 if reply[3] == 4 else 7+reply[4] if reply[3] == 3 else len(reply)
            dns = reply[offset:]
            if len(dns) < 12 or dns[:2] != ident or not dns[2] & 0x80:
                raise MamboError('Некорректный DNS-ответ.')
            code = dns[3] & 15
            answers = int.from_bytes(dns[6:8], 'big')
            return 'DNS '+('A' if qtype == 1 else 'AAAA')+f': RCODE {code}, ответов {answers}'+(' · UDP проходит' if code == 0 and answers else ' · UDP отвечает, записи не получены')


def run(profile, engine, settings, mode, cancel):
    timeout = max(1, min(15, int(settings.get('timeout', 8))))
    url = settings.get('test_url', 'https://www.gstatic.com/generate_204')
    lines = [MODES[mode]]
    with proxy_for(profile, engine, cancel) as (port, state):
        if mode == 0:
            targets = list(dict.fromkeys([url, 'https://example.com/']))
            for target in targets:
                cancel.check()
                # In system TUN mode this listener deliberately exits outside TUN.
                direct_port = 10810 if state['running'] and state['scope'] == 'tun' else None
                success = []
                lines.append('\n'+urlsplit(target).hostname)
                for label, proxy_port in [('Напрямую', direct_port), ('Через прокси', port)]:
                    try:
                        ms = https(target, proxy_port, timeout, cancel)
                        lines.append(f'{label}: {ms} мс · HTTPS проходит')
                        success.append(True)
                    except Exception as exc:
                        cancel.check()
                        lines.append(label+': '+reason(exc))
                        success.append(False)
                lines.append(comparison(*success))
            lines.append('\nУчитываются правила маршрутизации. Это сравнение доступности выбранных адресов, не доказательство наличия или отсутствия DPI.')
        elif mode == 1:
            servers = dns_ips(profile, validate(engine.store.rules()))
            for server in servers[:2]:
                for qtype in (1, 28):
                    cancel.check()
                    try:
                        lines.append(server+' · '+dns_udp(port, server, 'example.com', timeout, cancel, qtype))
                    except Exception as exc:
                        cancel.check()
                        lines.append(server+' · '+reason(exc))
        elif mode == 2:
            samples = []
            for index in range(5):
                cancel.check()
                try:
                    ms = https(url, port, timeout, cancel)
                    samples.append(ms)
                    lines.append(f'{index+1}. {ms} мс')
                except Exception as exc:
                    cancel.check()
                    lines.append(f'{index+1}. '+reason(exc))
            lines.append(f'Успешно {len(samples)}/5 · ошибок запросов {(5-len(samples))*20}%')
            if samples:
                lines.append(f'Мин/среднее/макс: {min(samples)}/{round(statistics.mean(samples))}/{max(samples)} мс')
            if len(samples) > 1:
                lines.append('Разброс соседних успешных запросов: '+str(round(statistics.mean(abs(b-a) for a,b in zip(samples,samples[1:]))))+' мс')
            lines.append('Это HTTPS-запросы; процент ошибок не равен потерям IP-пакетов.')
        else:
            if profile['protocol'] != 'wireguard':
                raise MamboError('Выбери профиль WireGuard.')
            settings_wg = profile['outbound']['settings']
            lines.append(f"Пиров: {len(settings_wg['peers'])} · MTU {settings_wg['mtu']} · Reserved: задан" if any(settings_wg['reserved']) else f"Пиров: {len(settings_wg['peers'])} · MTU {settings_wg['mtu']} · Reserved: стандартный")
            lines.append('Второй туннель с тем же ключом не создаётся при активном VPN.')
            for server in dns_ips(profile, validate(engine.store.rules())):
                address = ipaddress.ip_address(server)
                covered = any(address in ipaddress.ip_network(net, strict=False) for peer in settings_wg['peers'] for net in peer['allowedIPs'])
                lines.append(f'DNS {server}: '+('в AllowedIPs' if covered else 'вне AllowedIPs — добавь маршрут к DNS в профиль'))
            try:
                ms = https(url, port, timeout, cancel)
                lines.append(f'Ответ через WireGuard: {ms} мс · HTTPS проходит')
            except Exception as exc:
                cancel.check()
                lines.append('Нет подтверждённого ответа: '+reason(exc))
                lines.append('Проверь UDP до Endpoint, публичный ключ сервера, PSK и Reserved. Попробуй MTU 1280. Успешный TCP-пинг не подтверждает работу WireGuard.')
    return '\n'.join(lines)
