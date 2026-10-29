#!/usr/bin/env python3
from pathlib import Path
import importlib.util,os,subprocess,zipfile
root=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('build',root/'build.py');build=importlib.util.module_from_spec(spec);spec.loader.exec_module(build)
work=build.WORK
build.ensure('ecj.jar',*build.DEPS['ecj.jar'])
build.ensure('json.jar','https://repo.maven.apache.org/maven2/org/json/json/20240303/json-20240303.jar','3cf6cd6892e32e2b4c1c39e0f52f5248a2f5b37646fdfbb79a66b46b618414ed')
core=root.parent.parent/'tools-build/deps/core-linux/xray'
if not core.exists():raise RuntimeError('Run packaging/prepare-build.py first')
import shutil
(work/'linux').mkdir(exist_ok=True);shutil.copy2(core,work/'linux/xray')
classes=work/'test-classes';classes.mkdir(exist_ok=True)
java=os.environ.get('JAVA','java')
build.run(java,'-jar',work/'downloads/ecj.jar','-source','1.8','-target','1.8','-encoding','UTF-8','-nowarn','-classpath',work/'downloads/json.jar','-d',classes,root/'src/app/mambo/next/Profiles.java',root/'src/app/mambo/next/WireGuard.java',root/'src/app/mambo/next/HttpProbe.java',root/'tests/Regression.java')
build.run(java,'-cp',str(classes)+os.pathsep+str(work/'downloads/json.jar'),'app.mambo.next.Regression',work/'test-configs')
for file in sorted((work/'test-configs').glob('*.json')):
 core=work/'linux/xray';core.chmod(0o755);r=subprocess.run([str(core),'run','-test','-c',str(file)],capture_output=True,text=True)
 if r.returncode:raise RuntimeError(file.name+': '+r.stdout+r.stderr)
 print('PASS Xray config:',file.name)
