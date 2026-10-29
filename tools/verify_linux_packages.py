#!/usr/bin/env python3
"""Verify every payload file against the edited Linux distribution tree."""
import argparse
import hashlib
import io
from pathlib import Path
import subprocess
import tarfile

VERSION = '0.9.3'


def digest(stream):
    result = hashlib.sha256()
    for block in iter(lambda: stream.read(1024*1024), b''):
        result.update(block)
    return result.hexdigest()


def deb_members(path):
    with path.open('rb') as source:
        if source.read(8) != b'!<arch>\n':
            raise AssertionError('Invalid DEB header')
        while header := source.read(60):
            name = header[:16].decode().strip().rstrip('/')
            size = int(header[48:58])
            body = source.read(size)
            if size % 2:
                source.read(1)
            yield name, body


def validate_tar(archive, expected, prefix=''):
    seen = set()
    for item in archive:
        name = item.name.removeprefix('./')
        if prefix:
            if not name.startswith(prefix):
                continue
            name = name[len(prefix):]
        if name not in expected:
            continue
        path, sha, mode = expected[name]
        if item.issym():
            assert path.is_symlink() and item.linkname == path.readlink().as_posix(), name
        else:
            assert item.isfile(), name
            assert digest(archive.extractfile(item)) == sha, name
        assert item.mode & 0o777 == mode, (name, item.mode, mode)
        assert item.uid == 0 and item.gid == 0, name
        seen.add(name)
    assert seen == expected.keys(), 'Missing files: '+str(expected.keys()-seen)
    return len(seen)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, default=Path('linux'))
    parser.add_argument('--output', type=Path, default=Path('dist'))
    args = parser.parse_args()
    root = args.bundle.resolve()/'root'
    out = args.output.resolve()
    expected = {}
    for path in root.rglob('*'):
        if not path.is_file() and not path.is_symlink():
            continue
        if '__pycache__' in path.parts:
            continue
        with path.open('rb') as f:
            sha = digest(f)
        expected[path.relative_to(root).as_posix()] = (path, sha, path.stat().st_mode & 0o777)
    package = out/f'mambo-{VERSION}-1-x86_64.pkg.tar.zst'
    process = subprocess.Popen(['zstd', '-dq', '-c', str(package)], stdout=subprocess.PIPE)
    with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
        count = validate_tar(archive, expected)
    process.stdout.close()
    assert process.wait() == 0
    print(f'Arch: {count} payload files match', flush=True)
    data = None
    for name, body in deb_members(out/f'mambo_{VERSION}-1_amd64.deb'):
        if name.startswith('control.tar'):
            with tarfile.open(fileobj=io.BytesIO(body)) as archive:
                control = archive.extractfile('./control').read().decode()
                assert f'Version: {VERSION}-1\n' in control
        if name.startswith('data.tar'):
            data = body
    assert data is not None
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        count = validate_tar(archive, expected)
    print(f'DEB: {count} payload files match', flush=True)
    with tarfile.open(out/f'Mambo-Linux-x64-{VERSION}.tar.gz') as archive:
        count = validate_tar(archive, expected, f'Mambo-Linux-x64-{VERSION}/root/')
    print(f'tar.gz: {count} payload files match', flush=True)
    for name in ['usr/bin/mambo', 'usr/bin/mambo-lite', 'usr/lib/mambo/mambo-tun-helper',
                 'usr/lib/mambo/bin/xray', 'usr/lib/mambo/bin/sing-box']:
        assert expected[name][2] & 0o111, name
    print('Launchers and VPN cores are executable', flush=True)


if __name__ == '__main__':
    main()
