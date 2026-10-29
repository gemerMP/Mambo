"""Read payload byte counters from the running core, without resetting them."""
import http.client
import json
import socket
import time


def format_bytes(value):
    value = max(0, int(value or 0))
    for unit in ('Б', 'КиБ', 'МиБ', 'ГиБ', 'ТиБ'):
        if value < 1024 or unit == 'ТиБ':
            return (str(value) if unit == 'Б' else f'{value:.1f}')+' '+unit
        value /= 1024


class Traffic:
    def __init__(self):
        self.port = None
        self.reset()

    def reset(self):
        self.values = dict(uploaded=0, downloaded=0, upload_rate=0, download_rate=0, available=False)
        self.stamp = time.monotonic()

    def configure(self, config):
        self.reset()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        config['stats'] = {}
        config.setdefault('policy', {})['system'] = dict(statsOutboundUplink=True, statsOutboundDownlink=True)
        config['metrics'] = {'listen': '127.0.0.1:'+str(self.port)}
        return config

    def read(self):
        if self.port is None:
            return self.values.copy()
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=.6)
        try:
            connection.request('GET', '/debug/vars')
            reply = connection.getresponse()
            payload = reply.read(1048577)
            if reply.status != 200 or len(payload) > 1048576:
                raise ValueError('Metrics response')
            stats = json.loads(payload).get('stats', {}).get('outbound', {}).get('proxy', {})
            now = time.monotonic()
            elapsed = max(.01, now-self.stamp)
            up, down = max(0, int(stats.get('uplink', 0))), max(0, int(stats.get('downlink', 0)))
            self.values = dict(uploaded=up, downloaded=down,
                upload_rate=max(0, (up-self.values['uploaded'])/elapsed),
                download_rate=max(0, (down-self.values['downloaded'])/elapsed), available=True)
            self.stamp = now
        except (OSError, ValueError, TypeError, http.client.HTTPException):
            self.values.update(available=False, upload_rate=0, download_rate=0)
        finally:
            connection.close()
        return self.values.copy()
