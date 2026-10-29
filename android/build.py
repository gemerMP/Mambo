#!/usr/bin/env python3
"""Build without Gradle: Python 3, Java 17 and curl. Dependencies are SHA-256 pinned."""
from pathlib import Path
import hashlib, os, secrets, shutil, subprocess, zipfile, json
ROOT=Path(__file__).resolve().parent
VERSION='0.9.3'
APP_ID=os.environ.get('MAMBO_APP_ID','app.mambo.next')
WORK=Path(os.environ.get('MAMBO_BUILD_DIR',ROOT/'.build')).resolve()
DIST=ROOT/'dist'
DEPS={
 'platform.zip':('https://dl.google.com/android/repository/platform-35_r02.zip','0988cacad01b38a18a47bac14a0695f246bc76c1b06c0eeb8eb0dc825ab0c8e0'),
 'tools.zip':('https://dl.google.com/android/repository/build-tools_r35_linux.zip','bd3a4966912eb8b30ed0d00b0cda6b6543b949d5ffe00bea54c04c81e1561d88'),
 'ecj.jar':('https://repo.maven.apache.org/maven2/org/eclipse/jdt/ecj/3.40.0/ecj-3.40.0.jar','05cc22a24e7982970f63a405fc6c820bc80b806f27f3c5a6236fc475f8f7152b'),
 'xray.aar':('https://github.com/2dust/AndroidLibXrayLite/releases/download/v26.10.10/libv2ray.aar','15db760bfbc24c0492ee997784b48a7b5e1bc5032950d617cd252fc2195f7ac7'),
 'hev.aar':('https://github.com/heiher/hev-socks5-tunnel/releases/download/2.18.0/hev-socks5-tunnel.aar','15ec8ed121663b562c99caa5bb602d1009f24e5b09e733438b81988f12feaaab'),
}
def run(*args):
 args=[str(a) for a in args];p=Path(args[0])
 if p.is_file() and WORK in p.resolve().parents:p.chmod(0o755)
 env=os.environ.copy();env['LD_LIBRARY_PATH']=str(WORK/'sdk/android-15/lib64')+':'+env.get('LD_LIBRARY_PATH','')
 subprocess.run(args,check=True,env=env)
def ensure(name,url,digest):
 path=WORK/'downloads'/name;path.parent.mkdir(parents=True,exist_ok=True)
 if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
  new=path.with_suffix(path.suffix+'.new');run('curl','-fL','--retry','2','--max-time','300','-o',new,url)
  if hashlib.sha256(new.read_bytes()).hexdigest()!=digest:raise RuntimeError('Checksum mismatch: '+name)
  new.replace(path)
 return path
