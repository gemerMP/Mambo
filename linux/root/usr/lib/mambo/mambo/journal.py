"""One bounded, thread-safe event journal shared by the UI and VPN workers."""
import re
import threading
import time

LOCK = threading.RLock()


def safe(text):
    text = str(text)
    text = re.sub(r'(?i)(?:vless|trojan|wg|wireguard|https?)://\S+', '[ссылка скрыта]', text)
    text = re.sub(r'[A-Za-z0-9+/_-]{43}=?', '[ключ скрыт]', text)
    return text.replace('\r', ' ')[:2500]


def append(home, event):
    with LOCK:
        path = home/'events.log'
        try:
            old = path.read_text(encoding='utf-8') if path.exists() else ''
            lines = (old + time.strftime('%Y-%m-%d %H:%M:%S')+'  '+safe(event)+'\n').splitlines(True)
            text = ''.join(lines)[-60000:]
            if len(text) == 60000:
                text = text.partition('\n')[2]
            path.write_text(text, encoding='utf-8')
            path.chmod(0o600)
        except OSError:
            pass
