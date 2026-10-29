"""Regression tests: actual Xray sockets/HTTPS, helper pipe lifecycle, status.

No privileged networking is emulated as a successful system TUN test.
"""
import base64
import errno
import http.server
import io
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

PROJECT = Path(__file__).resolve().parents[1]
BASE = next(p for p in [PROJECT/'linux/root/usr/lib/mambo',
    PROJECT/'work/linux-fix/Mambo-Linux-x64-0.9.2/root/usr/lib/mambo'] if p.is_dir())
sys.path.insert(0, str(BASE))
from mambo.core import Engine, MamboError, Store, parse_uri, make_config
from mambo.connectivity import check_https, check_access, health_summary, access_ok
from mambo.diagnostics import CoreOutput, core_reason
from mambo.net_utils import check_local_port
from mambo.tun_config import build_tun_config
from mambo.tun_client import TunClient
from mambo.xray_bridge import XrayBridge

IDENT = '12345678-1234-4234-8234-123456789abc'
URI = f'vless://{IDENT}@127.0.0.1:50443?security=none'
XRAY = str(BASE/'bin/xray')
SINGBOX = str(BASE/'bin/sing-box')


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def wait_port(port):
    deadline = time.monotonic()+4
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=.1):
                return
        except OSError:
            time.sleep(.02)
    raise AssertionError(f'Port {port} did not start')


class RestartSockets(unittest.TestCase):
    def test_time_wait_does_not_mean_another_vpn_is_running(self):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
            listener.listen()
            peer = socket.create_connection(('127.0.0.1', port))
            accepted, _ = listener.accept()
            accepted.close()  # Active closer owns TIME_WAIT.
            peer.recv(1)
            peer.close()
        # The exact pre-0.9.2 check reproduces the user's OSError.
        with socket.socket() as old:
            with self.assertRaises(OSError) as result:
                old.bind(('127.0.0.1', port))
            self.assertEqual(result.exception.errno, errno.EADDRINUSE)
        check_local_port(port)

    def test_a_real_listener_is_still_rejected(self):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
            listener.listen()
            with self.assertRaisesRegex(MamboError, str(port)):
                check_local_port(port)

    def test_bridge_restarts_10_times_with_live_socks_clients_at_shutdown(self):
        p = parse_uri(URI)
        for cycle in range(10):
            with self.subTest(cycle=cycle):
                bridge = XrayBridge()
                self.addCleanup(bridge.stop)
                bridge.start(p, '127.0.0.1', XRAY, {'lan': False})
                with socket.create_connection(('127.0.0.1', 10809), timeout=1) as sock:
                    sock.sendall(b'\x05\x01\x00')
                    self.assertEqual(sock.recv(2), b'\x05\x00')
                    bridge.stop()
                self.assertIsNone(bridge.process)
                self.assertIsNone(bridge.runtime)


