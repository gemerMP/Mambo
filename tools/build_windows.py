#!/usr/bin/env python3
"""Overlay shared desktop source onto the supplied Windows runtime and package it."""
import argparse
import ast
from pathlib import Path
import shutil
from zipfile import ZipFile,ZIP_DEFLATED
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=ROOT/'dist');args=p.parse_args();args.output.mkdir(parents=True,exist_ok=True)
 src=ROOT/'linux/root/usr/lib/mambo/mambo';target=ROOT/'windows/app/mambo'
 for f in src.glob('*.py'):ast.parse(f.read_text())
 shutil.copytree(src,target,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
 for d in target.rglob('__pycache__'):shutil.rmtree(d)
 required=['Mambo.exe','bin/xray.exe','bin/sing-box.exe','bin/wintun.dll','runtime/python312.dll','runtime/Lib/site-packages/PySide6/Qt6Widgets.dll','app/mambo/ui.py','app/mambo/fonts/NotoSans-Regular.ttf']
 for f in required:
  if not (ROOT/'windows'/f).is_file():raise RuntimeError('Missing Windows component: '+f)
 out=args.output/'Mambo-Windows-x64-0.9.3-Qt.zip'
 with ZipFile(out,'w',ZIP_DEFLATED,compresslevel=6) as z:
  for f in sorted((ROOT/'windows').rglob('*')):
   if f.is_file() and '__pycache__' not in f.parts and not f.name.endswith('.pyc'):z.write(f,f.relative_to(ROOT/'windows'))
 print(out.name,out.stat().st_size,flush=True)
if __name__=='__main__':main()
