#!/usr/bin/env python3
"""Offline loopback integration test; uses no provider credentials or public VPN."""
from pathlib import Path
import json,os,ssl,socket,subprocess,threading,time,http.server,sys,base64
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives import serialization
root=Path(__file__).resolve().parent.parent
work=Path(os.environ.get('MAMBO_BUILD_DIR',root/'.build')).resolve()
env=os.environ.copy();java=env.get('JAVA','java')
def run(args,**kwargs):return subprocess.run([str(a) for a in args],check=True,env=env,**kwargs)
def free():
 with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
cert=work/'test-cert-v2';cert.mkdir(exist_ok=True)
if not (cert/'test.p12').exists():
 run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',cert/'key.pem','-out',cert/'cert.pem','-days','2','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1,IP:10.23.0.1'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 run(['keytool','-importcert','-noprompt','-alias','test','-file',cert/'cert.pem','-keystore',cert/'test.p12','-storepass','local-test-only'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
counts={};lock=threading.Lock()
class Handler(http.server.BaseHTTPRequestHandler):
 protocol_version='HTTP/1.1'
 def do_GET(self):
  with lock:counts.setdefault(self.client_address,[]).append(self.command)
  self.send_response(200);self.send_header('Transfer-Encoding','chunked');self.end_headers();self.wfile.write(b'4\r\ntest\r\n0\r\n\r\n')
 def do_HEAD(self):
  with lock:counts.setdefault(self.client_address,[]).append(self.command)
  self.send_response(200);self.send_header('Content-Length','123');self.end_headers()
 def log_message(self,*args):pass
http=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(cert/'cert.pem',cert/'key.pem');http.socket=tls.wrap_socket(http.socket,server_side=True);threading.Thread(target=http.serve_forever,daemon=True).start()
uuid='11111111-1111-4111-8111-111111111111';vport=free();sport=free()
server={'log':{'loglevel':'debug'},'inbounds':[{'listen':'127.0.0.1','port':vport,'protocol':'vless','settings':{'clients':[{'id':uuid}],'decryption':'none'}}],'outbounds':[{'protocol':'freedom','settings':{'finalRules':[{'action':'allow','network':'tcp','ip':['127.0.0.1/32'],'port':str(http.server_port)}]}}]}
client={'log':{'loglevel':'debug'},'inbounds':[{'listen':'127.0.0.1','port':sport,'protocol':'socks','settings':{'udp':True}}],'outbounds':[{'protocol':'vless','settings':{'vnext':[{'address':'127.0.0.1','port':vport,'users':[{'id':uuid,'encryption':'none'}]}]}}]}
wireguard='--wireguard' in sys.argv
if wireguard:
 def keypair():
  p=X25519PrivateKey.generate()
  return base64.b64encode(p.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption())).decode(),base64.b64encode(p.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode()
 sk,sp=keypair();ck,cp=keypair()
 server['inbounds']=[{'listen':'127.0.0.1','port':vport,'protocol':'wireguard','settings':{'secretKey':sk,'address':['10.2.0.1/32'],'noKernelTun':True,'peers':[{'publicKey':cp,'allowedIPs':['10.2.0.2/32']} ]}}]
 server['outbounds'][0]['settings']['redirect']='127.0.0.1:'+str(http.server_port)
 wg=work/'loopback-test.conf';wg.write_text('[Interface]\nPrivateKey = '+ck+'\nAddress = 10.2.0.2/32\n[Peer]\nPublicKey = '+sp+'\nEndpoint = 127.0.0.1:'+str(vport)+'\nAllowedIPs = 0.0.0.0/0\n')
 run([java,'-jar',work/'downloads/ecj.jar','-source','1.8','-target','1.8','-nowarn','-encoding','UTF-8','-classpath',work/'downloads/json.jar','-d',work/'test-classes',root/'src/app/mambo/next/Profiles.java',root/'src/app/mambo/next/WireGuard.java',root/'tests/BuildFixture.java'])
 run([java,'-cp',str(work/'test-classes')+os.pathsep+str(work/'downloads/json.jar'),'app.mambo.next.BuildFixture',wg,sport,work/'loopback-wg.json'])
 client=json.loads((work/'loopback-wg.json').read_text())
processes=[];core=work/'linux/xray'
try:
 for name,cfg in [('loopback-server',server),('loopback-client',client)]:
  file=work/(name+'.json');file.write_text(json.dumps(cfg));core.chmod(0o755);processes.append(subprocess.Popen([str(core),'run','-c',str(file)],stdout=open(work/(name+'.log'),'w'),stderr=subprocess.STDOUT))
 for port in ([sport] if wireguard else [vport,sport]):
  for i in range(50):
   try:
    with socket.create_connection(('127.0.0.1',port),.1):break
   except OSError:time.sleep(.05)
  else:raise RuntimeError('Xray did not start')
 run([java,'-jar',work/'downloads/ecj.jar','-source','1.8','-target','1.8','-nowarn','-encoding','UTF-8','-d',work/'test-classes',root/'src/app/mambo/next/HttpProbe.java',root/'tests/NetworkProbe.java'])
 run([java,'-Djavax.net.ssl.trustStore='+str(cert/'test.p12'),'-Djavax.net.ssl.trustStorePassword=local-test-only','-cp',work/'test-classes','app.mambo.next.NetworkProbe',sport,('https://10.23.0.1:' if wireguard else 'https://127.0.0.1:')+str(http.server_port)+'/test'])
 assert sorted(counts.values())==[['GET','GET'],['HEAD','HEAD']],counts
 print('PASS:', 'WireGuard' if wireguard else 'VLESS', 'server observed exactly two TLS connections, both reused')
finally:
 for p in processes:
  p.terminate()
  try:p.wait(timeout=3)
  except subprocess.TimeoutExpired:p.kill();p.wait()
 http.shutdown();http.server_close()
