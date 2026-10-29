import json,sys,tempfile,unittest,base64
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'linux/root/usr/lib/mambo'))
from mambo.core import Store,parse_uri,parse_bundle,make_config,MamboError
from mambo.routing import validate
from mambo.tun_config import build_tun_config
from mambo.windows_tun import windows_config
class Tests(unittest.TestCase):
 def setUp(self):self.cases=json.loads((Path(__file__).parent/'wireguard-vectors.json').read_text());self.p=parse_uri(self.cases[0]['raw'])
 def test_vectors(self):
  for c in self.cases:
   with self.subTest(case=c['name']):
    if c['valid']:self.assertEqual(parse_uri(c['raw'])['protocol'],'wireguard')
    else:
     with self.assertRaises(MamboError):parse_uri(c['raw'])
 def test_database_update(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d);s.import_text(self.p['uri']);s.favorite(self.p['id'],True);old=dict(self.p);old['outbound']={}
   with s.connect() as db:db.execute('UPDATE profiles SET data=? WHERE id=?',(json.dumps(old),self.p['id']))
   s=Store(d);self.assertTrue(s.get(self.p['id'])['outbound']);self.assertTrue(s.get(self.p['id'])['favorite']);self.assertNotIn('uri',s.public()[0])
 def test_b64_conf(self):self.assertEqual(len(parse_bundle(base64.b64encode(self.p['uri'].encode()).decode())),1)
 def test_comment_identity(self):self.assertNotEqual(parse_uri('# same\n'+self.p['uri'])['id'],parse_uri('# same\n'+self.p['uri'].replace('10.2.0.2','10.2.0.3'))['id'])
 def test_dns(self):
  c=make_config(self.p,rules={'block':['ads.test']});self.assertEqual(c['routing']['rules'][0]['outboundTag'],'block');self.assertEqual(c['routing']['rules'][1]['ip'],['10.2.0.1']);self.assertEqual(c['outbounds'][0]['settings']['remoteDNS'],['10.2.0.1']);self.assertNotIn('remoteDNS',self.p['outbound']['settings']);self.assertEqual(make_config(self.p,rules={'dns':'9.9.9.9'})['outbounds'][0]['settings']['remoteDNS'],['9.9.9.9'])
 def test_v6_dns(self):
  p=parse_uri(self.p['uri'].replace('10.2.0.2/32','fd23::2/128').replace('DNS = 10.2.0.1\n',''));self.assertIn(':',make_config(p)['outbounds'][0]['settings']['remoteDNS'][0])
 def test_tun(self):
  c=build_tun_config({'uri':self.p['uri'],'rules':{},'server_ips':['1.2.3.4','2001:db8::1']},'1.2.3.4');self.assertEqual(c['inbounds'][0]['route_exclude_address'],['127.0.0.0/8','::1/128','1.2.3.4/32','2001:db8::1/128']);self.assertEqual(c['route']['rules'][0]['inbound'],['direct-egress']);c=windows_config(self.p,{},'1.2.3.4');self.assertNotIn('auto_redirect',c['inbounds'][0]);self.assertNotIn('bind_interface',c['outbounds'][0])
 def test_bad_rules(self):
  for c in [{'mtu':0},{'dns':'bad.test'},{'direct':['https://example.com']},{'evil':'x'},{'proxy':['10.0.0.0/99']}]:
   with self.subTest(c=c),self.assertRaises(MamboError):validate(c)
if __name__=='__main__':unittest.main()
