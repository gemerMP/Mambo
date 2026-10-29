"""Native Qt Widgets client. Connection work runs outside the UI thread."""
import json,os,random,re,socket,ssl,sys,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import Qt,QTimer,Signal,QObject,QSize,QPropertyAnimation
from PySide6.QtGui import QPixmap,QIcon
from PySide6.QtWidgets import QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QListWidget,QListWidgetItem,QStackedWidget,QScrollArea,QFrame,QLineEdit,QPlainTextEdit,QComboBox,QCheckBox,QSpinBox,QSlider,QFileDialog,QMessageBox,QDialog,QDialogButtonBox
from .core import Store,Engine,MamboError,fetch_subscription
from .routing import DEFAULT
from .probes import Cancel,measure
from .audio import Player
from .ui import Interface, QUOTES, setup_fonts
from .connectivity import health_summary
VERSION='0.9.3';ASSETS=Path(__file__).parent/'web/assets'

def error_text(e):
 if isinstance(e,MamboError):return str(e)
 if isinstance(e,ssl.SSLError):return 'Не удалось проверить TLS-сертификат.'
 if isinstance(e,(TimeoutError,socket.timeout)):return 'Истекло время ожидания.'
 if isinstance(e,socket.gaierror):return 'Не удалось определить адрес сервера.'
 return 'Операция не выполнена ('+type(e).__name__+'). Проверь сеть и настройки.'
