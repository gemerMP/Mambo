"""TUN routes proxied traffic to the same Xray core as Android."""
import ipaddress
from .core import MamboError, parse_uri
from .routing import validate, dns_ips


def build_tun_config(request, server_ip):
    allowed = {'uri', 'rules', 'server_ip', 'server_ips'}
    if not isinstance(request, dict) or not {'uri', 'rules'} <= set(request) or set(request)-allowed:
        raise MamboError('Некорректный запрос TUN.')
    p = parse_uri(request['uri'])
    r = validate(request['rules'])
    try:
        primary = str(ipaddress.ip_address(server_ip))
        excluded = request.get('server_ips', [primary])
        if not isinstance(excluded, list) or not 1 <= len(excluded) <= 64:
            raise ValueError()
        addresses = list(dict.fromkeys([primary, *[str(ipaddress.ip_address(x)) for x in excluded]]))
        excluded = [str(ipaddress.ip_network(x+('/128' if ':' in x else '/32'))) for x in addresses]
    except (TypeError, ValueError):
        raise MamboError('Некорректные адреса серверов.')
    # The two local SOCKS links must never be recaptured by the system TUN.
    excluded = list(dict.fromkeys(['127.0.0.0/8', '::1/128', *excluded]))
    dns = dns_ips(p, r)
    mtu = min(r['mtu'], p['outbound']['settings'].get('mtu', 1500))
    return {
        'log': {'level': 'error', 'timestamp': False},
        'dns': {
            'servers': [{'type': 'udp', 'tag': 'vpn-dns-'+str(i), 'server': d,
                         'server_port': 53, 'detour': 'proxy'} for i, d in enumerate(dns)],
            'final': 'vpn-dns-0'},
        'inbounds': [
            {'type': 'tun', 'tag': 'tun-in', 'interface_name': 'mambo0',
             'address': ['172.29.252.1/30', 'fdfe:6d61:6d62::1/126'], 'mtu': mtu,
             'auto_route': True, 'auto_redirect': True, 'strict_route': True,
             'stack': 'mixed', 'route_exclude_address': excluded},
            {'type': 'mixed', 'tag': 'local', 'listen': '127.0.0.1', 'listen_port': 10808},
            {'type': 'socks', 'tag': 'direct-egress', 'listen': '127.0.0.1', 'listen_port': 10810}],
        'outbounds': [
            {'type': 'socks', 'tag': 'proxy', 'server': '127.0.0.1', 'server_port': 10809,
             'version': '5', 'bind_interface': 'lo'},
            {'type': 'direct', 'tag': 'direct'}],
        'route': {
            'auto_detect_interface': True, 'default_domain_resolver': 'vpn-dns-0',
            'rules': [
                {'inbound': ['direct-egress'], 'action': 'route', 'outbound': 'direct'},
                {'port': 53, 'action': 'hijack-dns'}, {'action': 'sniff'},
                {'protocol': 'dns', 'action': 'hijack-dns'}],
            'final': 'proxy'}}
