"""Validated routing shared by SOCKS, TUN and probes."""
import copy,ipaddress,re
from .core import MamboError
DEFAULT={'direct':[],'block':[],'proxy':[],'fallback':'proxy','dns':'','lan':True,'ipv6':True,'mtu':1500}
LAN=['10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','169.254.0.0/16','fc00::/7','fe80::/10']
def validate(value):
    if not isinstance(value,dict) or set(value)-set(DEFAULT):raise MamboError('Некорректные настройки маршрутизации.')
    r={**DEFAULT,**value}
    if r['fallback'] not in ('proxy','direct') or type(r['mtu']) is not int or not 576<=r['mtu']<=9000:raise MamboError('Некорректный маршрут или MTU (576–9000).')
    if any(type(r[k]) is not bool for k in ('lan','ipv6')):raise MamboError('Некорректные параметры сети.')
    for k in ['block','direct','proxy']:
        if not isinstance(r[k],list) or len(r[k])>200:raise MamboError('Допустимо до 200 правил в списке.')
        for x in r[k]:
            if not isinstance(x,str):raise MamboError('Нужен домен или IP/CIDR.')
            if '/' in x or ':' in x:
                try:ipaddress.ip_network(x,strict=False)
                except ValueError:raise MamboError('Некорректная сеть IP/CIDR.')
            elif not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?',x):raise MamboError('Укажи домен без URL или IP/CIDR.')
    if any(set(r[a]) & set(r[b]) for a,b in [('block','direct'),('block','proxy'),('direct','proxy')]):raise MamboError('Одинаковое правило не может быть сразу в двух списках.')
    if not isinstance(r['dns'],str):raise MamboError('DNS должен содержать IP-адреса.')
    dns_ips({'dns':r['dns']},{**r,'dns':''}) if r['dns'] else None
    return r
def dns_ips(profile,rules):
    text=rules.get('dns') or profile.get('dns') or ''
    if not text:
        v4=profile.get('protocol')!='wireguard' or any(':' not in x for x in profile['outbound']['settings']['address'])
        text='1.1.1.1,1.0.0.1' if v4 else '2606:4700:4700::1111,2606:4700:4700::1001'
    try:return [str(ipaddress.ip_address(x)) for x in re.split(r'[,\s]+',text) if x]
    except ValueError:raise MamboError('DNS должен содержать IP-адреса.')
def fields(items,tag):
    ips=[];domains=[]
    for x in items:
        try:ips.append(str(ipaddress.ip_network(x,strict=False)))
        except ValueError:domains.append('domain:'+x)
    return ([{'type':'field','ip':ips,'outboundTag':tag}] if ips else [])+([{'type':'field','domain':domains,'outboundTag':tag}] if domains else [])
def config(profile,port,rules=None):
    if type(port) is not int or not 1024<=port<=65535:raise MamboError('SOCKS-порт должен быть от 1024 до 65535.')
    r=validate(rules or {});dns=dns_ips(profile,r);routing=[]
    routing+=fields(r['block'],'block')
    routing.append({'type':'field','ip':dns,'port':'53','network':'tcp,udp','outboundTag':'proxy'})
    routing+=fields(r['proxy'],'proxy')
    routing+=fields(r['direct']+(LAN if r['lan'] else []),'direct')
    if not r['ipv6']:routing.append({'type':'field','ip':['::/0'],'outboundTag':'block'})
    routing.append({'type':'field','network':'tcp,udp','outboundTag':r['fallback']})
    out=copy.deepcopy(profile['outbound'])
    if profile['protocol']=='wireguard':
        out['settings']['remoteDNS']=dns
        out['settings']['mtu']=min(r['mtu'], out['settings'].get('mtu',1420))
    return {'log':{'loglevel':'warning'},'inbounds':[{'tag':'local','listen':'127.0.0.1','port':port,'protocol':'socks','settings':{'auth':'noauth','udp':True},'sniffing':{'enabled':True,'destOverride':['http','tls','quic'],'routeOnly':True}}],'outbounds':[out,{'tag':'direct','protocol':'freedom'},{'tag':'block','protocol':'blackhole'}],'routing':{'domainStrategy':'AsIs','rules':routing}}