def main():
 WORK.mkdir(parents=True,exist_ok=True);DIST.mkdir(exist_ok=True)
 for name,(url,digest) in DEPS.items():
  p=ensure(name,url,digest)
  if name in ['platform.zip','tools.zip','xray.aar','hev.aar']:
   dest=WORK/('sdk' if name.endswith('.zip') else name.split('.')[0])
   with zipfile.ZipFile(p) as z:z.extractall(dest)
 tools=WORK/'sdk/android-15';android=WORK/'sdk/android-35/android.jar'
 for folder in ['generated','classes','dex']:
  p=WORK/folder
  if p.exists():shutil.rmtree(p)
  p.mkdir()
 run(tools/'aapt2','compile','--dir',ROOT/'res','-o',WORK/'resources.zip')
 manifest=WORK/'AndroidManifest.xml'
 manifest.write_text((ROOT/'AndroidManifest.xml').read_text().replace('package="app.mambo.next"','package="'+APP_ID+'"').replace('android:name=".MainActivity"','android:name="app.mambo.next.MainActivity"').replace('android:name=".Vpn"','android:name="app.mambo.next.Vpn"').replace('android:label="Mambo Next"','android:label="Mambo Next Preview"' if APP_ID!='app.mambo.next' else 'android:label="Mambo Next"'))
 run(tools/'aapt2','link','-o',WORK/'base.apk','-I',android,'--manifest',manifest,'--custom-package','app.mambo.next','--java',WORK/'generated','-A',ROOT/'assets','-0','wav',WORK/'resources.zip')
 classpath=os.pathsep.join(str(p) for p in [android,WORK/'xray/classes.jar',WORK/'hev/classes.jar'])
 java=os.environ.get('JAVA','java')
 run(java,'-jar',WORK/'downloads/ecj.jar','-source','1.8','-target','1.8','-encoding','UTF-8','-nowarn','-classpath',classpath,'-d',WORK/'classes',*sorted((ROOT/'src').rglob('*.java')),*sorted((WORK/'generated').rglob('*.java')))
 with zipfile.ZipFile(WORK/'app.jar','w',zipfile.ZIP_DEFLATED) as z:
  for p in (WORK/'classes').rglob('*.class'):z.write(p,p.relative_to(WORK/'classes').as_posix())
 run(java,'-cp',tools/'lib/d8.jar','com.android.tools.r8.D8','--release','--min-api','29','--lib',android,'--output',WORK/'dex',WORK/'app.jar',WORK/'xray/classes.jar',WORK/'hev/classes.jar')
 private=WORK/'private';private.mkdir(exist_ok=True);private.chmod(0o700);key=private/'mambo-signing.p12';password=private/'password.txt'
 if not key.exists():
  if APP_ID=='app.mambo.next':raise RuntimeError('Restore the original signing key to .build/private before building an update. For a separate preview use MAMBO_APP_ID=app.mambo.next.preview.')
  password.write_text(secrets.token_urlsafe(32));password.chmod(0o600)
  run('keytool','-genkeypair','-keystore',key,'-storetype','PKCS12','-storepass:file',password,'-alias','mambo','-keyalg','RSA','-keysize','3072','-validity','10000','-dname','CN=Mambo Next Alpha, O=Mambo Open Source, C=XX')
 key.chmod(0o600)
 (private/'README.txt').write_text('PRIVATE SIGNING BACKUP — Mambo Next '+APP_ID+'\nKeep this ZIP private. Never upload it to a public GitHub repository.\nRestore both files into .build/private/ (or MAMBO_BUILD_DIR/private/) before rebuilding an update.\nAlias: mambo\nThe password is in password.txt. Losing the key prevents updates of installed copies.\n',encoding='utf-8')
 for label,abis in [('arm64',['arm64-v8a']),('universal',['arm64-v8a','armeabi-v7a','x86_64','x86'])]:
  unsigned=WORK/(label+'-unsigned.apk');aligned=WORK/(label+'-aligned.apk');shutil.copyfile(WORK/'base.apk',unsigned)
  with zipfile.ZipFile(unsigned,'a',zipfile.ZIP_DEFLATED) as z:
   for p in (WORK/'dex').glob('*.dex'):z.write(p,p.name)
   for abi in abis:
    for lib in ['xray','hev']:
     files=list((WORK/lib/'jni'/abi).glob('*.so'))
     if not files:raise RuntimeError('Missing native library: '+lib+'/'+abi)
     for p in files:z.write(p,'lib/'+abi+'/'+p.name)
  run(tools/'zipalign','-f','-p','4',unsigned,aligned)
  output=DIST/('Mambo-Next-'+VERSION+'-'+label+('-preview' if APP_ID!='app.mambo.next' else '')+'.apk')
  staged=WORK/('signed-'+label+'.apk')
  if staged.exists():staged.unlink()
  run(java,'-jar',tools/'lib/apksigner.jar','sign','--ks',key,'--ks-key-alias','mambo','--ks-pass','file:'+str(password),'--out',staged,aligned)
  temporary=output.with_suffix('.apk.tmp')
  with open(temporary,'wb') as f:
   f.write(staged.read_bytes());f.flush();os.fsync(f.fileno())
  os.replace(temporary,output)
  run(java,'-jar',tools/'lib/apksigner.jar','verify','--verbose',output);run(tools/'zipalign','-c','4',output)
  print(output.name,output.stat().st_size,hashlib.sha256(output.read_bytes()).hexdigest(),flush=True)
 (DIST/'SHA256SUMS.txt').write_text('\n'.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name for p in sorted(DIST.glob('*.apk')))+'\n')
if __name__=='__main__':main()
