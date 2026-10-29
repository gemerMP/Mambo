"""Bounded, unprivileged sound playback outside WebKit/GStreamer."""
import math
from pathlib import Path
import subprocess
import threading
import time
from .core import MamboError

class SoundPlayer:
    def __init__(self, assets):
        self.assets=Path(assets);self.process=None;self.lock=threading.Lock();self.last=0;self.closed=False
    def play(self,index,volume):
        if type(index) is not int or not 0<=index<5 or type(volume) not in (int,float) or not math.isfinite(volume) or not 0<=volume<=1:
            raise MamboError('Некорректные параметры звука.')
        with self.lock:
            if self.closed or time.monotonic()-self.last<.3:return {'played':False}
            self._stop()
            if volume==0:return {'played':False}
            binary=Path('/usr/bin/pw-play')
            if not binary.is_file():raise MamboError('Для звуков нужен пакет pipewire-audio. Остальные функции доступны.')
            self.process=subprocess.Popen([str(binary),'--volume',str(volume),str(self.assets/f'meow-{index}.wav')],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            self.last=time.monotonic();p=self.process
            threading.Thread(target=self._watch,args=(p,),daemon=True).start()
            return {'played':True}
    def _watch(self,p):
        try:p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            p.kill();p.wait()
    def _stop(self):
        if self.process:
            if self.process.poll() is None:self.process.kill()
            self.process=None
    def stop(self):
        with self.lock:self._stop()
    def close(self):
        with self.lock:self.closed=True;self._stop()
