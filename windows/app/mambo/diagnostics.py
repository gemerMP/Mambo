"""Bound core output in memory; expose only fixed, credential-free reasons."""
from collections import deque
import threading


def core_reason(output, core='VPN'):
    value = output.lower()
    if not value.strip():
        return None
    if 'address already in use' in value:
        return core + ': локальный порт занят другим процессом.'
    if '127.0.0.1:10809' in value and ('refused' in value or 'closed' in value):
        return 'Внутренний прокси Xray недоступен.'
    if 'permission denied' in value or 'operation not permitted' in value:
        return core + ': системе не удалось разрешить сетевую операцию. Проверь права TUN и другой VPN.'
    if '/dev/net/tun' in value or 'create tun' in value:
        return 'Не удалось создать TUN-интерфейс. Проверь /dev/net/tun и другой VPN.'
    if any(x in value for x in ('certificate', 'x509', 'unknown authority')):
        return core + ': ошибка проверки сертификата TLS. Проверь SNI и дату системы.'
    if 'reality' in value and any(x in value for x in ('invalid', 'failed', 'reject', 'mismatch')):
        return 'REALITY: соединение не прошло проверку. Проверь SNI, public key и short ID профиля.'
    if 'network is unreachable' in value or 'no route to host' in value:
        return core + ': нет маршрута к серверу. Проверь сеть и другой VPN.'
    if 'connection refused' in value:
        return core + ': сервер отклонил соединение на указанном порту.'
    if any(x in value for x in ('i/o timeout', 'deadline exceeded', 'timed out', 'timeout')):
        return core + ': истекло время ожидания ответа сервера.'
    if 'no such host' in value or 'dns exchange' in value or 'lookup ' in value:
        return core + ': не удалось получить ответ DNS.'
    if 'handshake' in value:
        return core + ': не удалось завершить согласование соединения.'
    if 'failed' in value or 'error' in value or 'fatal' in value:
        return core + ': сетевая операция завершилась ошибкой. Проверь профиль и доступность сервера.'
    return None


class CoreOutput:
    def __init__(self, stream, core, callback=None):
        self.lines = deque(maxlen=48)
        self.core = core
        self.callback = callback
        self.last_reason = None
        self.thread = threading.Thread(target=self._read, args=(stream,), daemon=True)
        self.thread.start()

    def _read(self, stream):
        try:
            for line in stream:
                self.lines.append(line[:4096])
                reason = core_reason(line, self.core)
                if reason and reason != self.last_reason:
                    self.last_reason = reason
                    if self.callback:
                        self.callback(reason)
        except (OSError, ValueError):
            pass

    def reason(self):
        return self.last_reason

    def close(self):
        self.thread.join(timeout=1)
