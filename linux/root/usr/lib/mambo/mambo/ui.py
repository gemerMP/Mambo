"""Native desktop presentation; network operations stay in qt_app/core."""
import math
import random
from pathlib import Path

from PySide6.QtCore import Qt, QSize, QRectF, QSignalBlocker
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QIcon, QPainter,
                          QPalette, QPen, QPixmap)
from PySide6.QtWidgets import (QApplication, QBoxLayout, QCheckBox, QComboBox,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSlider,
    QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from .routing import DEFAULT
from .connectivity import access_ok
from .traffic import format_bytes

ASSETS = Path(__file__).parent / 'web/assets'
QUOTES = [
    'Тебе не нужно успевать всё. Один маленький шаг — уже движение.',
    'Пусть сегодня найдётся место чему-то хорошему.',
    'Ты справляешься. И отдыхать тебе тоже можно.',
    'Вдохни. Выдохни. Мамбо рядом.',
]

# Keep the old palettes, with a genuinely neutral seventh theme.
THEMES = {
    'pink-dark': dict(name='Розовая · тёмная', short='Розовая ночь', color='pink', light=False,
        bg='#151318', side='#18161c', panel='#201c24', alt='#2a242e',
        ink='#f4edf2', muted='#a99da9', accent='#eda5ca', on='#321d2b', soft='#362733'),
    'green-dark': dict(name='Зелёная · тёмная', short='Тихий лес', color='green', light=False,
        bg='#121815', side='#161d19', panel='#1b241f', alt='#26312a',
        ink='#edf4ef', muted='#9cad9f', accent='#a5cab0', on='#1b2b20', soft='#29392e'),
    'red-dark': dict(name='Красная · тёмная', short='Тёплый вечер', color='red', light=False,
        bg='#191416', side='#1e171a', panel='#271e22', alt='#33262b',
        ink='#f6edef', muted='#b09ba2', accent='#ed929a', on='#351c23', soft='#3e2931'),
    'pink-light': dict(name='Розовая · светлая', short='Розовый рассвет', color='pink', light=True,
        bg='#faf6f8', side='#f5eef2', panel='#fffdfd', alt='#f1e9ee',
        ink='#322730', muted='#7e6b78', accent='#a9497e', on='#fff7fb', soft='#f1dde9'),
    'green-light': dict(name='Зелёная · светлая', short='Светлый сад', color='green', light=True,
        bg='#f5f8f3', side='#eef3eb', panel='#fdfffb', alt='#e8efe4',
        ink='#29372c', muted='#6e816f', accent='#4c7858', on='#ffffff', soft='#deebdf'),
    'red-light': dict(name='Красная · светлая', short='Светлый коралл', color='red', light=True,
        bg='#fbf6f3', side='#f5eeea', panel='#fffdfb', alt='#f3e9e4',
        ink='#402c30', muted='#8d747b', accent='#ae4a5d', on='#ffffff', soft='#f4dfe4'),
    'minimal-dark': dict(name='Минимализм · тёмная', short='Минимализм', color='pink', light=False,
        bg='#111315', side='#141618', panel='#1a1d20', alt='#24282d',
        ink='#edf0f2', muted='#9ba2aa', accent='#d8dfe6', on='#171b20', soft='#2c3239'),
}

ICONS = {
    'home': '<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/>',
    'servers': '<rect x="4" y="3" width="16" height="7" rx="2"/><rect x="4" y="14" width="16" height="7" rx="2"/><path d="M8 6.5h.01M8 17.5h.01M12 6.5h5M12 17.5h5"/>',
    'ping': '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    'routes': '<circle cx="6" cy="5" r="2"/><circle cx="18" cy="5" r="2"/><circle cx="18" cy="19" r="2"/><path d="M6 7v5a7 7 0 0 0 7 7h3M18 7v10"/>',
    'appearance': '<path d="m12 3 3 6 6 3-6 3-3 6-3-6-6-3 6-3z"/>',
    'logs': '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 7h6M9 12h6M9 17h4"/>',
    'arrow': '<path d="m9 5 7 7-7 7"/>',
    'plus': '<path d="M12 5v14M5 12h14"/>',
    'refresh': '<path d="M20 10a8 8 0 1 0-1 7M20 4v6h-6"/>',
    'shield': '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/><path d="m8 12 3 3 5-6"/>',
    'check': '<path d="m5 12 4 4L19 6"/>',
}


def icon(name, color):
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" '
           'viewBox="0 0 24 24" fill="none" stroke="' + color +
           '" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round">' +
           ICONS[name] + '</svg>')
    pix = QPixmap()
    pix.loadFromData(svg.encode(), 'SVG')
    return QIcon(pix)


def setup_fonts():
    """Use the same Cyrillic font on every distribution, without installation."""
    for path in (Path(__file__).parent / 'fonts').glob('*.ttf'):
        QFontDatabase.addApplicationFont(str(path))
    font = QFont('Noto Sans')
    font.setPixelSize(14)
    font.setHintingPreference(QFont.PreferNoHinting)
    QApplication.setFont(font)


def current_theme(prefs):
    key = prefs.get('theme')
    if key in THEMES:
        return key
    color = prefs.get('color', 'pink')
    if color not in ('pink', 'green', 'red'):
        color = 'pink'
    return color + ('-light' if prefs.get('light', False) else '-dark')


