"""Regression checks for the Linux UI update and the real core session clock."""
import base64
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
BASE = next(p for p in [PROJECT/'linux/root/usr/lib/mambo',
    PROJECT/'work/linux-fix/Mambo-Linux-x64-0.9.2/root/usr/lib/mambo',
    PROJECT/'work/linux-redesign/Mambo-Linux-x64-0.9.1/root/usr/lib/mambo'] if p.is_dir())
sys.path[:0] = [str(BASE), str(BASE/'vendor')]
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFontInfo, QKeyEvent
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea
from mambo.core import Engine, MamboError, Store
from mambo.qt_app import Window
from mambo.ui import THEMES, current_theme, format_duration, setup_fonts

URI = 'vless://12345678-1234-4234-8234-123456789abc@127.0.0.1:50443?security=none#Local%20fixture'


def pump_until(predicate, seconds=8):
    deadline = time.monotonic()+seconds
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('UI operation timed out')


APP = QApplication([])
APP.setStyle('Fusion')
setup_fonts()


class SessionClock(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.store.import_text(URI)
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]
        self.engine = Engine(self.store, port=port)
        self.ident = self.store.public()[0]['id']
        self.addCleanup(self.engine.stop)

    def test_real_xray_session_clock_disconnect_and_reconnect(self):
        self.assertEqual(self.engine.status()['uptime_seconds'], 0)
        first = self.engine.start(self.ident)
        self.assertTrue(first['running'])
        with patch('mambo.core.time.monotonic', return_value=self.engine.started_monotonic+65.9), \
             patch('mambo.core.time.time', return_value=100):
            self.assertEqual(format_duration(self.engine.status()['uptime_seconds']), '00:01:05')
        self.engine.stop()
        self.assertEqual(self.engine.status()['uptime_seconds'], 0)
        restarted = self.engine.start(self.ident)
        self.assertTrue(restarted['running'])
        self.assertLess(restarted['uptime_seconds'], 1)

    def test_core_crash_clears_elapsed_time(self):
        self.engine.start(self.ident)
        self.engine.process.terminate()
        self.engine.process.wait(timeout=3)
        state = self.engine.status()
        self.assertFalse(state['running'])
        self.assertEqual(state['uptime_seconds'], 0)
        self.assertIsNone(self.engine.started_monotonic)

    def test_failed_start_never_starts_timer(self):
        self.engine.executable = '/nonexistent-mambo-fixture'
        with self.assertRaises(MamboError):
            self.engine.start(self.ident)
        self.assertEqual(self.engine.status()['uptime_seconds'], 0)

    def test_tun_timer_starts_only_after_ready_and_resets(self):
        class Controller:
            process = None
            bridge = None
            ready = False
            error = None
            def start(controller, profile, rules):
                self.assertEqual(self.engine.status()['uptime_seconds'], 0)
                controller.ready = True
            def running(controller):
                return controller.ready
            def stop(controller):
                controller.ready = False
        self.engine.port = 10808
        with patch('mambo.tun_client.TunClient', Controller):
            state = self.engine.start(self.ident, 'tun')
            self.assertTrue(state['running'])
            self.assertLess(state['uptime_seconds'], 1)
            self.engine.stop()
            self.assertEqual(self.engine.status()['uptime_seconds'], 0)

    def test_long_and_invalid_durations(self):
        self.assertEqual(format_duration(90061), '25:01:01')
        for value in [None, -1, 'bad', float('inf'), float('nan')]:
            self.assertEqual(format_duration(value), '00:00:00')


