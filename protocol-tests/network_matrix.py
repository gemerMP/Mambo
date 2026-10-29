"""Loopback integration: real Xray WireGuard, DNS/UDP/TLS and desktop relay."""
from pathlib import Path
import os,sys,json,base64,socket,ssl,subprocess,threading,time,http.server,struct
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives import serialization
ROOT=Path(__file__).resolve().parents[1];BUILD=Path(os.environ.get('MAMBO_INPUTS',ROOT.parent/'tools-build'));W=BUILD/'network-matrix';W.mkdir(exist_ok=True);sys.path.insert(0,str(ROOT/'linux/root/usr/lib/mambo'))
from mambo.core import parse_uri,make_config
from mambo.probes import Cancel,connect_https,request,exact
from mambo.tun_config import build_tun_config
CORE=BUILD/'deps/core-linux/xray';SB=next((BUILD/'deps/sing-box-linux').rglob('sing-box'));CP=str(BUILD/'test-classes')+':'+str(ROOT/'android/.build/downloads/json.jar');ENV=os.environ.copy();ENV['LD_LIBRARY_PATH']='/usr/lib/jvm/java-17-openjdk-amd64/lib:/usr/lib/jvm/java-17-openjdk-amd64/lib/server'
def run(a,**kw):return subprocess.run([str(x) for x in a],check=True,env=ENV,**kw)
def port():
 with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
