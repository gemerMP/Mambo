"""Nonblocking Windows WAV playback with per-click gain; no browser audio."""
import array
import math
from pathlib import Path
import tempfile
import threading
import time
import wave
from .core import MamboError

class SoundPlayer:
    def __init__(self, assets):
        self.assets = Path(assets)
        self.lock = threading.Lock()
        self.runtime = tempfile.TemporaryDirectory(prefix='mambo-audio-')
        self.last = 0
        self.closed = False

    def play(self, index, volume):
        import winsound
        if type(index) is not int or not 0 <= index < 5 or type(volume) not in (int,float) or not math.isfinite(volume) or not 0 <= volume <= 1:
            raise MamboError('Некорректные параметры звука.')
        with self.lock:
            if self.closed or time.monotonic() - self.last < .3:
                return {'played': False}
            winsound.PlaySound(None, 0)
            if not volume:
                return {'played': False}
            with wave.open(str(self.assets / f'meow-{index}.wav'), 'rb') as source:
                params = source.getparams()
                if params.sampwidth != 2:
                    raise MamboError('Звук должен быть PCM WAV 16 bit.')
                samples = array.array('h', source.readframes(source.getnframes()))
            samples = array.array('h', (int(sample * volume) for sample in samples))
            target = Path(self.runtime.name) / 'click.wav'
            with wave.open(str(target), 'wb') as output:
                output.setparams(params)
                output.writeframes(samples.tobytes())
            winsound.PlaySound(str(target), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            self.last = time.monotonic()
            return {'played': True}

    def stop(self):
        import winsound
        with self.lock:
            winsound.PlaySound(None, 0)

    def close(self):
        import winsound
        with self.lock:
            self.closed = True
            winsound.PlaySound(None, 0)
            self.runtime.cleanup()
