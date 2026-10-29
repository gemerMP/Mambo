#!/usr/bin/env python3
"""Install files from this extracted archive. Invoke explicitly with sudo."""
import os,shutil,subprocess,sys
from pathlib import Path
if os.geteuid()!=0:raise SystemExit('Запусти: sudo python3 install.py')
source=Path(__file__).resolve().parent/'root'
if not (source/'usr/lib/mambo/mambo/qt_app.py').is_file():raise SystemExit('Распакуй весь архив перед установкой.')
for p in source.rglob('*'):
 target=Path('/')/p.relative_to(source)
 if p.is_dir():target.mkdir(parents=True,exist_ok=True)
 elif p.is_file():shutil.copy2(p,target);os.chown(target,0,0)
if shutil.which('update-desktop-database'):subprocess.run(['update-desktop-database','/usr/share/applications'])
print('Mambo установлен. Открой Mambo в меню приложений или выполни mambo без sudo.')
