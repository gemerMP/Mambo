"""Standalone terminal workflow; imports no GUI, web server, art or audio."""
import getpass
import os
import select
import signal
import sys
import time
from .core import Engine, MamboError, fetch_subscription, probe


def add_connection(store):
    print('Вставь vless://, trojan://, wg:// или HTTPS-подписку (файл .conf: mambo-lite import FILE) и нажми Enter.')
    value=getpass.getpass('Ссылка (ввод скрыт, в историю команд не попадёт): ').strip()
    if not value:return
    if value.lower().startswith('https://'):
        result=store.import_subscription(fetch_subscription(value))
        print('Добавлено:',result['count'])
        for item in result['skipped']:print('Пропущена строка',item['index'],':',item['reason'])
    else:print('Добавлено:',store.import_text(value))


def measure_ping(store, selection=None, settings=None):
    profiles=store.list()
    if not profiles:
        print('Сначала добавь ключ или подписку через A.');return
    if selection is None:
        for i,p in enumerate(profiles,1):print(f"  {i}. {p['name']}")
        selection=input('Номер сервера (Enter — все): ').strip()
    if selection in ('','all'):
        chosen=profiles
    elif selection.isdecimal() and 1<=int(selection)<=len(profiles):
        chosen=[profiles[int(selection)-1]]
    else:
        chosen=[p for p in profiles if p['id']==selection]
        if not chosen:raise MamboError('Такого сервера нет.')
    from .probes import measure,Cancel
    settings=settings or {'ping_type':'GET','ping_mode':'Default','timeout':8,'test_url':'https://www.gstatic.com/generate_204'}
    engine=Engine(store);cancel=Cancel()
    for p in chosen:
        try:print(p['name']+': '+measure(store.get(p['id']),engine,settings,cancel),flush=True)
        except MamboError as e:print(p['name']+': '+str(e),flush=True)
        except KeyboardInterrupt:cancel.stop();raise
        except Exception as e:print(p['name']+': проверка не выполнена ('+type(e).__name__+')',flush=True)


def choose_server(store, executable=None, port=10808):
    while True:
        profiles=store.public()
        print('\nMambo Lite — серверы')
        for index,p in enumerate(profiles,1):
            print(f"  {index}. {p['name']} [{p['protocol'].upper()} / {p['transport']}]")
        if not profiles:print('  Пока пусто. Нажми A и вставь ключ или подписку.')
        print('  A — добавить ключ/подписку | P — задержка | I — установить Xray | Q — выход')
        choice=input('Номер сервера или действие: ').strip().lower()
        try:
            if choice=='q':return None
            if choice=='a':add_connection(store);continue
            if choice=='p':measure_ping(store);continue
            if choice=='i':
                print('Скачать официальное ядро Xray с GitHub? Оно нужно для XHTTP и SOCKS5.')
                if input('Установить? [y/N]: ').strip().lower() in ('y','yes','д','да'):
                    from .installer import install_xray
                    print('Установлено:',install_xray(store)['version'])
                continue
            if choice.isdecimal() and 1<=int(choice)<=len(profiles):return profiles[int(choice)-1]['id']
            print('Введи номер из списка, A, P, I или Q.')
        except (MamboError,OSError,ValueError) as exc:
            print('Ошибка:',exc)


def run_connection(engine, ident, mode):
    def interrupted(*_):raise KeyboardInterrupt
    previous={sig:signal.getsignal(sig) for sig in (signal.SIGINT,signal.SIGTERM)}
    for sig in previous:signal.signal(sig,interrupted)
    try:
        try:
            print('Подключение…',flush=True)
            engine.start(ident,mode)
            print('VPN запущен.' if mode=='tun' else f'SOCKS5: 127.0.0.1:{engine.port}',flush=True)
            print('Ctrl+C или Enter — отключить и выйти.',flush=True)
            while engine.status()['running']:
                if os.name=='posix' and sys.stdin.isatty():
                    ready,_,_=select.select([sys.stdin],[],[],.3)
                    if ready:
                        text=sys.stdin.readline()
                        if not text or text.strip().lower() in ('','q','quit'):break
                elif os.name=='nt' and sys.stdin.isatty():
                    import msvcrt
                    if msvcrt.kbhit() and msvcrt.getwch() in ('\r','\n','q','Q'):break
                    time.sleep(.1)
                else:time.sleep(.3)
            else:raise MamboError('Ядро остановилось.')
        except KeyboardInterrupt:
            pass
        finally:
            # Do not let a second Ctrl+C interrupt route/DNS restoration.
            for sig in previous:signal.signal(sig,signal.SIG_IGN)
            print('Отключение…',flush=True)
            engine.stop()
        print('Отключено. Mambo Lite завершён.',flush=True)
        return 0
    finally:
        for sig,handler in previous.items():signal.signal(sig,handler)
