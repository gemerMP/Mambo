"""Per-link resolved setup. Never overwrite resolv.conf or physical-link settings."""
from pathlib import Path
import subprocess

BINARY = '/usr/bin/resolvectl'

def configure():
    if not Path(BINARY).is_file():
        return 'unavailable'
    try:
        if subprocess.run([BINARY, 'status'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5).returncode:
            return 'unavailable'
        for args in [('dns','mambo0','172.29.252.2'), ('domain','mambo0','~.'), ('default-route','mambo0','yes')]:
            result=subprocess.run([BINARY,*args],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
            if result.returncode:
                revert()
                return 'failed'
        return 'configured'
    except (OSError,subprocess.TimeoutExpired):
        revert()
        return 'failed'

def revert():
    if Path(BINARY).is_file():
        try:
            subprocess.run([BINARY,'revert','mambo0'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
        except (OSError,subprocess.TimeoutExpired):
            pass
