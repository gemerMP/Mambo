"""User workflows and failure boundaries added in 0.9.3."""
from test_desktop_update import APP, URI, pump_until
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
from mambo.core import Store, parse_uri, make_config, MamboError
from mambo.qt_app import Window
from mambo.journal import append
from mambo.network_checks import comparison
from mambo.net_utils import check_local_port

class Workflows(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.store=Store(self.temp.name);self.store.import_text(URI)
  self.store.import_text(URI.replace('127.0.0.1','127.0.0.2').replace('Local%20fixture','Second'))
  self.w=Window(self.store);self.w.show();APP.processEvents();self.addCleanup(self.close)
 def close(self):
  self.w.close();pump_until(lambda:not self.w.isVisible())
 def click_server(self,index):
  self.w.list.setCurrentRow(index)
  item=self.w.list.item(index);point=QPointF(self.w.list.visualItemRect(item).center())
  for kind,buttons in [(QEvent.MouseButtonPress,Qt.LeftButton),(QEvent.MouseButtonRelease,Qt.NoButton)]:
   QApplication.sendEvent(self.w.list.viewport(),QMouseEvent(kind,point,Qt.LeftButton,buttons,Qt.NoModifier))
  APP.processEvents()
 def test_home_server_selection_returns_home_and_changes_profile(self):
  w=self.w;w.server_picker.click();self.assertEqual(w.pages.currentIndex(),1)
  wanted=w.list.item(1).data(Qt.UserRole);self.click_server(1)
  self.assertEqual(w.pages.currentIndex(),0);self.assertEqual(w.selected()['id'],wanted)
  self.assertEqual(w.selected_label.text(),w.selected()['name'])
 def test_normal_server_tab_selection_stays_on_server_tab(self):
  self.w.nav.setCurrentRow(1);self.click_server(1);self.assertEqual(self.w.pages.currentIndex(),1)
 def test_abandoning_picker_clears_return_home(self):
  w=self.w;w.server_picker.click();w.nav.setCurrentRow(2);w.nav.setCurrentRow(1);self.click_server(1);self.assertEqual(w.pages.currentIndex(),1)
 def test_server_ping_stays_in_list_and_preserves_ping_preferences(self):
  w=self.w;w.pt.setCurrentIndex(2);w.pm.setCurrentIndex(2);w.pref('ping_type','TCP');w.pref('ping_mode','KeepAlive');w.nav.setCurrentRow(1)
  with patch('mambo.qt_app.measure',return_value='42 мс · GET') as measured:
   w.probe(False,True);pump_until(lambda:not w.jobs)
   self.assertEqual(measured.call_args.args[2]['ping_type'],'GET')
  self.assertEqual(w.pages.currentIndex(),1);self.assertIn('42 мс',w.server_ping_result.text())
  self.assertIn('42 мс',w.list.currentItem().text());self.assertEqual(w.prefs['ping_type'],'TCP');self.assertEqual(w.prefs['ping_mode'],'KeepAlive')
 def test_traffic_direction_and_theme_do_not_clear_totals(self):
  w=self.w;state=dict(running=True,scope='socks',uptime_seconds=3,traffic=dict(downloaded=2048,uploaded=1024,download_rate=512,upload_rate=256,available=True))
  w.update_connection(state);self.assertEqual(w.downloaded.text(),'↓  2.0 КиБ');self.assertEqual(w.uploaded.text(),'↑  1.0 КиБ');w.apply_theme('minimal-dark');self.assertEqual(w.downloaded.text(),'↓  2.0 КиБ')
 def test_worker_events_appear_without_reopening_logs(self):
  append(self.store.home,'WireGuard: тестовое событие');self.w.poll();self.assertIn('тестовое событие',self.w.log_text.toPlainText())
 def test_diagnostics_results_reach_page_and_journal(self):
  w=self.w;w.nav.setCurrentRow(2)
  with patch('mambo.network_checks.run',return_value='DNS A: RCODE 0 · UDP проходит'):
   w.diagnose();pump_until(lambda:not w.jobs)
  self.assertIn('UDP проходит',w.diagnostic_result.text());self.assertIn('UDP проходит',w.log_text.toPlainText())
 def test_no_removed_slogan_in_any_theme(self):
  for key in wkeys():
   self.w.apply_theme(key);self.assertNotIn('Связь без суеты',self.w.home_title.text())

def wkeys():
 from mambo.ui import THEMES
 return THEMES

class Boundaries(unittest.TestCase):
 def test_windows_time_wait_without_listener_allows_start(self):
  with patch('mambo.net_utils.os.name','nt'),patch('mambo.net_utils.socket.socket') as mock:
   mock.return_value.__enter__.return_value.connect_ex.return_value=10061
   check_local_port(10808)
 def test_windows_live_listener_is_rejected(self):
  with patch('mambo.net_utils.os.name','nt'),patch('mambo.net_utils.socket.socket') as mock:
   mock.return_value.__enter__.return_value.connect_ex.return_value=0
   with self.assertRaises(MamboError):check_local_port(10808)
 def test_mtu_reaches_wireguard_outbound_without_modifying_profile(self):
  vectors=json.loads((Path(__file__).parents[1]/'protocol-tests/wireguard-vectors.json').read_text());p=parse_uri(vectors[0]['raw']);old=p['outbound']['settings']['mtu'];config=make_config(p,rules={'mtu':1280});self.assertEqual(config['outbounds'][0]['settings']['mtu'],1280);self.assertEqual(p['outbound']['settings']['mtu'],old)
 def test_journal_masks_keys_and_links(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder);append(path,'key '+'A'*43+'= vless://secret@example.com:443 https://secret.test/path')
   value=(path/'events.log').read_text();self.assertNotIn('A'*43,value);self.assertNotIn('secret',value)
 def test_comparison_does_not_claim_censorship_from_timeout(self):
  self.assertIn('причину определить нельзя',comparison(False,False));self.assertIn('Возможны',comparison(False,True))