class LocalHTTPS(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        home = Path(cls.temp.name)
        cert, key = home/'cert.pem', home/'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes',
            '-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=Mambo test',
            '-addext','subjectAltName=IP:127.0.0.1,DNS:localhost'],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
        cls.context = ssl.create_default_context(cafile=str(cert))
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(204)
                self.send_header('Content-Length','0')
                self.end_headers()
            def log_message(self, *_):
                pass
        cls.http = http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert,key)
        cls.http.socket = ctx.wrap_socket(cls.http.socket,server_side=True)
        cls.thread = threading.Thread(target=cls.http.serve_forever,daemon=True)
        cls.thread.start()
        port = free_port()
        cls.uri = f'vless://{IDENT}@127.0.0.1:{port}?security=none'
        server = dict(log=dict(loglevel='error'),inbounds=[dict(listen='127.0.0.1',port=port,
            protocol='vless',settings=dict(clients=[dict(id=IDENT)],decryption='none'))],
            # Recent Xray protects private targets on VLESS servers. This test
            # allows exactly the isolated HTTPS fixture, on its random port.
            outbounds=[dict(protocol='freedom',settings=dict(finalRules=[dict(
                action='allow',network='tcp',ip=['127.0.0.1/32'],
                port=str(cls.http.server_port))]))])
        config = home/'server.json'
        config.write_text(json.dumps(server))
        cls.server = subprocess.Popen([XRAY,'run','-config',str(config)],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        wait_port(port)

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait(timeout=4)
        cls.http.shutdown()
        cls.http.server_close()
        cls.temp.cleanup()

    def check(self, port, context=None):
        return check_https(port,'127.0.0.1',timeout=2,
            target_port=self.http.server_port,context=context or self.context)

    def test_bridge_passes_validated_https_after_5_reconnects(self):
        p = parse_uri(self.uri)
        for cycle in range(5):
            with self.subTest(cycle=cycle):
                bridge = XrayBridge()
                try:
                    bridge.start(p,'127.0.0.1',XRAY,{'lan':False})
                    result = self.check(10809)
                    self.assertTrue(result['ok'],result)
                finally:
                    bridge.stop()

    def test_engine_socks_reconnect_passes_https(self):
        with tempfile.TemporaryDirectory() as home:
            store = Store(home)
            store.import_text(self.uri)
            store.save_rules({'lan':False})
            engine = Engine(store,XRAY,free_port())
            try:
                for _ in range(3):
                    engine.start(store.public()[0]['id'])
                    self.assertEqual(engine.status()['traffic']['downloaded'],0)
                    self.assertTrue(self.check(engine.port)['ok'])
                    counts=engine.refresh_traffic()
                    self.assertTrue(counts['available'],counts)
                    self.assertGreater(counts['uploaded'],0)
                    self.assertGreater(counts['downloaded'],0)
                    engine.stop()
                    self.assertGreaterEqual(engine.status()['traffic']['downloaded'],counts['downloaded'])
                    journal=(store.home/'events.log').read_text()
                    self.assertIn('загружено',journal)
                    self.assertNotIn('vless://',journal)
            finally:
                engine.stop()

    def test_untrusted_tls_certificate_reports_tls_not_success(self):
        bridge = XrayBridge()
        try:
            bridge.start(parse_uri(self.uri),'127.0.0.1',XRAY,{'lan':False})
            result = self.check(10809,ssl.create_default_context())
            self.assertFalse(result['ok'])
            self.assertEqual(result['stage'],'tls')
        finally:
            bridge.stop()


class HelperLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.script = Path(self.temp.name)/'helper.py'
        self.script.write_text('import json,sys\njson.loads(sys.stdin.readline())\n'
            'print(json.dumps(dict(event="diagnostic",message="Test diagnostic")),flush=True)\n'
            'print(json.dumps(dict(event="ready",system_dns="fixture")),flush=True)\n'
            'sys.stdin.read()\nprint(json.dumps(dict(event="stopped")),flush=True)\n')
        self.controller = TunClient()
        self.addCleanup(self.controller.stop)
        self.spawn = subprocess.Popen

    def intercepted(self, args, **kwargs):
        if args[0] == '/usr/bin/pkexec':
            return self.spawn([sys.executable,str(self.script)],**kwargs)
        return self.spawn(args,**kwargs)

    def start(self):
        with patch('mambo.tun_client.available',return_value=True), \
             patch('mambo.tun_client.subprocess.Popen',side_effect=self.intercepted):
            self.controller.start({**parse_uri(URI),'_xray_binary':XRAY},{'lan':False})

    def test_ready_diagnostic_eof_cleanup_3_sessions(self):
        for _ in range(3):
            self.controller = TunClient()
            self.addCleanup(self.controller.stop)
            self.start()
            self.assertTrue(self.controller.running())
            self.assertEqual(self.controller.core_message,'Test diagnostic')
            helper = self.controller.process
            core = self.controller.bridge.process
            self.controller.stop()
            self.assertIsNotNone(helper.poll())
            self.assertIsNotNone(core.poll())
            self.assertIsNone(self.controller.process)
            self.assertIsNone(self.controller.bridge)

    def test_authorization_cancellation_cleans_xray(self):
        self.script.write_text('import sys\nsys.stdin.readline()\nraise SystemExit(126)\n')
        with self.assertRaises(MamboError):
            self.start()
        self.assertIsNone(self.controller.process)
        self.assertIsNone(self.controller.bridge)
        check_local_port(10809)

    def test_helper_error_survives_to_the_ui(self):
        self.script.write_text('import json,sys\nsys.stdin.readline()\n'
            'print(json.dumps(dict(event="error",message="TUN test failure")),flush=True)\n')
        with self.assertRaisesRegex(MamboError,'TUN test failure'):
            self.start()
        self.assertIsNone(self.controller.process)
        self.assertIsNone(self.controller.bridge)


class RoutingAndDiagnostics(unittest.TestCase):
    def test_loopback_and_all_endpoints_bypass_tun(self):
        config = build_tun_config(dict(uri=URI,rules={},server_ips=['2001:db8::1','192.0.2.2']),'192.0.2.1')
        excluded = config['inbounds'][0]['route_exclude_address']
        self.assertEqual(set(excluded),{'127.0.0.0/8','::1/128','192.0.2.1/32','192.0.2.2/32','2001:db8::1/128'})
        self.assertTrue(config['route']['auto_detect_interface'])

    def test_wireguard_private_dns_stays_inside_tunnel(self):
        private = base64.b64encode(bytes(range(32))).decode()
        public = base64.b64encode(bytes(range(32,64))).decode()
        psk = base64.b64encode(bytes(range(64,96))).decode()
        uri = f'[Interface]\nPrivateKey = {private}\nAddress = 10.8.0.2/32\nDNS = 10.8.0.1\n[Peer]\nPublicKey = {public}\nPresharedKey = {psk}\nEndpoint = 192.0.2.1:51820\nAllowedIPs = 0.0.0.0/0\nReserved = 1,2,3\n'
        config = build_tun_config(dict(uri=uri,rules={'lan':True}),'192.0.2.1')
        self.assertEqual(config['dns']['servers'][0]['server'],'10.8.0.1')
        self.assertEqual(config['dns']['servers'][0]['detour'],'proxy')
        self.assertNotIn('10.0.0.0/8',config['inbounds'][0]['route_exclude_address'])
        with tempfile.TemporaryDirectory() as home:
            for binary,config,args in [(SINGBOX,config,['check','-c']),
                    (XRAY,make_config(parse_uri(uri),10809),['run','-test','-config'])]:
                path = Path(home)/'config.json';path.write_text(json.dumps(config))
                result = subprocess.run([binary,*args,str(path)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
                self.assertEqual(result.returncode,0,result.stdout.decode(errors='replace'))

    def test_fallback_probe_does_not_depend_on_one_website(self):
        with patch('mambo.connectivity.check_https',side_effect=[dict(ok=False,stage='http'),dict(ok=True)]) as check:
            result = check_access(10808)
        self.assertTrue(result['ok'])
        self.assertEqual(check.call_count,2)

    def test_local_failure_is_not_repeated_for_two_sites(self):
        with patch('mambo.connectivity.check_https',return_value=dict(ok=False,stage='local')) as check:
            self.assertFalse(check_access(10808)['ok'])
        self.assertEqual(check.call_count,1)

    def test_core_output_never_exports_raw_credentials(self):
        secret = 'wg://PRIVATE_KEY_SECRET@example.invalid/?publickey=secret'
        for text in ['failed: '+secret,'REALITY invalid: '+secret,'x509: '+secret,
                'operation not permitted: '+secret,'i/o timeout: '+secret]:
            reason = core_reason(text,'Xray')
            self.assertTrue(reason)
            self.assertNotIn('SECRET',reason)
            self.assertNotIn('wg://',reason)
        output = CoreOutput(io.StringIO(('error: '+secret+'\n')*200),'Xray')
        output.close()
        self.assertEqual(len(output.lines),48)
        self.assertNotIn('PRIVATE',output.reason())

    def test_running_cores_do_not_imply_system_access(self):
        self.assertFalse(access_ok(None,'tun'))
        self.assertFalse(access_ok(dict(ok=True,system=dict(ok=False)),'tun'))
        self.assertTrue(access_ok(dict(ok=True,system=dict(ok=True)),'tun'))
        self.assertTrue(access_ok(dict(ok=True),'socks'))
        self.assertIn('системный DNS',health_summary(dict(ok=True,system=dict(ok=False,message='системный DNS'))))

    def test_singbox_accepts_pinned_vless_tun_with_loopback_exclusions(self):
        config = build_tun_config(dict(uri=URI,rules={}), '127.0.0.1')
        with tempfile.TemporaryDirectory() as home:
            path=Path(home)/'config.json';path.write_text(json.dumps(config))
            result=subprocess.run([SINGBOX,'check','-c',str(path)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            self.assertEqual(result.returncode,0,result.stdout.decode(errors='replace'))


class EngineHealth(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        store = Store(self.temp.name)
        store.import_text(URI)
        self.engine = Engine(store)
        self.engine.active = store.public()[0]['id']
        self.engine.started = 1
        self.engine.scope = 'tun'
        self.controller = SimpleNamespace(process=None, ready=True, bridge=SimpleNamespace(process=None),
            running=lambda: True, diagnostic=lambda: 'Safe core diagnostic')
        self.engine.tun = self.controller

    def test_separates_local_chain_from_xray_and_system_routes(self):
        def access(port):
            return dict(ok=port == 10809, stage='proxy', message='Proxy fixture')
        with patch('mambo.connectivity.check_access', side_effect=access) as check, \
             patch('mambo.connectivity.check_system_https', return_value=dict(ok=False, stage='dns')):
            result = self.engine.check_internet()
        self.assertFalse(result['ok'])
        self.assertTrue(result['xray']['ok'])
        self.assertFalse(result['system']['ok'])
        self.assertEqual([c.args[0] for c in check.call_args_list], [10808,10809])
        self.assertEqual(result['core_message'], 'Safe core diagnostic')
        self.assertEqual(self.engine.internet, result)
        self.assertIs(self.engine.tun, self.controller)

    def test_old_probe_cannot_replace_new_session_result(self):
        def reconnect(port):
            self.engine.started = 2
            self.engine.internet = dict(ok=True, system=dict(ok=True))
            return dict(ok=True)
        with patch('mambo.connectivity.check_access', side_effect=reconnect), \
             patch('mambo.connectivity.check_system_https', return_value=dict(ok=True)):
            result = self.engine.check_internet()
        self.assertTrue(result['stale'])
        self.assertNotIn('stale', self.engine.internet)


if __name__ == '__main__':
    unittest.main(verbosity=2)