class NativeUI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.store.import_text(URI)
        self.window = Window(self.store)
        self.window.show()
        APP.processEvents()
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.close()
        pump_until(lambda: not self.window.isVisible())

    def test_visible_theme_picker_and_tiles_save_the_same_choice(self):
        w = self.window
        for i, key in enumerate(THEMES):
            w.theme_picker.setCurrentIndex(i)
            APP.processEvents()
            self.assertEqual(current_theme(w.prefs), key)
            self.assertTrue(w.theme_tiles[key].isChecked())
            self.assertEqual(sum(tile.isChecked() for tile in w.theme_tiles.values()), 1)
            self.assertEqual(w.art.isHidden(), key == 'minimal-dark')
        w.theme_tiles['green-light'].click()
        self.assertEqual(w.theme_picker.currentData(), 'green-light')
        w.close()
        self.window = Window(Store(self.temp.name))
        self.window.show()
        APP.processEvents()
        self.assertEqual(self.window.theme_picker.currentData(), 'green-light')

    def test_minimal_theme_preserves_profiles_and_character_preferences(self):
        w = self.window
        before = self.store.list()
        w.characters.setChecked(False)
        self.assertFalse(w.companion_card.isHidden())
        self.assertTrue(w.art.isHidden())
        w.apply_theme('minimal-dark')
        self.assertTrue(w.companion_card.isHidden())
        self.assertFalse(w.characters.isEnabled())
        w.apply_theme('red-dark')
        self.assertFalse(w.companion_card.isHidden())
        self.assertTrue(w.art.isHidden())
        w.characters.setChecked(True)
        self.assertFalse(w.art.isHidden())
        self.assertEqual(self.store.list(), before)

    def test_legacy_palette_and_cyrillic_font(self):
        for color in ['pink', 'green', 'red']:
            for light in [False, True]:
                self.assertEqual(current_theme(dict(color=color, light=light)),
                    color+('-light' if light else '-dark'))
        self.assertEqual(QFontInfo(APP.font()).family(), 'Noto Sans')

    def test_timer_survives_theme_switch_and_returns_to_zero(self):
        w = self.window
        state = dict(running=True, uptime_seconds=3661, scope='socks')
        w.update_connection(state)
        self.assertEqual(w.elapsed.text(), '01:01:01')
        w.theme_picker.setCurrentIndex(6)
        self.assertEqual(w.elapsed.text(), '01:01:01')
        w.update_connection(dict(running=False, uptime_seconds=3661))
        self.assertEqual(w.elapsed.text(), '00:00:00')

    def test_keyboard_navigation_and_server_picker(self):
        w = self.window
        w.nav.setCurrentRow(0)
        QApplication.sendEvent(w.nav, QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier))
        QApplication.sendEvent(w.nav, QKeyEvent(QEvent.KeyRelease, Qt.Key_Down, Qt.NoModifier))
        self.assertEqual(w.pages.currentIndex(), 1)
        w.nav.setCurrentRow(0)
        w.server_picker.click()
        self.assertEqual(w.pages.currentIndex(), 1)

    def test_async_connect_timer_and_disconnect_with_real_xray(self):
        w = self.window
        w.scope.setCurrentIndex(1)
        with patch('mambo.connectivity.check_access', return_value=dict(ok=True)):
            w.power.click()
            pump_until(lambda: not w.jobs)
        self.assertTrue(w.state['running'])
        pump_until(lambda: w.elapsed.text() != '00:00:00', 3)
        self.assertEqual(w.status.text(), 'Подключено')
        w.power.click()
        pump_until(lambda: not w.jobs)
        self.assertEqual(w.elapsed.text(), '00:00:00')
        self.assertEqual(w.status.text(), 'Отключено')

    def test_wireguard_profile_survives_appearance_updates(self):
        # Non-secret fixed data belongs only to this isolated test store.
        a = base64.b64encode(bytes(range(32))).decode()
        b = base64.b64encode(bytes(range(32,64))).decode()
        self.store.import_text(f'[Interface]\nPrivateKey = {a}\nAddress = 10.8.0.2/32\nDNS = 1.1.1.1\n[Peer]\nPublicKey = {b}\nEndpoint = 127.0.0.1:51820\nAllowedIPs = 0.0.0.0/0\nReserved = 1,2,3\n')
        before = self.store.list()
        for key in THEMES:
            self.window.apply_theme(key)
        self.assertEqual(self.store.list(), before)
        wg = next(p for p in before if p['protocol'] == 'wireguard')
        self.assertEqual(self.store.get(wg['id'])['outbound']['settings']['reserved'], [1,2,3])

    def test_connection_label_requires_a_successful_system_probe(self):
        w = self.window
        state = dict(running=True, scope='tun', uptime_seconds=15)
        w.update_connection(state)
        self.assertEqual(w.status.text(), 'Проверяем доступ…')
        self.assertEqual(w.elapsed.text(), '00:00:15')
        state['internet'] = dict(ok=True, system=dict(ok=False, stage='dns'))
        w.update_connection(state)
        self.assertEqual(w.status.text(), 'Нет доступа')
        state['internet']['system']['ok'] = True
        w.update_connection(state)
        self.assertEqual(w.status.text(), 'Подключено')

    def test_stale_probe_after_reconnect_triggers_current_session_check(self):
        w = self.window
        w.state = dict(running=True)
        with patch.object(w,'submit') as submit:
            w.completed('health',dict(stale=True),None)
        self.assertEqual(submit.call_args.args[0],'health')


if __name__ == '__main__':
    unittest.main(verbosity=2)
