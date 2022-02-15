import subprocess
import os
import string
import random
from typing import Union

from utils import random_voice

from logging import getLogger, StreamHandler, Formatter, DEBUG, INFO


logger = getLogger(__name__)
logger.setLevel(DEBUG)
logger.propagate = False
hdlr = StreamHandler()
hdlr.setLevel(DEBUG)
fmt = Formatter(fmt='[{asctime}][{name}][{funcName}][{levelname}] {message}', datefmt='%Y-%m-%d %H:%M:%S' ,style='{')
hdlr.setFormatter(fmt)
logger.addHandler(hdlr)


def random_name(n:int) -> str:
        return ''.join(random.choices(string.ascii_letters + string.digits, k=n))


class TTS:
    def __init__(self, openjtalk_dir:str='./openjtalk', outdir:str='./wav/tmp') -> None:
        self.openjtalk = f'{openjtalk_dir}/open_jtalk'
        self.dic = f'{openjtalk_dir}/dic'
        self.htsvoice = f'{openjtalk_dir}/htsvoice'
        self.outdir = outdir
        os.makedirs(self.outdir, exist_ok=True)


    def synthesize(self, text:str, speaker:str='mei', emotion:str='normal', effect:str='none', tone:str='0', speed:str='0') -> Union[str, None]:
        wavpath = f'{self.outdir}/{random_name(8)}.wav'
        tone = str(1.5 * int(tone))
        #感情がsadなら基準のspeedを少し速くする
        if emotion == 'sad':
            speed = str(1.2 * (2**(0.2))**int(speed))
        else:
            speed = str(1.1 * (2**(0.2))**int(speed))

        open_jtalk = [self.openjtalk]
        dic = ['-x', self.dic]
        htsvoice = ['-m', f'{self.htsvoice}/{speaker}/{emotion}.htsvoice']
        outwav = ['-ow', wavpath]
        _tone = ['-fm', tone]
        _speed = ['-r', speed]
        volume = ['-g', '10']
        cmd = open_jtalk + dic + htsvoice + outwav + _tone + _speed + volume
        if effect == 'robot':
            cmd.extend(['-a', '0.4'])
        elif effect == 'whisper':
            cmd.extend(['-u', '1.0'])
        
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        proc.stdin.write(text.encode())
        proc.stdin.close()
        proc.wait()
        if proc.returncode != 0:
            #読み上げられる文字がない以外のエラーならログ表示
            if 'No phenome.' not in (err_lines := proc.stderr.read().decode().strip()):
                for line in err_lines.split('\n'):
                    level, message = tuple(line.split(': ', maxsplit=1))
                    if level == 'Warning':
                        logger.warning(message)
                    elif level == 'Error':
                        logger.error(message)
            #ファイルが作成されていれば削除したうえでNoneを返す
            if os.path.exists(wavpath):
                os.remove(wavpath)
            wavpath = None

        return wavpath


if __name__ == '__main__':
    TTS().synthesize('お疲れさまでした．では，また．')
