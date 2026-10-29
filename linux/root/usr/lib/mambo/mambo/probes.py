"""Cancellable TCP/ICMP and actual HTTPS-over-proxy measurements."""
import http.client,os,re,socket,ssl,struct,subprocess,tempfile,threading,time
from pathlib import Path
from urllib.parse import urlsplit
from .core import Engine,Store,MamboError
class Cancel:
 def __init__(self):self.event=threading.Event();self.socket=None;self.process=None
 def check(self):
  if self.event.is_set():raise MamboError('Проверка отменена.')
 def stop(self):
  self.event.set()
  if self.socket:
   try:self.socket.shutdown(socket.SHUT_RDWR)
   except OSError:pass
   try:self.socket.close()
   except OSError:pass
  if self.process and self.process.poll() is None:self.process.terminate()
def exact(s,n):
 out=b''
 while len(out)<n:
  b=s.recv(n-len(out))
  if not b:raise MamboError('Прокси закрыл соединение.')
  out+=b
 return out
def connect_https(url,port,timeout,cancel,context=None):
 u=urlsplit(url)
 if u.scheme!='https' or not u.hostname or u.username or u.password or any(ord(c)<=32 for c in url):raise MamboError('Для проверки нужен корректный HTTPS URL.')
 s=socket.create_connection(('127.0.0.1',port),timeout);cancel.socket=s;cancel.check();start=time.monotonic()
 try:
  s.sendall(b'\x05\x01\x00')
  if exact(s,2)!=b'\x05\x00':raise MamboError('Прокси отклонил запрос.')
  host=u.hostname.encode('idna')
  if len(host)>255:raise MamboError('Слишком длинное имя сервера.')
  s.sendall(b'\x05\x01\x00\x03'+bytes([len(host)])+host+struct.pack('!H',u.port or 443));head=exact(s,4)
  if head[1]:raise MamboError('Сервер не пропускает тестовый запрос.')
  n={1:4,4:16}.get(head[3]);n=exact(s,1)[0] if head[3]==3 else n
  if n is None:raise MamboError('Некорректный ответ SOCKS.')
  exact(s,n+2);s=(context or ssl.create_default_context()).wrap_socket(s,server_hostname=u.hostname);cancel.socket=s;return s,u,start
 except BaseException:s.close();raise
def request(s,u,method,keep,start,cancel):
 cancel.check();start=start or time.monotonic();path=(u.path or '/')+('?' +u.query if u.query else '');host=('['+u.hostname+']') if ':' in u.hostname else u.hostname
 if u.port and u.port!=443:host+=':'+str(u.port)
 s.sendall((method+' '+path+' HTTP/1.1\r\nHost: '+host+'\r\nUser-Agent: Mambo/0.9.3\r\nAccept-Encoding: identity\r\nConnection: '+('keep-alive' if keep else 'close')+'\r\n\r\n').encode('ascii'))
 r=http.client.HTTPResponse(s,method=method);r.begin()
 if not 200<=r.status<400:raise MamboError('URL теста вернул HTTP '+str(r.status))
 total=0
 while True:
  cancel.check();b=r.read(16384);total+=len(b)
  if total>524288:raise MamboError('Ответ URL больше 512 КБ; выбери generate_204.')
  if not b:break
 if keep and r.will_close:raise MamboError('URL теста не поддерживает KeepAlive.')
 r.close();return max(1,round((time.monotonic()-start)*1000))
def measure(profile,engine,settings,cancel):
 kind=settings.get('ping_type','GET');mode=settings.get('ping_mode','Default');timeout=int(settings.get('timeout',8));cancel.check()
 if not 1<=timeout<=60:raise MamboError('Тайм-аут: 1–60 секунд.')
 if kind=='TCP':
  if profile['protocol']=='wireguard':raise MamboError('TCP неприменим к WireGuard (UDP). Выбери Proxy GET/HEAD.')
  start=time.monotonic()
  with socket.create_connection((profile['host'],profile['port']),timeout) as s:cancel.socket=s;cancel.check()
  cancel.socket=None;return str(max(1,round((time.monotonic()-start)*1000)))+' мс · TCP'
 if kind=='ICMP':
  from .endpoints import resolve
  host=resolve(profile)[0];args=['ping','-n','1','-w',str(timeout*1000),host] if os.name=='nt' else ['ping','-n','-c','1','-W',str(timeout),host]
  p=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,creationflags=0x08000000 if os.name=='nt' else 0);cancel.process=p
  try:
   output=p.communicate(timeout=timeout+2)[0].decode(errors='replace');cancel.check();m=re.search(r'(?:time|время)[=<]\s*([0-9.,]+)',output,re.I)
   if p.returncode or not m:raise MamboError('ICMP недоступен или заблокирован.')
   return m.group(1)+' мс · ICMP'
  finally:
   if p.poll() is None:p.kill();p.wait()
   cancel.process=None
 if kind not in ('GET','HEAD') or mode not in ('Default','Double','KeepAlive'):raise MamboError('Неизвестный режим пинга.')
 state=engine.status();reuse=state['running'] and state['active']==profile['id'];owned=None;directory=None
 if profile['protocol']=='wireguard' and (state['tun_pending'] or (state['running'] and not reuse)):raise MamboError('WireGuard: отключи VPN перед проверкой другого профиля.')
 try:
  port=engine.port
  if not reuse:
   directory=tempfile.TemporaryDirectory(prefix='mambo-probe-');store=Store(Path(directory.name));store.import_text(profile['uri']);store.save_rules({'lan':False,'dns':engine.store.rules().get('dns',''),'mtu':engine.store.rules().get('mtu',1500)})
   with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
   owned=Engine(store,engine.binary(),port);owned.start(profile['id'])
  values=[]
  for _ in range(2 if mode=='Double' else 1):
   cancel.check();s,u,start=connect_https(settings.get('test_url','https://www.gstatic.com/generate_204'),port,timeout,cancel)
   try:
    first=request(s,u,kind,mode=='KeepAlive',start,cancel);values.append(request(s,u,kind,False,0,cancel) if mode=='KeepAlive' else first)
   finally:s.close();cancel.socket=None
  return str(min(values))+' мс · '+kind+(' · второй запрос' if mode=='KeepAlive' else ' · лучший из 2' if mode=='Double' else '')
 finally:
  if owned:owned.stop()
  if directory:directory.cleanup()