def pair():
 k=X25519PrivateKey.generate();return base64.b64encode(k.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption())).decode(),base64.b64encode(k.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode()
run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',W/'key.pem','-out',W/'cert.pem','-days','2','-subj','/CN=vpn.test','-addext','subjectAltName=DNS:vpn.test,IP:127.0.0.1,IP:10.23.0.1,IP:fd23::99'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
if (W/'trust.p12').exists():(W/'trust.p12').unlink()
run(['keytool','-importcert','-noprompt','-alias','test','-file',W/'cert.pem','-keystore',W/'trust.p12','-storepass','local-test-only'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
requests=[];dns_queries=[];wire_reserved=[];stop=threading.Event()
class Handler(http.server.BaseHTTPRequestHandler):
 protocol_version='HTTP/1.1'
 def do_GET(self):requests.append((self.client_address,self.command));self.send_response(200);self.send_header('Transfer-Encoding','chunked');self.end_headers();self.wfile.write(b'4\r\ntest\r\n0\r\n\r\n')
 def do_HEAD(self):requests.append((self.client_address,self.command));self.send_response(200);self.send_header('Content-Length','123');self.end_headers()
 def log_message(self,*a):pass
http=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(W/'cert.pem',W/'key.pem');http.socket=tls.wrap_socket(http.socket,server_side=True);threading.Thread(target=http.serve_forever,daemon=True).start();ctx=ssl.create_default_context(cafile=str(W/'cert.pem'))
resolver=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);resolver.bind(('127.0.0.1',0));resolver.settimeout(.3);echo=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);echo.bind(('127.0.0.1',0));echo.settimeout(.3)
def dns_loop():
 while not stop.is_set():
  try:
   data,addr=resolver.recvfrom(65535);i=12
   while data[i]:i+=1+data[i]
   i+=1;typ=struct.unpack('!H',data[i:i+2])[0];question=data[12:i+4];dns_queries.append(typ);answer=socket.inet_pton(socket.AF_INET6,'fd23::99') if typ==28 else socket.inet_aton('10.23.0.1');resolver.sendto(data[:2]+b'\x81\x80'+struct.pack('!HHHH',1,1,0,0)+question+b'\xc0\x0c'+struct.pack('!HHIH',typ,1,30,len(answer))+answer,addr)
  except socket.timeout:pass
  except OSError:return
def echo_loop():
 while not stop.is_set():
  try:data,addr=echo.recvfrom(65535);echo.sendto(data,addr)
  except socket.timeout:pass
  except OSError:return
threading.Thread(target=dns_loop,daemon=True).start();threading.Thread(target=echo_loop,daemon=True).start()
def spawn(name,cfg,sing=False):
 binary=SB if sing else CORE;binary.chmod(0o755);f=W/(name+'.json');f.write_text(json.dumps(cfg));f.chmod(0o600);log=open(W/(name+'.log'),'w');p=subprocess.Popen([str(SB if sing else CORE),'run','-c',str(f)],stdout=log,stderr=subprocess.STDOUT);p._log=log;return p
def finish(p):
 p.terminate()
 try:p.wait(timeout=4)
 except subprocess.TimeoutExpired:p.kill();p.wait()
 p._log.close()
def ready(p,n):
 for _ in range(100):
  if p.poll() is not None:raise RuntimeError('Core exited '+str(p.returncode))
  try:
   with socket.create_connection(('127.0.0.1',n),.1):return
  except OSError:time.sleep(.03)
 raise RuntimeError('Core startup timeout')
def udp_echo(socks,family):
 with socket.create_connection(('127.0.0.1',socks),3) as tcp:
  tcp.settimeout(4);tcp.sendall(b'\x05\x01\x00');assert exact(tcp,2)==b'\x05\x00';tcp.sendall(b'\x05\x03\x00\x01\0\0\0\0\0\0');h=exact(tcp,4);assert h[1]==0
  if h[3]==1:exact(tcp,4)
  elif h[3]==4:exact(tcp,16)
  else:exact(tcp,exact(tcp,1)[0])
  p=struct.unpack('!H',exact(tcp,2))[0]
  with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as udp:
   udp.settimeout(5);data=os.urandom(1024);addr=(b'\x01'+socket.inet_aton('198.18.0.1')) if family=='ipv4' else (b'\x04'+socket.inet_pton(socket.AF_INET6,'2001:db8::99'));udp.sendto(b'\0\0\0'+addr+struct.pack('!H',23400)+data,('127.0.0.1',p));r=udp.recv(65535);assert r[(22 if r[3]==4 else 10):]==data
count=0
try:
 for family in ['ipv4','ipv6']:
  sk,sp=pair();ck,cp=pair();psk=base64.b64encode(os.urandom(32)).decode();wgport=port();socks=port();address='10.2.0.2' if family=='ipv4' else 'fd23::2';dns='10.2.0.1' if family=='ipv4' else 'fd23::1'
  server={'log':{'loglevel':'warning'},'inbounds':[{'listen':'127.0.0.1','port':wgport,'protocol':'wireguard','settings':{'secretKey':sk,'address':['10.2.0.1/32','fd23::1/128'],'noKernelTun':True,'peers':[{'publicKey':cp,'preSharedKey':psk,'allowedIPs':['10.2.0.2/32','fd23::2/128']}]}}],'outbounds':[{'tag':tag,'protocol':'freedom','settings':{'redirect':'127.0.0.1:'+str(p),'finalRules':[{'action':'allow','network':'tcp,udp','ip':['127.0.0.1/32'],'port':str(p)}]}} for tag,p in [('tls',http.server_port),('dns',resolver.getsockname()[1]),('echo',echo.getsockname()[1])]],'routing':{'rules':[{'type':'field','port':'53','outboundTag':'dns'},{'type':'field','port':'23400','outboundTag':'echo'}]}}
  serverp=spawn('server',server);time.sleep(.1);relay=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);relay.bind(('127.0.0.1',0));relay.settimeout(.3);relay_stop=threading.Event();target=('127.0.0.1',wgport)
  def wire_loop(relay=relay,relay_stop=relay_stop,target=target):
   client=None
   while not relay_stop.is_set():
    try:
     data,addr=relay.recvfrom(65535)
     if addr==target:
      if client:relay.sendto(data,client)
     else:client=addr;wire_reserved.append(data[1:4]);relay.sendto(data,target)
    except socket.timeout:pass
    except OSError:return
  thread=threading.Thread(target=wire_loop,daemon=True);thread.start();relayport=relay.getsockname()[1]
  raw=f'[Interface]\nPrivateKey = {ck}\nAddress = {address}\nDNS = {dns}\nReserved = 17,34,51\n[Peer]\nPublicKey = {sp}\nPresharedKey = {psk}\nEndpoint = 127.0.0.1:{relayport}\nAllowedIPs = 0.0.0.0/0, ::/0\n';uri=f'wireguard://{ck}@127.0.0.1:{relayport}?public_key={sp}&pre_shared_key={psk}&address={address}&dns={dns}&reserved=ESIz'
  try:
   for parser in ['python-conf','python-uri','java-conf','java-uri']:
    value=raw if parser.endswith('conf') else uri;sbp=None
    if parser.startswith('java'):
     f=W/'profile.txt';f.write_text(value);f.chmod(0o600);run(['java','-cp',CP,'app.mambo.next.BuildFixture',f,socks,W/'java.json']);client=json.loads((W/'java.json').read_text())
    else:client=make_config(parse_uri(value),socks,{'lan':True,'direct':['127.0.0.0/8']})
    from mambo.traffic import Traffic
    traffic=Traffic()
    if parser.startswith('python'):traffic.configure(client)
    if parser=='python-conf' and '--relay' in sys.argv:
     client['outbounds'][1]={'tag':'direct','protocol':'socks','settings':{'servers':[{'address':'127.0.0.1','port':10810}]}}
     cfg=build_tun_config({'uri':value,'rules':{}},'127.0.0.1');cfg['inbounds']=cfg['inbounds'][1:];cfg['route'].pop('auto_detect_interface',None);cfg['outbounds'][0].pop('bind_interface',None);cfg['outbounds'][0]['server_port']=socks;sbp=spawn('desktop-relay',cfg,True);ready(sbp,10808);testport=10808
    else:testport=socks
    proc=spawn('client',client);ready(proc,socks)
    try:
     before=len(dns_queries);seen=len(wire_reserved)
     for method in ['GET','HEAD']:
      cancel=Cancel();s,u,start=connect_https('https://vpn.test:'+str(http.server_port)+'/test',testport,5,cancel,ctx)
      try:request(s,u,method,True,start,cancel);request(s,u,method,False,0,cancel)
      finally:s.close()
     assert len(dns_queries)>before;assert b'\x11\x22\x33' in wire_reserved[seen:];udp_echo(testport,family)
     if parser.startswith('python'):
      from mambo.network_checks import dns_udp
      for qtype in (1,28):assert 'UDP проходит' in dns_udp(testport,dns,'vpn.test',5,Cancel(),qtype)
      sample=traffic.read();assert sample['available'] and sample['uploaded']>1024 and sample['downloaded']>1024, sample
      assert traffic.read()['uploaded']>=sample['uploaded']
      print('PASS real core payload counters and diagnostic DNS/UDP',family,parser,flush=True)
     if parser=='python-conf':
      extra_cp=CP+':'+str(ROOT/'android/.build/classes')+':'+str(ROOT/'android/.build/sdk/android-35/android.jar')
      run(['java','-Djavax.net.ssl.trustStore='+str(W/'trust.p12'),'-Djavax.net.ssl.trustStorePassword=local-test-only','-cp',extra_cp,'app.mambo.next.NewChecks',testport,dns,'https://127.0.0.1:'+str(http.server_port)+'/direct'],stdout=subprocess.DEVNULL)
      print('PASS Java diagnostic DNS/UDP and direct HTTPS',family,flush=True)
     run(['java','-Djavax.net.ssl.trustStore='+str(W/'trust.p12'),'-Djavax.net.ssl.trustStorePassword=local-test-only','-cp',CP,'app.mambo.next.NetworkProbe',testport,'https://vpn.test:'+str(http.server_port)+'/test'],stdout=subprocess.DEVNULL)
     if sbp:
      # Exercise the direct-egress path independently from the peer tunnel.
      s,u,start=connect_https('https://127.0.0.1:'+str(http.server_port)+'/direct',10808,5,Cancel(),ctx)
      try:request(s,u,'GET',False,start,Cancel())
      finally:s.close()
     if parser=='python-conf':
      import mambo.probes as probes
      class Active:
       port=testport
       def status(self):return {'running':True,'active':parse_uri(value)['id'],'tun_pending':False}
      saved=probes.Engine
      def forbidden(*a,**kw):raise AssertionError('Active WG must reuse the current core')
      probes.Engine=forbidden;os.environ['SSL_CERT_FILE']=str(W/'cert.pem')
      try:
       for method in ['GET','HEAD']:
        for mode in ['Default','Double','KeepAlive']:assert 'мс' in probes.measure(parse_uri(value),Active(),{'ping_type':method,'ping_mode':mode,'timeout':5,'test_url':'https://vpn.test:'+str(http.server_port)+'/test'},Cancel())
      finally:probes.Engine=saved
      print('PASS active WG reuse × all proxy ping modes',family,flush=True)
     count+=1;print('PASS',family,parser,'PSK Reserved-on-wire DNS UDP GET HEAD KeepAlive',flush=True)
    finally:
     finish(proc)
     if sbp:finish(sbp)
   invalid=json.loads(json.dumps(client));invalid['outbounds'][0]['settings']['peers'][0]['preSharedKey']=base64.b64encode(os.urandom(32)).decode();proc=spawn('wrong-psk',invalid);ready(proc,socks);before=len(requests)
   try:
    try:s,u,start=connect_https('https://vpn.test:'+str(http.server_port)+'/test',socks,1,Cancel(),ctx);s.close();raise AssertionError('Wrong PSK accepted')
    except (TimeoutError,OSError):pass
    assert len(requests)==before;print('PASS wrong PSK rejected',family,flush=True)
   finally:finish(proc)
  finally:relay_stop.set();relay.close();thread.join(1);finish(serverp)
 print('PASS:',count,'WireGuard variants;',len(requests),'HTTPS requests;',len(dns_queries),'tunnel DNS queries',flush=True)
finally:stop.set();resolver.close();echo.close();http.shutdown();http.server_close()
