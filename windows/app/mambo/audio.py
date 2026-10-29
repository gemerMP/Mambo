import array,os,random,shutil,subprocess,tempfile,threading,wave
from pathlib import Path
class Player:
 def __init__(self,assets):self.assets=Path(assets);self.lock=threading.Lock();self.process=None;self.closed=False;self.worker=None;self.temp=tempfile.TemporaryDirectory(prefix='mambo-audio-');self.error=None
 def play(self,bank='meow',sample=0,volume=75):
  if self.closed or bank=='mute' or volume<=0 or not self.lock.acquire(False):return
  def work():
   try:
    self.error=None;name=('meow-'+str((sample-1) if sample else random.randrange(5))) if bank=='meow' else bank;source=self.assets/(name+'.wav');target=Path(self.temp.name)/(name+'-'+str(volume)+'.wav')
    if not target.exists():
     with wave.open(str(source),'rb') as w:params=w.getparams();raw=w.readframes(w.getnframes())
     if params.sampwidth==2:raw=array.array('h',(int(x*volume/100) for x in array.array('h',raw))).tobytes()
     with wave.open(str(target),'wb') as w:w.setparams(params);w.writeframes(raw)
    if self.closed:return
    if os.name=='nt':
     import winsound
     winsound.PlaySound(str(target),winsound.SND_FILENAME|winsound.SND_ASYNC|winsound.SND_NODEFAULT)
    else:
     if self.process and self.process.poll() is None:self.process.terminate();self.process.wait(timeout=2)
     player=shutil.which('paplay') or shutil.which('aplay')
     if not player:raise OSError()
     self.process=subprocess.Popen([player,str(target)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   except Exception:self.error='Не удалось воспроизвести звук. Проверь аудиоустройство; Linux: нужен pulseaudio-utils или alsa-utils.'
   finally:self.lock.release()
  self.worker=threading.Thread(target=work,daemon=True);self.worker.start()
 def close(self):
  self.closed=True
  if self.worker:self.worker.join(timeout=3)
  if os.name=='nt':
   import winsound
   winsound.PlaySound(None,0)
  if self.process and self.process.poll() is None:self.process.terminate();self.process.wait(timeout=3)
  self.temp.cleanup()
