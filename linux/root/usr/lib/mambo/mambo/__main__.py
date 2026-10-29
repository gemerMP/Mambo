import argparse
import getpass
import json
import signal
import sys
import time
from pathlib import Path
from .core import Engine, MamboError, Store, fetch_subscription, probe


def main():
    ap = argparse.ArgumentParser(prog='mambo-lite', description='Mambo Lite · локальный клиент Xray')
    ap.add_argument('--home', type=Path, help='Каталог профилей')
    ap.add_argument('--xray', help='Путь к исполняемому Xray')
    ap.add_argument('--socks-port', type=int, default=10808)
    sub = ap.add_subparsers(dest='command', required=False)
    imp = sub.add_parser('import', help='Импорт ссылок или Base64 из файла / stdin')
    imp.add_argument('file', nargs='?', default='-')
    ping_parser=sub.add_parser('ping',help='TCP-задержка: выбор по номеру или все серверы')
    ping_parser.add_argument('server',nargs='?')
    ping_parser.add_argument('--type',choices=['GET','HEAD','TCP','ICMP'],default='GET')
    ping_parser.add_argument('--mode',choices=['Default','Double','KeepAlive'],default='Default')
    ping_parser.add_argument('--url',default='https://www.gstatic.com/generate_204')
    ping_parser.add_argument('--timeout',type=int,default=8)
    sub.add_parser('add', help='Вставить ключ или подписку в консоли')
    sub.add_parser('subscribe', help='Импорт HTTPS-подписки; URL вводится скрыто')
    list_parser=sub.add_parser('list', help='ID и названия серверов')
    list_parser.add_argument('--json',action='store_true')
    for command in ('connect', 'check', 'remove'):
        command_parser = sub.add_parser(command)
        command_parser.add_argument('id', nargs='?' if command == 'connect' else None)
        if command == 'connect':
            command_parser.add_argument('--mode', choices=['socks', 'tun'], default='tun')
    fav = sub.add_parser('favorite')
    fav.add_argument('id')
    fav.add_argument('--off', action='store_true')
    ui = sub.add_parser('ui', help='Графический интерфейс на localhost')
    ui.add_argument('--port', type=int, default=0)
    ui.add_argument('--no-browser', action='store_true')
    sub.add_parser('doctor', help='Проверить наличие ядра и показать границы подключения')
    args = ap.parse_args()
    try:
        store = Store(args.home)
        if args.command in (None, 'add'):
            from .cli import add_connection, choose_server, run_connection
            if args.command == 'add':
                add_connection(store)
                return 0
            ident=choose_server(store)
            if ident is None:return 0
            return run_connection(Engine(store,args.xray,args.socks_port),ident,'tun')
        if args.command == 'ping':
            from .cli import measure_ping
            measure_ping(store,args.server,dict(ping_type=args.type,ping_mode=args.mode,test_url=args.url,timeout=args.timeout))
            return 0
        if args.command == 'import':
            text = sys.stdin.read(1024 * 1024 + 1) if args.file == '-' else Path(args.file).read_text(encoding='utf-8-sig')
            print(f'Импортировано: {store.import_text(text)}')
        elif args.command == 'subscribe':
            print(json.dumps(store.import_subscription(fetch_subscription(getpass.getpass('HTTPS URL: '))), ensure_ascii=False))
        elif args.command == 'list':
            if args.json:
                print(json.dumps(store.public(), ensure_ascii=False, indent=2))
            else:
                for p in store.public():
                    print(f"{p['id']}  {p['name']}  [{p['transport']}]")
                print('Подключение: mambo-lite connect ID --mode tun')
        elif args.command == 'remove':
            store.delete(args.id)
        elif args.command == 'favorite':
            store.favorite(args.id, not args.off)
        elif args.command == 'check':
            print(json.dumps(probe(store.get(args.id)), ensure_ascii=False))
            print('TCP-проверка не подтверждает авторизацию и работу туннеля.')
        elif args.command == 'ui':
            if not Path(__file__).with_name('server.py').exists():
                raise MamboError('В отдельном Lite-пакете нет интерфейса. Запусти mambo-lite без параметров.')
            from .server import serve
            serve(store, args.xray, args.socks_port, args.port, not args.no_browser)
        else:
            engine = Engine(store, args.xray, args.socks_port)
            if args.command == 'doctor':
                print('Xray:', engine.binary() or 'не найден')
                print('TUN:', 'готов' if engine.status()['tun_available'] else 'не найдено ядро / системный компонент Mambo')
            else:
                from .cli import choose_server, run_connection
                ident=args.id or choose_server(store)
                if ident is None:return 0
                return run_connection(engine,ident,args.mode)
    except (KeyboardInterrupt, EOFError):
        return 0
    except (MamboError, OSError, ValueError) as exc:
        print(f'Ошибка: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
