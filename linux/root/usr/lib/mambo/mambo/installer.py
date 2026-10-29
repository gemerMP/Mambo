"""Download an official, fixed-version Xray archive after an explicit UI action."""
import hashlib
import io
import os
from pathlib import Path
import platform
import re
import tempfile
import urllib.request
import zipfile
from .core import HTTPSOnly, MamboError

XRAY_VERSION = 'v26.3.27'
MAX_ARCHIVE = 80 * 1024 * 1024


def release_asset(machine=None, system=None):
    machine = (machine or platform.machine()).lower()
    system = system or platform.system()
    if system == 'Windows':
        if machine not in ('amd64', 'x86_64'):
            raise MamboError('Windows-сборка поддерживает x64.')
        return 'Xray-windows-64.zip'
    if system != 'Linux':
        raise MamboError('Автоустановка ядра в этой сборке доступна только на Linux.')
    name = {'x86_64': 'Xray-linux-64.zip', 'amd64': 'Xray-linux-64.zip', 'aarch64': 'Xray-linux-arm64-v8a.zip', 'arm64': 'Xray-linux-arm64-v8a.zip'}.get(machine)
    if not name:
        raise MamboError('Автоустановка поддерживает x86_64 и ARM64.')
    return name


def download(url, limit):
    opener = urllib.request.build_opener(HTTPSOnly())
    try:
        with opener.open(urllib.request.Request(url, headers={'User-Agent': 'Mambo/0.2'}), timeout=60) as response:
            payload = response.read(limit + 1)
        if len(payload) > limit:
            raise MamboError('Файл ядра превышает допустимый размер.')
        return payload
    except MamboError:
        raise
    except Exception as exc:
        raise MamboError('Не удалось скачать ядро с GitHub. Проверьте сеть или укажите свой Xray при запуске.') from exc


def verify_digest(payload, manifest):
    """Accept the digest formats used by openssl dgst; never execute on mismatch."""
    text = manifest.decode('ascii', errors='strict')
    matches = re.findall(r'(?:SHA2?-?256)\s*\([^\r\n]*\)\s*=\s*([0-9a-fA-F]{64})', text, re.I)
    if not matches:
        matches = re.findall(r'^\s*SHA2?-?256\s*[:=]\s*([0-9a-fA-F]{64})\s*$', text, re.I | re.M)
    if len(matches) != 1 or hashlib.sha256(payload).hexdigest().lower() != matches[0].lower():
        raise MamboError('Контрольная сумма ядра не совпала. Установка отменена.')


def install_xray(store, fetch=download):
    asset = release_asset()
    base = f'https://github.com/XTLS/Xray-core/releases/download/{XRAY_VERSION}/{asset}'
    manifest = fetch(base + '.dgst', 16384)
    payload = fetch(base, MAX_ARCHIVE)
    try:
        verify_digest(payload, manifest)
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            info = archive.getinfo('xray.exe' if os.name == 'nt' else 'xray')
            if info.file_size > 120 * 1024 * 1024 or info.is_dir():
                raise MamboError('Некорректный бинарный файл ядра.')
            binary = archive.read(info)
        if not binary.startswith(b'MZ' if os.name == 'nt' else b'\x7fELF'):
            raise MamboError('В архиве нет ядра для этой системы.')
        directory = store.home / 'bin'
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temp = tempfile.mkstemp(prefix='.xray-', dir=directory)
        try:
            with os.fdopen(fd, 'wb') as output:
                output.write(binary)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temp, 0o700)
            destination = directory / ('xray.exe' if os.name == 'nt' else 'xray')
            os.replace(temp, destination)
        finally:
            Path(temp).unlink(missing_ok=True)
        return {'version': XRAY_VERSION, 'installed': True}
    except MamboError:
        raise
    except (ValueError, KeyError, zipfile.BadZipFile, UnicodeError) as exc:
        raise MamboError('Не удалось проверить официальный архив ядра. Установка отменена.') from exc
