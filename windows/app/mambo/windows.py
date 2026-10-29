"""Windows paths and launch helpers, imported lazily by the shared engine."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys


def bundle_root():
    portable = Path(__file__).resolve().parents[2]
    if (portable / 'runtime' / 'python.exe').is_file() and (portable / 'bin').is_dir():
        return portable
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]


def core_binary(name):
    candidate = bundle_root() / 'bin' / (name + '.exe')
    return str(candidate) if candidate.is_file() else None


def is_admin():
    return bool(ctypes.windll.shell32.IsUserAnAdmin()) if os.name == 'nt' else False


def ensure_admin():
    """One visible UAC prompt at launch, never a password/policy bypass."""
    if is_admin():
        return True
    args = sys.argv[1:] if getattr(sys, 'frozen', False) else sys.argv
    shell = ctypes.windll.shell32.ShellExecuteW
    shell.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
                     ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int]
    shell.restype = ctypes.c_void_p
    result = shell(None, 'runas', sys.executable, subprocess.list2cmdline(args), str(bundle_root()), 1)
    if not result or result <= 32:
        raise OSError('Запуск от администратора отменён. Он нужен для VPN всей системы.')
    return False