class Events(QObject):done=Signal(str,object,object)
class Window(Interface,QMainWindow):
 def __init__(self,store=None):
  super().__init__();self.store=store or Store();self.engine=Engine(self.store);self.pool=ThreadPoolExecutor(max_workers=3);self.events=Events();self.events.done.connect(self.completed);self.jobs={};self.closing=False;self.cancel=None;self.state={};self.pose=0;self.audio=Player(ASSETS);self.prefs={};self.pixmaps={};self.last_error=''
  with self.store.connect() as db:row=db.execute("SELECT value FROM settings WHERE key='desktop'").fetchone()
  if row:
   try:self.prefs=json.loads(row[0])
   except ValueError:pass
  self.pings={};self.return_home=False;self.last_traffic=0;self.log_mtime=None
  self.version=VERSION;self.build_ui();self.theme();self.reload();self.update_connection(self.engine.status());self.log('Приложение открыто');self.timer=QTimer(self);self.timer.timeout.connect(self.poll);self.timer.start(500)
 def pref(self,k,v):
  self.prefs[k]=v
  with self.store.connect() as db:db.execute("INSERT OR REPLACE INTO settings VALUES ('desktop',?)",(json.dumps(self.prefs),))
 def selected(self):return self.store.get(self.prefs['selected']) if self.prefs.get('selected') else None
 def reload(self,*args):
  profiles=self.store.public();chosen=self.prefs.get('selected')
  if chosen not in [p['id'] for p in profiles]:chosen=profiles[0]['id'] if profiles else None;self.pref('selected',chosen)
  self.list.blockSignals(True);self.list.clear();query=self.search.text().casefold()
  for p in profiles:
   if query not in (p['name']+' '+p['host']+' '+p['protocol']).casefold():continue
   item=QListWidgetItem(('★ ' if p['favorite'] else '')+p['name']+'\n'+p['protocol'].upper()+' · '+p['host']+':'+str(p['port'])+(' · '+self.pings[p['id']] if p['id'] in self.pings else ''));item.setData(Qt.UserRole,p['id']);self.list.addItem(item)
   if p['id']==chosen:self.list.setCurrentItem(item)
  self.list.blockSignals(False)
  try:
   p=self.selected();self.selected_label.setText(p['name'] if p else 'Выбрать сервер');self.profile_meta.setText(p['protocol'].upper()+' · '+p['host'] if p else 'Добавь ключ или подписку')
  except MamboError:self.selected_label.setText('Профиль нужно исправить или импортировать заново.')
 def select(self):
  item=self.list.currentItem()
  if item:
   self.pref('selected',item.data(Qt.UserRole));p=self.selected();self.selected_label.setText(p['name']);self.profile_meta.setText(p['protocol'].upper()+' · '+p['host'])
 def open_servers(self):
  self.return_home=True;self.nav.setCurrentRow(1)
 def page_changed(self,row):
  if row!=1:self.return_home=False
 def choose_server(self,item=None):
  self.select();self.log('Выбран сервер для следующего подключения')
  if self.return_home:self.return_home=False;self.nav.setCurrentRow(0)
 def import_dialog(self):
  d=QDialog(self);d.setWindowTitle('Добавить профиль');d.resize(600,380);box=QVBoxLayout(d);box.addWidget(QLabel('Вставь ключ, HTTPS-подписку или WireGuard .conf'));text=QPlainTextEdit();box.addWidget(text);buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(d.accept);buttons.rejected.connect(d.reject);box.addWidget(buttons)
  if d.exec()==QDialog.Accepted:self.import_text(text.toPlainText())
 def import_file(self):
  p,_=QFileDialog.getOpenFileName(self,'Импорт','','Профили (*.conf *.txt);;Все файлы (*)')
  if p:
   try:
    if Path(p).stat().st_size>1048576:raise MamboError('Файл больше 1 МБ.')
    self.import_text(Path(p).read_text(encoding='utf-8-sig'))
   except Exception as e:self.error(e)
 def import_text(self,text):
  if text.strip():self.submit('import',lambda:self.store.import_subscription(fetch_subscription(text.strip()) if text.strip().startswith('https://') else text))
 def favorite(self):
  try:
   p=self.selected()
   if p:self.store.favorite(p['id'],not p['favorite']);self.reload()
  except Exception as e:self.error(e)
 def delete(self):
  try:
   p=self.selected()
   if not p:return
   if self.state.get('active')==p['id']:raise MamboError('Сначала отключи этот сервер.')
   if QMessageBox.question(self,'Удалить профиль?','Удалить выбранный профиль с устройства?')==QMessageBox.Yes:self.store.delete(p['id']);self.reload()
  except Exception as e:self.error(e)
 def save_routes(self):
  try:
   r={k:re.split(r'[,\s]+',w.toPlainText().strip()) if w.toPlainText().strip() else [] for k,w in self.rule_fields.items()};r.update(fallback='direct' if self.fallback.currentIndex() else 'proxy',dns=self.dns.text().strip(),lan=self.lan.isChecked(),ipv6=self.ipv6.isChecked(),mtu=self.mtu.value());self.store.save_rules(r);self.log('Маршруты сохранены');QMessageBox.information(self,'Сохранено','Настройки применятся при следующем подключении.')
  except Exception as e:self.error(e)
 def connect_toggle(self):
  if 'connection' in self.jobs:return
  if any(k in self.jobs for k in ('ping','diagnostic')):self.cancel_probe();self.status.setText('Дождись отмены проверки');return
  try:
   if self.engine.status()['running'] or self.engine.tun is not None or self.engine.process is not None:self.submit('connection',self.engine.stop)
   else:
    p=self.selected()
    if not p:raise MamboError('Добавь и выбери сервер.')
    self.submit('connection',lambda:self.engine.start(p['id'],'tun' if not self.scope.currentIndex() else 'socks'))
   self.power.setEnabled(False);self.status.setText('Отключаем…' if self.state.get('running') else 'Подключаем…');self.connect_caption.setText('Подожди, настраиваем соединение')
  except Exception as e:self.error(e)
 def probe(self,all_servers,server_view=False):
  if any(k in self.jobs for k in ('connection','ping','diagnostic')):return
  try:
   profiles=[self.store.get(p['id']) for p in self.store.public()] if all_servers else [self.selected()]
   if not profiles or not profiles[0]:raise MamboError('Добавь и выбери сервер.')
   values=dict(ping_type='GET' if server_view else ['GET','HEAD','TCP','ICMP'][self.pt.currentIndex()],ping_mode='Default' if server_view else self.pm.currentText(),timeout=self.timeout.value(),test_url=self.url.text().strip())
   if not server_view:
    for k,v in values.items():self.pref(k,v)
   self.cancel=Cancel();cancel=self.cancel;self.ping_location='servers' if server_view else 'ping';(self.server_ping_result if server_view else self.ping_result).setText('Проверяю…')
   def work():
    out=[];cache={}
    for i,p in enumerate(profiles,1):
     cancel.check()
     try:answer=measure(p,self.engine,values,cancel)
     except Exception as e:answer=error_text(e)
     cache[p['id']]=answer
     out.append(str(i)+'. '+p['name']+' — '+answer)
    return {'text':'\n'.join(out),'cache':cache}
   self.submit('ping',work)
  except Exception as e:self.error(e)
 def diagnose(self):
  if any(k in self.jobs for k in ('connection','ping','diagnostic')):return
  try:
   p=self.selected()
   if not p:raise MamboError('Добавь и выбери сервер.')
   from .network_checks import run
   settings=dict(timeout=self.timeout.value(),test_url=self.url.text().strip());mode=self.diagnostic_mode.currentIndex()
   self.cancel=Cancel();cancel=self.cancel;self.diagnostic_result.setText('Проверяю…');self.log('Запущена диагностика · '+self.diagnostic_mode.currentText())
   self.submit('diagnostic',lambda:run(p,self.engine,settings,mode,cancel))
  except Exception as e:self.error(e)
 def cancel_probe(self):
  if self.cancel:self.cancel.stop()
 def health(self):
  if 'connection' not in self.jobs:self.submit('health',self.engine.check_internet)
 def submit(self,key,fn):
  if key in self.jobs:return
  def run():
   try:result=fn();error=None
   except Exception as e:result=None;error=e
   self.events.done.emit(key,result,error)
  self.jobs[key]=self.pool.submit(run)
 def completed(self,key,result,error):
  self.jobs.pop(key,None)
  if key=='traffic':
   if self.closing and not self.jobs:self.close()
   return
  if key=='ping':
   text=error_text(error) if error else result['text'];(self.server_ping_result if self.ping_location=='servers' else self.ping_result).setText(text);self.cancel=None
   if not error:self.pings.update(result['cache']);self.reload();self.log(text)
  if key=='diagnostic':
   text=error_text(error) if error else result;self.diagnostic_result.setText(text);self.cancel=None;self.log(text)
  if key=='connection':
   self.power.setEnabled(True);self.poll()
   if not error and self.state.get('running') and not self.closing:
    self.health_result.setText('Проверяем доступ через VPN и системный маршрут…');self.health()
   elif not self.state.get('running'):self.health_result.setText('Доступ в интернет можно проверить после подключения.')
  if key=='import' and not error:self.import_result.setText('Добавлено: '+str(result['count'])+' · пропущено: '+str(len(result['skipped'])));self.reload()
  if key=='health':
   if not error and not result.get('stale'):
    self.health_result.setText(health_summary(result));self.log(health_summary(result));self.poll()
   elif not error and result.get('stale') and self.state.get('running') and not self.closing:self.health()
   elif error and self.state.get('running'):self.health_result.setText(error_text(error))
  if error:
   self.log(error_text(error))
   if key not in ('ping','health') and not self.closing:QMessageBox.warning(self,'Mambo',error_text(error))
  else:self.log({'connection':'Состояние VPN изменено','ping':'Проверка пинга завершена','diagnostic':'Диагностика завершена','import':'Импорт выполнен','health':'Проверка доступа завершена'}.get(key,'Готово'))
  if self.closing and not self.jobs:self.close()
 def poll(self):
  if 'connection' not in self.jobs and self.engine.lock.acquire(False):
   try:
    self.state=self.engine.status();self.update_connection(self.state)
    if self.state.get('error') and self.state['error']!=self.last_error:self.last_error=self.state['error'];self.log(self.last_error)
   finally:self.engine.lock.release()
  if self.audio.error:self.log(self.audio.error);self.health_result.setText(self.audio.error);self.audio.error=None
  if not self.closing and self.state.get('running') and time.monotonic()-self.last_traffic>2:
   self.last_traffic=time.monotonic();self.submit('traffic',self.engine.refresh_traffic)
  self.refresh_log()
 def log(self,event):
  from .journal import append
  append(self.store.home,event);self.refresh_log()
 def refresh_log(self):
  p=self.store.home/'events.log'
  try:
   stamp=p.stat().st_mtime_ns
   if stamp==self.log_mtime:return
   self.log_mtime=stamp;scroll=self.log_text.verticalScrollBar();pos=scroll.value();bottom=pos>=scroll.maximum()-5
   self.log_text.setPlainText('Mambo '+VERSION+' · '+sys.platform+'\n'+p.read_text(encoding='utf-8'));scroll.setValue(scroll.maximum() if bottom else pos)
  except OSError:pass
 def error(self,e):self.log(error_text(e));QMessageBox.warning(self,'Mambo',error_text(e))
 def clear_log(self):(self.store.home/'events.log').write_text('');self.log_text.clear()
 def export_log(self):
  p,_=QFileDialog.getSaveFileName(self,'Сохранить журнал','mambo-log.txt','Text (*.txt)')
  if p:
   try:Path(p).write_text(self.log_text.toPlainText(),encoding='utf-8')
   except OSError as e:self.error(e)
 def play_sound(self):self.audio.play(self.prefs.get('sound','meow'),self.prefs.get('sample',0),self.prefs.get('volume',75))
 def mascot(self):
  self.pose+=1;self.show_art();self.play_sound();self.quote.setText(random.choice(QUOTES))
  if self.prefs.get('animations',True):self.animation=QPropertyAnimation(self.art,b'iconSize');self.animation.setDuration(200);self.animation.setStartValue(QSize(280,215));self.animation.setKeyValueAt(.5,QSize(292,224));self.animation.setEndValue(QSize(280,215));self.animation.start()
 def closeEvent(self,event):
  self.closing=True;self.cancel_probe()
  if self.jobs:event.ignore();self.status.setText('Завершаю операции…');return
  if self.engine.process or self.engine.tun:event.ignore();self.submit('connection',self.engine.stop);return
  self.timer.stop();self.audio.close();self.pool.shutdown(wait=False,cancel_futures=True);event.accept()
def main():
 app=QApplication(sys.argv);app.setApplicationName('Mambo');app.setStyle('Fusion');setup_fonts();w=Window();w.show();return app.exec()
if __name__=='__main__':sys.exit(main())