def format_duration(seconds):
    """Hours deliberately keep growing after a day; never wrap at 24 hours."""
    try:
        seconds = max(0, int(seconds)) if math.isfinite(float(seconds)) else 0
    except (ValueError, TypeError, OverflowError):
        seconds = 0
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}'


class Switch(QCheckBox):
    """A keyboard-accessible native checkbox with a quiet switch appearance."""
    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 58, 30)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        palette = self.palette()
        accent = palette.color(QPalette.Highlight)
        muted = palette.color(QPalette.Mid)
        if not self.isEnabled():
            painter.setOpacity(.45)
        y = (self.height() - 22) / 2
        painter.setPen(Qt.NoPen)
        painter.setBrush(accent if self.isChecked() else muted)
        painter.drawRoundedRect(QRectF(0, y, 38, 22), 11, 11)
        painter.setBrush(palette.color(QPalette.HighlightedText) if self.isChecked()
                         else palette.color(QPalette.Window))
        painter.drawEllipse(QRectF(20 if self.isChecked() else 4, y + 4, 14, 14))
        painter.setPen(palette.color(QPalette.WindowText))
        painter.drawText(self.rect().adjusted(50, 0, 0, 0), Qt.AlignVCenter, self.text())
        if self.hasFocus():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(accent, 1, Qt.DotLine))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 5, 5)


