#!/usr/bin/env python3
"""Package the supplied complete Linux tree without downloading dependencies.

Usage: python3 tools/build_linux.py --bundle linux --output dist
The tree contains the editable Python application plus the unchanged supplied
Qt runtime, Xray and sing-box. This script does not rebuild those dependencies.
"""
import argparse
import ast
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time
import zipfile

VERSION = '0.9.3'


def root_owner(info):
    info.uid = info.gid = 0
    info.uname = info.gname = 'root'
    return info


def archive_tree(bundle, output):
    target = output/f'Mambo-Linux-x64-{VERSION}.tar.gz'
    with tarfile.open(target, 'w:gz', compresslevel=6) as archive:
        archive.add(bundle, arcname=target.name.removesuffix('.tar.gz'), filter=root_owner)
    return target


def arch_package(root, output, installed_size):
    deps = ['python', 'polkit', 'libxkbcommon-x11', 'libxcb', 'xcb-util-cursor',
            'xcb-util-image', 'xcb-util-keysyms', 'xcb-util-renderutil', 'xcb-util-wm',
            'fontconfig', 'freetype2', 'glib2', 'libglvnd', 'dbus', 'alsa-utils']
    meta = '\n'.join([
        'pkgname = mambo', 'pkgbase = mambo', f'pkgver = {VERSION}-1',
        'pkgdesc = Mambo native Qt VPN client', f'builddate = {int(time.time())}',
        'packager = Mambo', f'size = {installed_size}', 'arch = x86_64',
        'license = GPL3', *['depend = '+d for d in deps], '',
    ])
    target = output/f'mambo-{VERSION}-1-x86_64.pkg.tar.zst'
    with tempfile.TemporaryDirectory(dir=output) as tmp:
        info = Path(tmp)/'.PKGINFO'
        info.write_text(meta)
        plain = Path(tmp)/'package.tar'
        with tarfile.open(plain, 'w', format=tarfile.PAX_FORMAT) as archive:
            archive.add(info, arcname='.PKGINFO', filter=root_owner)
            archive.add(root/'usr', arcname='usr', filter=root_owner)
        temporary = target.with_name(target.name + '.part')
        try:
            import zstandard
        except ImportError:
            subprocess.run(['zstd', '-q', '-10', '-f', str(plain), '-o', str(temporary)], check=True)
        else:
            with plain.open('rb') as source, temporary.open('wb') as destination:
                zstandard.ZstdCompressor(level=10).copy_stream(source, destination)
                destination.flush()
                os.fsync(destination.fileno())
        subprocess.run(['zstd', '-tq', str(temporary)], check=True)
        temporary.chmod(0o644)
        temporary.replace(target)
    return target


def deb_package(root, output, installed_size):
    target = output/f'mambo_{VERSION}-1_amd64.deb'
    control = f'''Package: mambo
Version: {VERSION}-1
Architecture: amd64
Maintainer: Mambo
Section: net
Priority: optional
Installed-Size: {(installed_size+1023)//1024}
Depends: python3 (>= 3.10), pkexec | policykit-1, libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-render-util0, libxcb-xinerama0, libxcb-xkb1, libxkbcommon-x11-0, libgl1, libegl1, libdbus-1-3, libfontconfig1, libglib2.0-0, alsa-utils
Description: Native Qt VPN client with VLESS, Trojan and WireGuard
 Native VPN interface, session timer, routing and connection diagnostics.
'''
    with tempfile.TemporaryDirectory(dir=output) as tmp:
        stage = Path(tmp)/'package'
        shutil.copytree(root, stage)
        metadata = stage/'DEBIAN'
        metadata.mkdir()
        (metadata/'control').write_text(control)
        env = dict(os.environ, TMPDIR=tmp)
        subprocess.run(['dpkg-deb', '--root-owner-group', '-Zxz', '-z6', '--build',
                        str(stage), str(target)], env=env, check=True)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, default=Path('linux'))
    parser.add_argument('--output', type=Path, default=Path('dist'))
    args = parser.parse_args()
    bundle, output = args.bundle.resolve(), args.output.resolve()
    root = bundle/'root'
    if not (root/'usr/lib/mambo/mambo/ui.py').is_file():
        parser.error('--bundle must contain root/usr/lib/mambo/mambo/ui.py')
    output.mkdir(parents=True, exist_ok=True)
    # Remove only generated Python caches inside this distribution tree.
    for path in root.rglob('__pycache__'):
        shutil.rmtree(path)
    for path in root.rglob('*.pyc'):
        path.unlink()
    for path in (root/'usr/lib/mambo/mambo').glob('*.py'):
        ast.parse(path.read_text())
    for name in ['mambo', 'mambo-lite']:
        if not os.access(root/'usr/bin'/name, os.X_OK):
            raise RuntimeError(f'Launcher is not executable: {name}')
    installed_size = sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
    for build in [arch_package, deb_package]:
        target = build(root, output, installed_size)
        print(f'{target.name}: {target.stat().st_size} bytes', flush=True)
    target = archive_tree(bundle, output)
    print(f'{target.name}: {target.stat().st_size} bytes', flush=True)


if __name__ == '__main__':
    main()
