"""Recovered WireGuard URI/.conf parser from the 0.9.0 development session."""
import base64, hashlib, ipaddress, re
from urllib.parse import unquote, urlsplit
from .core import MamboError

def fail(message): raise MamboError('WireGuard: '+message)
def key(value):
    try:
        value=value.strip().replace('-','+').replace('_','/')
        raw=base64.b64decode(value+'='*(-len(value)%4),validate=True)
        if len(raw)!=32: raise ValueError()
        return base64.b64encode(raw).decode()
    except (ValueError,TypeError): fail('ключ должен содержать 32 байта Base64')
def number(s,low,high,label):
    try:
        n=int(s)
        if not low<=n<=high: raise ValueError()
        return n
    except (ValueError,TypeError): fail('некорректный '+label)
def networks(value):
    try: return [str(ipaddress.ip_interface(s)) for s in re.split(r'[,\s]+',value.strip()) if s]
    except ValueError: fail('некорректный IP/CIDR')
def dns(value):
    try:return [str(ipaddress.ip_address(s)) for s in re.split(r'[,\s]+',value.strip()) if s]
    except ValueError:fail('DNS должен содержать IP-адреса')
def reserved(value):
    try:
        v=value.strip().strip('[]')
        r=[int(x.strip()) for x in v.split(',')] if ',' in v else list(base64.b64decode(v+'='*(-len(v)%4),altchars=b'-_',validate=True))
        if len(r)!=3 or any(not 0<=x<=255 for x in r):raise ValueError()
        return r
    except (ValueError,TypeError):fail('Reserved должен содержать 3 байта')
def field(s):return s.lower().replace('_','').replace('-','')
def put(m,k,v):
    if k in m:
        if k in ('address','dns','allowedips'):v=m[k]+','+v
        else:fail('повторяющийся параметр')
    m[k]=v
def allowed(m,keys):
    if set(m)-set(keys.split()):fail('неподдерживаемый параметр; AmneziaWG и команды wg-quick не поддерживаются')
def endpoint(s):
    try:
        u=urlsplit('udp://'+s)
        if not u.hostname or not u.port or u.username or u.path or u.query or u.fragment or any(ord(c)<33 for c in s):raise ValueError()
        if not re.fullmatch(r'[A-Za-z0-9_.:\-]+',u.hostname):raise ValueError()
        return u.hostname,u.port
    except ValueError:fail('Endpoint должен содержать хост и порт; IPv6 — в квадратных скобках')
def parse(raw):
    raw=raw.strip().lstrip('\ufeff');name=''
    if len(raw)>65536:fail('профиль больше 64 КБ')
    if raw.lower().startswith(('wg://','wireguard://')):
        rest=raw.split('://',1)[1]
        if '@' not in rest:fail('в ссылке нужен приватный ключ перед @')
        secret,rest=rest.split('@',1)
        try:u=urlsplit('wg://'+rest);h=u.hostname;p=u.port or 51820
        except ValueError:fail('некорректная ссылка')
        if not h or u.path not in ('','/'):fail('некорректный адрес ссылки')
        iface={}
        for part in u.query.split('&'):
            if not part:continue
            k,_,v=part.partition('=');k=field(unquote(k));k={'ip':'address','localaddress':'address','psk':'presharedkey','publick':'publickey','pubkey':'publickey'}.get(k,k)
            put(iface,k,unquote(v))
        allowed(iface,'address publickey presharedkey allowedips keepalive persistentkeepalive mtu reserved dns')
        iface['privatekey']=unquote(secret);iface['endpoint']=('['+h+']' if ':' in h else h)+':'+str(p)
        peers=[iface.copy()];name=unquote(u.fragment)
    else:
        iface={};peers=[];section=None;seen=False
        for line in raw.splitlines():
            line=line.strip()
            if not line or line.startswith(('#',';')):continue
            if line.lower()=='[interface]':
                if seen:fail('несколько Interface')
                seen=True;section=iface;continue
            if line.lower()=='[peer]':section={};peers.append(section);continue
            if section is None or '=' not in line or line.startswith('['):fail('некорректный .conf')
            k,v=line.split('=',1);put(section,field(k.strip()),re.split(r'\s[#;]',v,1)[0].strip())
        allowed(iface,'privatekey address dns mtu reserved listenport table saveconfig')
        for peer in peers:
            allowed(peer,'publickey presharedkey endpoint allowedips persistentkeepalive reserved')
            if 'reserved' in peer:
                if 'reserved' in iface and reserved(peer['reserved'])!=reserved(iface['reserved']):fail('разный Reserved у пиров не поддерживается')
                iface['reserved']=peer['reserved']
    address=networks(iface.get('address',''))
    if not address:fail('нет Address')
    if not peers:fail('нет Peer')
    ps=[]
    for peer in peers:
        endpoint(peer.get('endpoint',''))
        ips=networks(peer.get('allowedips','0.0.0.0/0,::/0'))
        if not ips:fail('нет AllowedIPs')
        p={'publicKey':key(peer.get('publickey','')),'endpoint':peer['endpoint'],'allowedIPs':ips,'keepAlive':number(peer.get('persistentkeepalive',peer.get('keepalive','25')),0,65535,'KeepAlive')}
        if 'presharedkey' in peer:p['preSharedKey']=key(peer['presharedkey'])
        ps.append(p)
    h,port=endpoint(ps[0]['endpoint'])
    settings={'secretKey':key(iface.get('privatekey','')),'address':address,'peers':ps,'mtu':number(iface.get('mtu','1420'),576,9000,'MTU'),'reserved':reserved(iface['reserved']) if 'reserved' in iface else [0,0,0],'noKernelTun':True}
    identity=raw if '[interface]' in raw.lower() else raw.split('#')[0]
    return {'id':hashlib.sha256(identity.encode()).hexdigest()[:16],'uri':raw,'name':(name or 'WireGuard · '+h)[:120],'host':h,'port':port,'protocol':'wireguard','transport':'udp','security':'wireguard','dns':','.join(dns(iface.get('dns',''))),'outbound':{'tag':'proxy','protocol':'wireguard','settings':settings}}
