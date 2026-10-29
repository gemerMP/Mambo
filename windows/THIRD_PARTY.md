# Third-party components

- Xray 26.10.10, MPL-2.0: corresponding source is in android/upstream/Xray-core-v26.10.10.tar.gz. Desktop cores are built from this source with Go 1.27.3, CGO_ENABLED=0.
- AndroidLibXrayLite 26.10.10, LGPL-3.0: source in android/upstream; pinned AAR in android/build.py.
- HEV socks5 tunnel 2.18.0, MIT: source in android/upstream; pinned AAR in android/build.py.
- sing-box 1.12.12, GPL-3.0: https://github.com/SagerNet/sing-box/tree/v1.12.12. Desktop binary license accompanies the binary.
- Qt / PySide6 Essentials / Shiboken 6.8.3, LGPL-3.0 and component licenses: https://code.qt.io/pyside/pyside-setup.git/tree/?h=6.8.3. License files and metadata accompany shared libraries. No statically linked Qt modifications.
- Python 3.12.10 Windows embedded distribution: PSF license in runtime/LICENSE.txt.
- Wintun 0.14.1: https://www.wintun.net/, license in bin/WINTUN-LICENSE.txt.
- distlib Windows launcher: license in LICENSE-LAUNCHER.txt; launch scripts are available in packaging/windows-launchers.

Artwork and supplied sound samples were retained from the user's original application archives; no new ownership claim is made.
