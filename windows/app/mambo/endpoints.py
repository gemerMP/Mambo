import socket
from .core import MamboError

def resolve(profile):
    from .wireguard import endpoint
    peers=[endpoint(x['endpoint']) for x in profile['outbound']['settings']['peers']] if profile['protocol']=='wireguard' else [(profile['host'],profile['port'])]
    out=[]
    try:
        for host,port in peers:
            addresses=socket.getaddrinfo(host,port,type=socket.SOCK_DGRAM if profile['protocol']=='wireguard' else socket.SOCK_STREAM)
            addresses.sort(key=lambda a:a[0]!=socket.AF_INET)
            chosen = None
            for family, _, _, _, address in addresses:
                # UDP connect only asks the OS for a route; it sends no packet.
                try:
                    with socket.socket(family, socket.SOCK_DGRAM) as sock:
                        sock.connect(address)
                    chosen = address[0]
                    break
                except OSError:
                    continue
            if chosen is None:
                raise OSError('No usable endpoint route')
            out.append(chosen)
    except (OSError,IndexError):raise MamboError('Не удалось определить адрес VPN-сервера.')
    return out


def pin_wireguard(profile):
    import copy
    from .wireguard import endpoint
    result = copy.deepcopy(profile)
    for peer, ip in zip(result['outbound']['settings']['peers'], resolve(profile)):
        _, port = endpoint(peer['endpoint'])
        peer['endpoint'] = ('['+ip+']' if ':' in ip else ip)+':'+str(port)
    return result