class PowerButton(QPushButton):
    def __init__(self, callback):
        super().__init__('Подключить')
        self.setObjectName('power')
        self.setFixedSize(108, 108)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName('Подключить VPN')
        self.clicked.connect(callback)
        self.running = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.scale(self.width()/120, self.height()/120)
        palette = self.palette()
        accent = palette.color(QPalette.Highlight)
        if not self.isEnabled():
            painter.setOpacity(.45)
        halo = QColor(accent)
        halo.setAlpha(18 if not self.underMouse() else 28)
        painter.setPen(Qt.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(QRectF(0, 0, 120, 120))
        painter.setBrush(accent if self.running else palette.color(QPalette.AlternateBase))
        painter.drawEllipse(QRectF(12, 12, 96, 96))
        stroke = palette.color(QPalette.HighlightedText) if self.running else accent
        painter.setPen(QPen(stroke, 2.6, Qt.SolidLine, Qt.RoundCap))
        painter.setBrush(Qt.NoBrush)
        painter.drawArc(QRectF(43, 43, 34, 34), 48 * 16, -276 * 16)
        painter.drawLine(60, 37, 60, 57)
        if self.hasFocus():
            painter.setPen(QPen(accent, 1, Qt.DotLine))
            painter.drawEllipse(QRectF(5, 5, 110, 110))


class ThemeTile(QPushButton):
    def __init__(self, key, callback, wide=False):
        super().__init__()
        self.key, self.wide = key, wide
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(148)
        self.setFixedHeight(100 if wide else 145)
        self.setAccessibleName(THEMES[key]['name'])
        self.setToolTip(THEMES[key]['name'])
        self.clicked.connect(lambda: callback(key))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = THEMES[self.key]
        p.setPen(Qt.NoPen)
        p.setBrush(self.palette().color(QPalette.AlternateBase))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 12, 12)
        preview = QRectF(12, 12, 116 if self.wide else self.width()-24, 72)
        p.setBrush(QColor(t['bg']))
        p.drawRoundedRect(preview, 7, 7)
        p.setBrush(QColor(t['panel']))
        p.drawRoundedRect(preview.adjusted(7, 7, -preview.width()+30, -7), 3, 3)
        p.drawRoundedRect(preview.adjusted(38, 22, -8, -8), 4, 4)
        p.setBrush(QColor(t['accent']))
        p.drawRoundedRect(QRectF(preview.left()+40, preview.top()+11, 40, 3), 1.5, 1.5)
        p.drawRoundedRect(QRectF(preview.left()+12, preview.top()+18, 11, 3), 1.5, 1.5)
        p.setBrush(QColor(t['soft']))
        p.drawEllipse(QRectF(preview.center().x()+3, preview.top()+32, 24, 24))
        p.setPen(QPen(QColor(t['accent']), 1.5, Qt.SolidLine, Qt.RoundCap))
        x, y = preview.center().x()+15, preview.top()+44
        p.drawArc(QRectF(x-5, y-5, 10, 10), 45*16, -270*16)
        p.drawLine(int(x), int(y-7), int(x), int(y-1))
        font = self.font()
        font.setPixelSize(13)
        font.setWeight(QFont.DemiBold)
        p.setFont(font)
        p.setPen(self.palette().color(QPalette.WindowText))
        text_x, text_y = (146, 39) if self.wide else (13, 107)
        p.drawText(text_x, text_y, t['short'])
        font.setPixelSize(11)
        font.setWeight(QFont.Normal)
        p.setFont(font)
        p.setPen(self.palette().color(QPalette.PlaceholderText))
        p.drawText(text_x, text_y+19, 'Без персонажа и цитат' if self.wide else
                   ('Светлая тема' if t['light'] else 'Тёмная тема'))
        if self.isChecked() or self.hasFocus():
            p.setPen(QPen(self.palette().color(QPalette.Highlight), 1.4))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 12, 12)
        if self.isChecked():
            x = self.width()-24
            p.setPen(QPen(self.palette().color(QPalette.Highlight), 1.7,
                          Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawLine(x-5, text_y-5, x-2, text_y-2)
            p.drawLine(x-2, text_y-2, x+4, text_y-8)


class Interface:
    def label(self, text, role='', wrap=False):
        w = QLabel(text)
        if role:
            w.setObjectName(role)
        w.setWordWrap(wrap)
        if wrap:
            w.setMinimumWidth(0)
            w.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        return w

    def build_ui(self):
        self.setWindowTitle('Mambo · ' + self.version)
        self.resize(1180, 820)
        self.setMinimumSize(900, 680)
        shell = QWidget()
        shell.setObjectName('shell')
        layout = QHBoxLayout(shell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(shell)
        sidebar = QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(210)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(22, 32, 18, 24)
        side.setSpacing(8)
        brand = QHBoxLayout()
        self.brand_mark = self.label('m', 'brandMark')
        self.brand_mark.setFixedSize(36, 36)
        self.brand_mark.setAlignment(Qt.AlignCenter)
        self.brand = self.label('mambo', 'logo')
        brand.addWidget(self.brand_mark)
        brand.addWidget(self.brand, 1)
        side.addLayout(brand)
        self.brand_caption = self.label('Твой спокойный уголок', 'muted')
        side.addWidget(self.brand_caption)
        side.addSpacing(36)
        side.addWidget(self.label('ПРОСТРАНСТВО', 'eyebrow'))
        side.addSpacing(8)
        self.nav = QListWidget()
        self.nav.setObjectName('navigation')
        self.nav.setIconSize(QSize(19, 19))
        self.nav.addItems(['Главная', 'Серверы', 'Пинг', 'Маршрутизация', 'Вид и звук', 'Журнал'])
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        side.addWidget(self.nav, 1)
        self.side_note = self.label('Немного тишины.\nИ стабильная связь.', 'sideNote')
        side.addWidget(self.side_note)
        side.addSpacing(16)
        side.addWidget(self.label('Mambo ' + self.version, 'version'))
        side.addWidget(self.label('VLESS · Trojan · WireGuard', 'version'))
        layout.addWidget(sidebar)
        main = QWidget()
        main.setObjectName('main')
        main_box = QVBoxLayout(main)
        main_box.setContentsMargins(32, 22, 32, 22)
        main_box.setSpacing(18)
        top = QHBoxLayout()
        self.top_note = self.label('ЛИЧНОЕ СОЕДИНЕНИЕ', 'eyebrow')
        top.addWidget(self.top_note)
        top.addStretch()
        top.addWidget(self.label('Тема', 'muted'))
        self.theme_picker = QComboBox()
        self.theme_picker.setObjectName('themePicker')
        self.theme_picker.setMinimumWidth(218)
        for key, theme in THEMES.items():
            self.theme_picker.addItem(theme['name'], key)
        self.theme_picker.setCurrentIndex(list(THEMES).index(current_theme(self.prefs)))
        self.theme_picker.currentIndexChanged.connect(
            lambda i: self.apply_theme(self.theme_picker.itemData(i)))
        top.addWidget(self.theme_picker)
        main_box.addLayout(top)
        self.pages = QStackedWidget()
        main_box.addWidget(self.pages, 1)
        layout.addWidget(main, 1)
        self.home()
        self.servers()
        self.ping()
        self.routes()
        self.appearance()
        self.logs()
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.currentRowChanged.connect(self.refresh_nav)
        self.nav.currentRowChanged.connect(self.page_changed)
        self.nav.setCurrentRow(0)

    def page(self, title, sub):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(7)
        h = self.label(title, 'title')
        box.addWidget(h)
        box.addWidget(self.label(sub, 'muted', True))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        out = QVBoxLayout(inner)
        out.setContentsMargins(0, 17, 2, 0)
        out.setSpacing(16)
        scroll.setWidget(inner)
        box.addWidget(scroll, 1)
        self.pages.addWidget(page)
        return out

    def card(self, parent, title):
        frame = QFrame()
        frame.setObjectName('card')
        box = QVBoxLayout(frame)
        box.setContentsMargins(24, 22, 24, 22)
        box.setSpacing(12)
        if title:
            box.addWidget(self.label(title, 'heading'))
        parent.addWidget(frame)
        return box

    def button(self, label, fn, primary=False):
        b = QPushButton(label)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(fn)
        if primary:
            b.setObjectName('primary')
        return b

    def combo(self, box, label, values, index=0):
        box.addWidget(self.label(label, 'fieldLabel'))
        w = QComboBox()
        w.addItems(values)
        w.setCurrentIndex(index if 0 <= index < len(values) else 0)
        box.addWidget(w)
        return w

    def home(self):
        box = self.page('Главная', 'Подключение, сервер и трафик текущего сеанса.')
        self.home_title = self.pages.widget(0).findChild(QLabel, 'title')
        self.hero = QBoxLayout(QBoxLayout.LeftToRight)
        self.hero.setSpacing(16)
        box.addLayout(self.hero)
        self.connection_card = QFrame()
        self.connection_card.setObjectName('card')
        self.connection_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        c = QVBoxLayout(self.connection_card)
        c.setContentsMargins(24, 22, 24, 22)
        c.setSpacing(6)
        row = QHBoxLayout()
        row.addWidget(self.label('СОЕДИНЕНИЕ', 'eyebrow'))
        row.addStretch()
        self.status_badge = self.label('●  Не активно', 'statusBadge')
        row.addWidget(self.status_badge)
        c.addLayout(row)
        c.addSpacing(6)
        self.power = PowerButton(self.connect_toggle)
        c.addWidget(self.power, 0, Qt.AlignHCenter)
        c.addSpacing(0)
        self.status = self.label('Отключено', 'connectionTitle')
        self.status.setAlignment(Qt.AlignCenter)
        c.addWidget(self.status)
        self.connect_caption = self.label('Нажми на кнопку, чтобы подключиться', 'muted', True)
        self.connect_caption.setAlignment(Qt.AlignCenter)
        c.addWidget(self.connect_caption)
        c.addSpacing(4)
        self.elapsed = self.label('00:00:00', 'elapsed')
        self.elapsed.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.elapsed.setAlignment(Qt.AlignCenter)
        self.elapsed.setAccessibleName('Время подключения')
        c.addWidget(self.elapsed)
        cap = self.label('ВРЕМЯ ПОДКЛЮЧЕНИЯ', 'timerCaption')
        cap.setAlignment(Qt.AlignCenter)
        c.addWidget(cap)
        c.addSpacing(6)
        self.server_picker = self.button('', self.open_servers)
        self.server_picker.setObjectName('serverPicker')
        self.server_picker.setMinimumHeight(70)
        self.server_picker.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.server_picker.setAccessibleName('Выбрать сервер')
        server_row = QHBoxLayout(self.server_picker)
        server_row.setContentsMargins(13, 12, 13, 12)
        self.server_icon = QLabel()
        self.server_icon.setFixedSize(27, 27)
        server_row.addWidget(self.server_icon)
        details = QVBoxLayout()
        details.setSpacing(3)
        self.selected_label = self.label('Выбрать сервер', 'serverName', True)
        self.profile_meta = self.label('Добавь ключ или подписку', 'smallMuted', True)
        details.addWidget(self.selected_label)
        details.addWidget(self.profile_meta)
        server_row.addLayout(details, 1)
        self.server_arrow = QLabel()
        self.server_arrow.setFixedSize(16, 16)
        server_row.addWidget(self.server_arrow)
        for label in (self.server_icon, self.selected_label, self.profile_meta, self.server_arrow):
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
        c.addWidget(self.server_picker)
        c.addSpacing(6)
        c.addWidget(self.label('ТРАФИК ЧЕРЕЗ VPN · ↓ ЗАГРУЖЕНО · ↑ ВЫГРУЖЕНО', 'timerCaption', True))
        traffic_row = QHBoxLayout()
        self.downloaded = self.label('↓  0 Б', 'heading')
        self.uploaded = self.label('↑  0 Б', 'heading')
        traffic_row.addWidget(self.downloaded, 1)
        traffic_row.addWidget(self.uploaded, 1)
        c.addLayout(traffic_row)
        self.traffic_rates = self.label('За сеанс · включая проверки соединения', 'smallMuted', True)
        c.addWidget(self.traffic_rates)
        self.hero.addWidget(self.connection_card, 11)
        self.companion_card = QFrame()
        self.companion_card.setObjectName('companionCard')
        self.companion_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        companion = QVBoxLayout(self.companion_card)
        companion.setContentsMargins(25, 22, 25, 16)
        companion.setSpacing(12)
        row = QHBoxLayout()
        row.addWidget(self.label('МАМБО РЯДОМ', 'eyebrow'))
        row.addStretch()
        self.shuffle = self.button('', self.mascot)
        self.shuffle.setObjectName('iconButton')
        self.shuffle.setFixedSize(29, 29)
        self.shuffle.setAccessibleName('Другая цитата и поза')
        self.shuffle.setToolTip('Другая цитата и поза')
        row.addWidget(self.shuffle)
        companion.addLayout(row)
        self.quote = self.label(random.choice(QUOTES), 'quote', True)
        self.quote.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        companion.addWidget(self.quote)
        companion.addStretch(1)
        self.art = self.button('', self.mascot)
        self.art.setObjectName('art')
        self.art.setMinimumHeight(185)
        self.art.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.art.setAccessibleName('Мамбо: сменить позу и воспроизвести звук')
        companion.addWidget(self.art)
        self.art_hint = self.label('Нажми на Мамбо — и улыбнись', 'smallMuted', True)
        self.art_hint.setAlignment(Qt.AlignCenter)
        companion.addWidget(self.art_hint)
        self.hero.addWidget(self.companion_card, 9)
        c = self.card(box, '')
        row = QHBoxLayout()
        labels = QVBoxLayout()
        labels.addWidget(self.label('Режим подключения', 'heading'))
        labels.addWidget(self.label('Выбирай, какой трафик направлять через VPN', 'smallMuted', True))
        row.addLayout(labels, 1)
        self.scope = QComboBox()
        self.scope.addItems(['Вся система · TUN', 'Только SOCKS · 127.0.0.1:10808'])
        self.scope.setCurrentIndex(int(bool(self.prefs.get('scope', 0))))
        self.scope.currentIndexChanged.connect(lambda i: self.pref('scope', i))
        self.scope.setMinimumWidth(265)
        row.addWidget(self.scope)
        c.addLayout(row)
        row = QHBoxLayout()
        self.health_result = self.label('Доступ в интернет можно проверить после подключения.', 'smallMuted', True)
        row.addWidget(self.health_result, 1)
        row.addWidget(self.button('Проверить доступ', self.health))
        c.addLayout(row)
        box.addStretch()

    def servers(self):
        box = self.page('Твои серверы', 'VLESS, Trojan, WireGuard, HTTPS-подписки и файлы .conf.')
        c = self.card(box, '')
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Найти сервер…')
        self.search.textChanged.connect(self.reload)
        row.addWidget(self.search, 1)
        row.addWidget(self.button('+ Вставить', self.import_dialog, True))
        row.addWidget(self.button('Открыть файл', self.import_file))
        c.addLayout(row)
        self.list = QListWidget()
        self.list.setObjectName('profiles')
        self.list.setSpacing(4)
        self.list.setMinimumHeight(290)
        self.list.itemSelectionChanged.connect(self.select)
        self.list.itemClicked.connect(self.choose_server)
        self.list.itemActivated.connect(self.choose_server)
        c.addWidget(self.list)
        row = QHBoxLayout()
        row.addWidget(self.button('★ Избранное', self.favorite))
        row.addStretch()
        row.addWidget(self.button('Удалить', self.delete))
        c.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(self.button('Пинг выбранного', lambda: self.probe(False, True), True))
        row.addWidget(self.button('Пинг всех', lambda: self.probe(True, True)))
        row.addWidget(self.button('Отмена', self.cancel_probe))
        c.addLayout(row)
        self.server_ping_result = self.label('GET через прокси · результат появится здесь и рядом с сервером.', 'smallMuted', True)
        self.server_ping_result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        c.addWidget(self.server_ping_result)
        self.import_result = self.label('Профили хранятся на твоём устройстве.', 'smallMuted', True)
        c.addWidget(self.import_result)
        box.addStretch()

    def ping(self):
        box = self.page('Проверка соединения', 'GET и HEAD проверяют путь через VPN. TCP и ICMP — доступность узла.')
        c = self.card(box, 'Параметры проверки')
        row = QHBoxLayout()
        left, right = QVBoxLayout(), QVBoxLayout()
        pt = self.prefs.get('ping_type', 'GET')
        pm = self.prefs.get('ping_mode', 'Default')
        self.pt = self.combo(left, 'Тип пинга', ['Proxy GET', 'Proxy HEAD', 'TCP', 'ICMP'],
            ['GET', 'HEAD', 'TCP', 'ICMP'].index(pt) if pt in ['GET', 'HEAD', 'TCP', 'ICMP'] else 0)
        self.pm = self.combo(right, 'Режим', ['Default', 'Double', 'KeepAlive'],
            ['Default', 'Double', 'KeepAlive'].index(pm) if pm in ['Default', 'Double', 'KeepAlive'] else 0)
        row.addLayout(left, 1)
        row.addLayout(right, 1)
        c.addLayout(row)
        row = QHBoxLayout()
        left, right = QVBoxLayout(), QVBoxLayout()
        left.addWidget(self.label('Тайм-аут', 'fieldLabel'))
        self.timeout = QSpinBox()
        self.timeout.setRange(1, 60)
        self.timeout.setValue(self.prefs.get('timeout', 8))
        self.timeout.setSuffix(' с')
        left.addWidget(self.timeout)
        right.addWidget(self.label('Адрес проверки', 'fieldLabel'))
        self.url = QLineEdit(self.prefs.get('test_url', 'https://www.gstatic.com/generate_204'))
        right.addWidget(self.url)
        row.addLayout(left, 1)
        row.addLayout(right, 3)
        c.addLayout(row)
        c.addWidget(self.label('Default — один запрос. Double — лучший из двух. KeepAlive — второй запрос в том же TLS-соединении. Для WireGuard используй GET или HEAD.', 'smallMuted', True))
        row = QHBoxLayout()
        row.addWidget(self.button('Выбранный сервер', lambda: self.probe(False), True))
        row.addWidget(self.button('Все серверы', lambda: self.probe(True)))
        row.addWidget(self.button('Отмена', self.cancel_probe))
        c.addLayout(row)
        c = self.card(box, 'Результаты')
        self.ping_result = self.label('Начни проверку — результаты появятся здесь.', 'muted', True)
        self.ping_result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        c.addWidget(self.ping_result)
        c = self.card(box, 'Диагностика сети')
        from .network_checks import MODES
        self.diagnostic_mode = self.combo(c, 'Что проверить', MODES)
        c.addWidget(self.label('Доступ напрямую и через прокси, DNS по UDP, стабильность и параметры WireGuard. Используются тайм-аут и URL выше.', 'smallMuted', True))
        row = QHBoxLayout()
        row.addWidget(self.button('Запустить диагностику', self.diagnose, True))
        row.addWidget(self.button('Отмена', self.cancel_probe))
        c.addLayout(row)
        self.diagnostic_result = self.label('Результат появится здесь и в журнале.', 'muted', True)
        self.diagnostic_result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        c.addWidget(self.diagnostic_result)
        box.addStretch()

    def routes(self):
        box = self.page('Маршрутизация', 'Правила применятся при следующем подключении: блокировка → DNS → VPN → напрямую.')
        c = self.card(box, 'Правила для доменов и IP')
        rules = {**DEFAULT, **self.store.rules()}
        self.rule_fields = {}
        for key, label in [('block', 'Блокировать'), ('proxy', 'Всегда через VPN'), ('direct', 'Напрямую')]:
            c.addWidget(self.label(label, 'fieldLabel'))
            w = QPlainTextEdit('\n'.join(rules[key]))
            w.setPlaceholderText('example.com или 192.0.2.0/24 · по одному на строке')
            w.setMaximumHeight(76)
            c.addWidget(w)
            self.rule_fields[key] = w
        c = self.card(box, 'Сеть и DNS')
        self.fallback = self.combo(c, 'Остальной трафик', ['Через VPN', 'Напрямую'], int(rules['fallback'] == 'direct'))
        self.lan = Switch('Локальная сеть напрямую')
        self.lan.setChecked(rules['lan'])
        c.addWidget(self.lan)
        self.ipv6 = Switch('Разрешить IPv6')
        self.ipv6.setChecked(rules['ipv6'])
        c.addWidget(self.ipv6)
        c.addWidget(self.label('DNS', 'fieldLabel'))
        self.dns = QLineEdit(rules['dns'])
        self.dns.setPlaceholderText('Пусто — из профиля или Cloudflare')
        c.addWidget(self.dns)
        c.addWidget(self.label('MTU', 'fieldLabel'))
        self.mtu = QSpinBox()
        self.mtu.setRange(576, 9000)
        self.mtu.setValue(rules['mtu'])
        c.addWidget(self.mtu)
        c.addWidget(self.button('Сохранить правила', self.save_routes, True))
        box.addStretch()

    def appearance(self):
        box = self.page('Как тебе нравится', 'Тема, персонаж и немного твоего настроения.')
        c = self.card(box, 'Выбери тему')
        c.addWidget(self.label('Переключатель темы также всегда доступен вверху окна.', 'smallMuted', True))
        grid = QGridLayout()
        grid.setSpacing(12)
        self.theme_tiles = {}
        for i, key in enumerate(THEMES):
            wide = key == 'minimal-dark'
            tile = ThemeTile(key, self.apply_theme, wide)
            grid.addWidget(tile, i//3, i%3, 1, 3 if wide else 1)
            self.theme_tiles[key] = tile
        c.addLayout(grid)
        c = self.card(box, 'Персонаж')
        self.characters = Switch('Показывать Мамбо')
        self.characters.setChecked(self.prefs.get('characters', True))
        self.characters.toggled.connect(lambda v: self.appear('characters', v))
        c.addWidget(self.characters)
        self.character_note = self.label('Когда персонаж скрыт, цитата остаётся компактной карточкой.', 'smallMuted', True)
        c.addWidget(self.character_note)
        self.animations = Switch('Анимация нажатия')
        self.animations.setChecked(self.prefs.get('animations', True))
        self.animations.toggled.connect(lambda v: self.pref('animations', v))
        c.addWidget(self.animations)
        c = self.card(box, 'Звук нажатия')
        values = ['meow', 'horse', 'mambo', 'mute']
        sound = self.prefs.get('sound', 'meow')
        self.bank = self.combo(c, 'Набор звуков', ['Мяуканье', 'Лошадь', 'Мамбо', 'Без звука'], values.index(sound) if sound in values else 0)
        self.bank.currentIndexChanged.connect(lambda i: self.pref('sound', values[i]))
        self.sample = self.combo(c, 'Вариант мяуканья', ['Случайное', 'Мяу 1', 'Мяу 2', 'Мяу 3', 'Мяу 4', 'Мяу 5'], self.prefs.get('sample', 0))
        self.sample.currentIndexChanged.connect(lambda i: self.pref('sample', i))
        c.addWidget(self.label('Громкость', 'fieldLabel'))
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(self.prefs.get('volume', 75))
        self.volume.valueChanged.connect(lambda v: self.pref('volume', v))
        c.addWidget(self.volume)
        c.addWidget(self.button('Проверить звук', self.play_sound, True))
        box.addStretch()

    def logs(self):
        box = self.page('Журнал', 'События приложения без ключей, подписок и содержимого трафика.')
        c = self.card(box, '')
        self.log_text = QPlainTextEdit()
        self.log_text.setObjectName('logText')
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(340)
        c.addWidget(self.log_text)
        row = QHBoxLayout()
        row.addWidget(self.button('Копировать', lambda: QApplication.clipboard().setText(self.log_text.toPlainText())))
        row.addWidget(self.button('Сохранить .txt', self.export_log))
        row.addStretch()
        row.addWidget(self.button('Очистить', self.clear_log))
        c.addLayout(row)
        box.addStretch()

    def refresh_nav(self, *args):
        t = THEMES[current_theme(self.prefs)]
        for i, name in enumerate(['home', 'servers', 'ping', 'routes', 'appearance', 'logs']):
            self.nav.item(i).setIcon(icon(name, t['accent'] if i == self.nav.currentRow() else t['muted']))

    def apply_theme(self, key):
        if key not in THEMES:
            return
        self.pref('theme', key)
        # Preserve earlier character and palette preferences while using minimal mode.
        if key != 'minimal-dark':
            self.pref('color', THEMES[key]['color'])
            self.pref('light', THEMES[key]['light'])
        self.theme()

    def appear(self, key, value):
        self.pref(key, value)
        self.theme()

    def theme(self):
        key = current_theme(self.prefs)
        t = THEMES[key]
        minimal = key == 'minimal-dark'
        palette = QPalette()
        for role, value in [
            (QPalette.Window, t['bg']), (QPalette.WindowText, t['ink']),
            (QPalette.Base, t['panel']), (QPalette.AlternateBase, t['alt']),
            (QPalette.Text, t['ink']), (QPalette.Button, t['alt']),
            (QPalette.ButtonText, t['ink']), (QPalette.Highlight, t['accent']),
            (QPalette.HighlightedText, t['on']), (QPalette.Mid, t['muted']),
            (QPalette.PlaceholderText, t['muted']), (QPalette.ToolTipBase, t['alt']),
            (QPalette.ToolTipText, t['ink']), (QPalette.Light, t['alt']),
            (QPalette.Dark, t['bg'])]:
            palette.setColor(role, QColor(value))
        QApplication.setPalette(palette)
        self.setPalette(palette)
        self.setStyleSheet(f'''
            QWidget {{ color:{t['ink']}; font-family:"Noto Sans"; font-size:14px; }}
            QMainWindow, QWidget#shell, QWidget#main {{ background:{t['bg']}; }}
            QFrame#sidebar {{ background:{t['side']}; border:0; }}
            QLabel {{ background:transparent; }}
            QLabel#logo {{ font-size:26px; font-weight:700; }}
            QLabel#brandMark {{ background:{t['soft']}; color:{t['accent']}; font-size:26px; font-weight:700; border-radius:12px; }}
            QLabel#title {{ font-size:30px; font-weight:600; }}
            QLabel#heading {{ font-size:16px; font-weight:600; }}
            QLabel#muted {{ color:{t['muted']}; font-size:13px; }}
            QLabel#smallMuted, QLabel#sideNote {{ color:{t['muted']}; font-size:12px; }}
            QLabel#sideNote {{ line-height:1.6; }}
            QLabel#eyebrow {{ color:{t['muted']}; font-size:10px; letter-spacing:1.2px; font-weight:600; }}
            QLabel#version {{ color:{t['muted']}; font-size:10px; }}
            QLabel#fieldLabel {{ color:{t['muted']}; font-size:12px; }}
            QLabel#quote {{ font-size:19px; font-weight:500; }}
            QLabel#connectionTitle {{ font-size:24px; font-weight:600; }}
            QLabel#elapsed {{ color:{t['accent']}; font-size:29px; font-weight:400; letter-spacing:1px; }}
            QLabel#timerCaption {{ color:{t['muted']}; font-size:9px; letter-spacing:1.1px; }}
            QLabel#statusBadge {{ color:{t['muted']}; background:{t['alt']}; border-radius:10px; padding:4px 9px; font-size:10px; }}
            QLabel#serverName {{ font-size:13px; font-weight:600; }}
            QFrame#card {{ background:{t['panel']}; border:0; border-radius:18px; }}
            QFrame#companionCard {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {t['panel']},stop:1 {t['soft']}); border:0; border-radius:18px; }}
            QScrollArea, QStackedWidget {{ background:transparent; border:0; }}
            QScrollArea > QWidget > QWidget {{ background:transparent; }}
            QPushButton {{ background:{t['alt']}; border:1px solid transparent; border-radius:10px; padding:10px 15px; }}
            QPushButton:hover {{ background:{t['soft']}; }}
            QPushButton:pressed {{ background:{t['bg']}; }}
            QPushButton:disabled {{ color:{t['muted']}; }}
            QPushButton:focus {{ border-color:{t['muted']}; }}
            QPushButton#primary {{ background:{t['accent']}; color:{t['on']}; font-weight:600; border:1px solid transparent; }}
            QPushButton#primary:hover {{ border-color:{t['ink']}; }}
            QPushButton#art, QPushButton#power {{ background:transparent; border:0; padding:0; }}
            QPushButton#art:hover {{ background:transparent; }}
            QPushButton#iconButton {{ background:transparent; border:0; padding:4px; }}
            QPushButton#iconButton:hover {{ background:{t['alt']}; }}
            QPushButton#serverPicker {{ background:{t['alt']}; border:0; padding:0; text-align:left; }}
            QPushButton#serverPicker:hover {{ background:{t['soft']}; }}
            QListWidget {{ background:transparent; border:0; outline:0; }}
            QListWidget::item {{ padding:14px 12px; border-radius:10px; margin:0 0 5px 0; color:{t['muted']}; }}
            QListWidget::item:hover {{ background:{t['panel']}; }}
            QListWidget::item:selected {{ background:{t['soft']}; color:{t['accent']}; }}
            QListWidget#navigation {{ font-size:13px; }}
            QListWidget#profiles {{ background:{t['bg']}; border-radius:12px; }}
            QListWidget#profiles::item {{ padding:16px; color:{t['ink']}; }}
            QListWidget#profiles::item:selected {{ background:{t['soft']}; color:{t['ink']}; }}
            QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {{ background:{t['alt']}; border:1px solid transparent; border-radius:9px; padding:9px 11px; selection-background-color:{t['accent']}; selection-color:{t['on']}; }}
            QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color:{t['accent']}; }}
            QComboBox {{ padding-right:28px; }}
            QComboBox#themePicker {{ background:{t['panel']}; font-size:12px; padding:8px 28px 8px 12px; }}
            QComboBox::drop-down {{ border:0; width:25px; }}
            QComboBox::down-arrow {{ image:url({(Path(__file__).parent / 'icons' / (key + '-down.svg')).as_posix()}); width:12px; height:12px; }}
            QSpinBox {{ padding-right:28px; }}
            QSpinBox::up-button {{ subcontrol-origin:border; subcontrol-position:top right; width:25px; border:0; background:transparent; }}
            QSpinBox::down-button {{ subcontrol-origin:border; subcontrol-position:bottom right; width:25px; border:0; background:transparent; }}
            QSpinBox::up-arrow {{ image:url({(Path(__file__).parent / 'icons' / (key + '-up.svg')).as_posix()}); width:10px; height:10px; }}
            QSpinBox::down-arrow {{ image:url({(Path(__file__).parent / 'icons' / (key + '-down.svg')).as_posix()}); width:10px; height:10px; }}
            QComboBox QAbstractItemView {{ background:{t['panel']}; color:{t['ink']}; border:1px solid {t['alt']}; selection-background-color:{t['soft']}; selection-color:{t['ink']}; padding:6px; outline:0; }}
            QDialog, QMessageBox {{ background:{t['bg']}; }}
            QSlider::groove:horizontal {{ height:4px; background:{t['alt']}; border-radius:2px; }}
            QSlider::sub-page:horizontal {{ background:{t['accent']}; border-radius:2px; }}
            QSlider::handle:horizontal {{ background:{t['accent']}; width:16px; margin:-6px 0; border-radius:8px; }}
            QScrollBar:vertical {{ background:transparent; width:6px; margin:2px 0; }}
            QScrollBar::handle:vertical {{ background:{t['alt']}; border-radius:3px; min-height:25px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background:transparent; }}
            QToolTip {{ background:{t['alt']}; color:{t['ink']}; border:0; padding:7px; }}
        ''')
        with QSignalBlocker(self.theme_picker):
            self.theme_picker.setCurrentIndex(list(THEMES).index(key))
        for tile_key, tile in self.theme_tiles.items():
            tile.setChecked(tile_key == key)
            tile.update()
        self.characters.setEnabled(not minimal)
        self.animations.setEnabled(not minimal)
        self.character_note.setText('Минимализм скрывает персонажа и цитаты. Твой выбор сохраняется для остальных тем.' if minimal
            else 'Когда персонаж скрыт, цитата остаётся компактной карточкой.')
        self.brand.setText('Соединение' if minimal else 'mambo')
        self.brand.setStyleSheet('font-size:18px;font-weight:600;' if minimal else '')
        self.brand_mark.setText('○' if minimal else 'm')
        self.brand_caption.setText('Личное подключение' if minimal else 'Твой спокойный уголок')
        self.side_note.setVisible(not minimal)
        self.home_title.setText('Твоё соединение' if minimal else 'Главная')
        self.server_icon.setPixmap(icon('servers', t['accent']).pixmap(22, 22))
        self.server_arrow.setPixmap(icon('arrow', t['muted']).pixmap(16, 16))
        self.shuffle.setIcon(icon('refresh', t['muted']))
        self.refresh_nav()
        self.show_art()
        self.power.update()

    def show_art(self):
        key = current_theme(self.prefs)
        minimal = key == 'minimal-dark'
        show = self.prefs.get('characters', True) and not minimal
        self.art.setVisible(show)
        self.art_hint.setVisible(show)
        self.companion_card.setVisible(not minimal)
        self.hero.setDirection(QBoxLayout.LeftToRight if show or minimal else QBoxLayout.TopToBottom)
        if minimal:
            return
        self.quote.setStyleSheet('font-size:19px;' if show else 'font-size:16px;')
        color = THEMES[key]['color']
        poses = ['hello', 'cool', 'heart', 'boss', 'wrench', 'flip-clean3'] if color != 'red' else ['hello', 'flip-clean3']
        path = ASSETS / (color + '-' + poses[self.pose % len(poses)] + '.png')
        if str(path) not in self.pixmaps:
            self.pixmaps[str(path)] = QPixmap(str(path))
        self.art.setIcon(QIcon(self.pixmaps[str(path)]))
        self.art.setIconSize(QSize(280, 215))

    def update_connection(self, state):
        running = bool(state.get('running'))
        internet = state.get('internet')
        verified = access_ok(internet, state.get('scope'))
        self.status.setText(('Подключено' if verified else 'Нет доступа' if internet else 'Проверяем доступ…') if running else 'Отключено')
        self.status_badge.setText(('●  Доступ есть' if verified else '●  Нет ответа' if internet else '●  Проверка') if running else '●  Не активно')
        self.power.running = running
        self.power.setText('Отключить' if running else 'Подключить')
        self.power.setAccessibleName('Отключить VPN' if running else 'Подключить VPN')
        self.power.setToolTip('Отключить' if running else 'Подключить')
        self.power.update()
        self.elapsed.setText(format_duration(state.get('uptime_seconds', 0) if running else 0))
        traffic = state.get('traffic', {})
        self.downloaded.setText('↓  '+format_bytes(traffic.get('downloaded', 0)))
        self.uploaded.setText('↑  '+format_bytes(traffic.get('uploaded', 0)))
        note = ('За сеанс' if running else 'Последний сеанс') if traffic.get('downloaded') or traffic.get('uploaded') else 'За сеанс'
        self.traffic_rates.setText(note+' · ↓ '+format_bytes(traffic.get('download_rate', 0))+'/с · ↑ '+format_bytes(traffic.get('upload_rate', 0))+'/с · включая проверки'+(' · счётчик временно недоступен' if running and not traffic.get('available') else ''))
        if running:
            if verified:
                self.connect_caption.setText('Вся система через VPN' if state.get('scope') == 'tun' else 'Локальный SOCKS-прокси активен')
            elif internet:
                self.connect_caption.setText('Не удалось подтвердить доступ. Подробности ниже и в журнале.')
            else:
                self.connect_caption.setText('Ядро запущено, проверяем передачу трафика')
        else:
            self.connect_caption.setText('Нажми на кнопку, чтобы подключиться')
