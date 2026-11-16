"""Qt weather presentation, drawn in code rather than downloaded imagery."""
from datetime import datetime
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QColor, QPainter, QRadialGradient, QPainterPath, QPolygonF
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
                             QGridLayout, QScrollArea, QGraphicsDropShadowEffect)


def label(text, name=None):
    result = QLabel(str(text))
    result.setTextFormat(Qt.TextFormat.PlainText)
    result.setWordWrap(True)
    if name:
        result.setObjectName(name)
    return result


def number(value, suffix='', decimals=0):
    if value is None:
        return '—'
    return f'{value:.{decimals}f}{suffix}'


class WeatherIcon(QWidget):
    """Soft, dimensional weather icons rendered with Qt gradients."""
    def __init__(self, kind, is_day=True, size=92):
        super().__init__()
        self.kind, self.is_day = kind, is_day
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(self.width() / 128, self.height() / 128)
        painter.setPen(Qt.PenStyle.NoPen)
        def sphere(x, y, size, light, dark):
            gradient = QRadialGradient(QPointF(x + size * .32, y + size * .24), size * .78)
            gradient.setColorAt(0, QColor(light))
            gradient.setColorAt(1, QColor(dark))
            painter.setBrush(gradient)
            painter.drawEllipse(QRectF(x, y, size, size))
        if self.kind in ('sun', 'partly'):
            if self.is_day:
                sphere(9, 10, 65, '#fff07a', '#ff9f00')
            else:
                sphere(14, 9, 61, '#f8f9ff', '#a8b9dd')
                sphere(34, 3, 49, '#273e75', '#12274d')
        if self.kind in ('cloud', 'partly', 'rain', 'storm', 'snow'):
            sphere(13, 43, 56, '#ffffff', '#b4c8dc')
            sphere(40, 24, 70, '#ffffff', '#bdcede')
            sphere(70, 44, 45, '#ffffff', '#b4c9dc')
            painter.setBrush(QColor('#eaf3fa'))
            painter.drawRoundedRect(QRectF(32, 68, 65, 25), 12, 12)
        if self.kind == 'rain':
            for x in (29, 54, 79):
                path = QPainterPath(QPointF(x + 6, 90))
                path.cubicTo(x + 2, 101, x - 1, 106, x, 111)
                path.cubicTo(x + 1, 123, x + 13, 123, x + 14, 111)
                path.cubicTo(x + 14, 106, x + 10, 99, x + 6, 90)
                gradient = QRadialGradient(QPointF(x + 3, 108), 16)
                gradient.setColorAt(0, QColor('#aef9ff'))
                gradient.setColorAt(1, QColor('#008bd4'))
                painter.setBrush(gradient)
                painter.drawPath(path)
        if self.kind == 'storm':
            painter.setBrush(QColor('#ffd631'))
            painter.drawPolygon(QPolygonF([QPointF(72, 80), QPointF(51, 106), QPointF(67, 105),
                                          QPointF(60, 125), QPointF(91, 96), QPointF(76, 97), QPointF(85, 80)]))
        if self.kind == 'snow':
            painter.setBrush(QColor('#e7f9ff'))
            for x in (29, 53, 78):
                painter.drawEllipse(QRectF(x, 99, 9, 9))


def card(name='weatherCard'):
    frame = QFrame()
    frame.setObjectName(name)
    shadow = QGraphicsDropShadowEffect(frame)
    shadow.setBlurRadius(20)
    shadow.setOffset(0, 6)
    shadow.setColor(QColor(0, 17, 42, 95))
    frame.setGraphicsEffect(shadow)
    return frame


class WeatherView(QFrame):
    def __init__(self, close_callback):
        super().__init__()
        self.setObjectName('weatherSurface')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 2, 4, 2)
        header = QHBoxLayout()
        self.heading = label('EL CLIMA', 'weatherHeading')
        header.addWidget(self.heading)
        header.addStretch()
        self.live_status = label('', 'weatherSmall')
        header.addWidget(self.live_status)
        close = QPushButton('Volver')
        close.setToolTip('Cerrar la vista del clima')
        close.clicked.connect(close_callback)
        header.addWidget(close)
        outer.addLayout(header)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content.setObjectName('weatherContent')
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(12, 8, 12, 14)
        self.body.setSpacing(14)
        self.scroll.setWidget(self.content)
        outer.addWidget(self.scroll, 1)
        self.setMinimumHeight(330)
        self.setStyleSheet('''
            QFrame#weatherSurface, QWidget#weatherContent, QScrollArea { background: transparent; border: none; }
            QLabel { background: transparent; border: none; color: #f6fbff; }
            QLabel#weatherHeading { color: #8de8ff; font-size: 13px; font-weight: 800; letter-spacing: 2px; }
            QLabel#weatherPlace { font-size: 20px; font-weight: 800; }
            QLabel#weatherDegrees { font-size: 52px; font-weight: 800; }
            QLabel#weatherCondition { font-size: 17px; font-weight: 700; }
            QLabel#weatherSmall { color: #c7e4f0; font-size: 11px; }
            QLabel#weatherMetric { font-size: 19px; font-weight: 700; }
            QLabel#weatherCaption { color: #c2e1ef; font-size: 11px; }
            QFrame#weatherHero { border-radius: 20px; background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #257cc1, stop:0.55 #147cb6, stop:1 #1965a9); }
            QFrame#weatherCard { border-radius: 15px; background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #294f79, stop:1 #183c62); }
            QFrame#weatherForecast { border-radius: 15px; background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #335984, stop:1 #263e6c); }
        ''')

    def set_notice(self, text):
        self.live_status.setText(text)

    def show_data(self, data):
        self.set_notice('')
        while self.body.count():
            item = self.body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
        place = data['location']
        current = data['current']
        hero = card('weatherHero')
        box = QHBoxLayout(hero)
        box.setContentsMargins(20, 14, 20, 14)
        hero_text = QVBoxLayout()
        location = ', '.join(dict.fromkeys(filter(None, (place.get('place'), place.get('region'), place.get('country')))))
        hero_text.addWidget(label(location or place.get('label', ''), 'weatherPlace'))
        if data.get('is_capital'):
            hero_text.addWidget(label('Capital · consulta por país', 'weatherSmall'))
        hero_text.addWidget(label(number(current.get('temperature'), '°'), 'weatherDegrees'))
        hero_text.addWidget(label(current.get('description', 'Clima no disponible'), 'weatherCondition'))
        hero_text.addWidget(label('Sensación ' + number(current.get('feels_like'), '°') + ' · Hora local: ' + current.get('time', '').replace('T', ' '), 'weatherSmall'))
        box.addLayout(hero_text, 1)
        box.addWidget(WeatherIcon(current.get('icon', 'cloud'), current.get('is_day', True), 126))
        self.body.addWidget(hero)
        metrics_widget = QWidget()
        metrics_widget.setObjectName('weatherContent')
        metrics = QGridLayout(metrics_widget)
        metrics.setContentsMargins(0, 0, 0, 0)
        metrics.setHorizontalSpacing(12)
        metrics.setVerticalSpacing(12)
        today = (data.get('daily') or [{}])[0]
        def clock(value):
            try:
                return datetime.fromisoformat(value).strftime('%H:%M')
            except (TypeError, ValueError):
                return '—'
        values = [('HUMEDAD', number(current.get('humidity'), '%')),
                  ('VIENTO', number(current.get('wind'), ' km/h')),
                  ('PRECIPITACIÓN', number(current.get('precipitation'), ' mm', 1)),
                  ('LLUVIA HOY', number(today.get('precipitation_probability'), '%')),
                  ('MÁXIMA / MÍNIMA', number(today.get('max'), '°') + ' / ' + number(today.get('min'), '°')),
                  ('ÍNDICE UV MÁX.', number(today.get('uv'), '', 1)),
                  ('AMANECER', clock(today.get('sunrise'))),
                  ('ATARDECER', clock(today.get('sunset')))]
        for index, (title, value) in enumerate(values):
            frame = card()
            inner = QVBoxLayout(frame)
            inner.setContentsMargins(15, 11, 15, 11)
            inner.addWidget(label(title, 'weatherCaption'))
            inner.addWidget(label(value, 'weatherMetric'))
            metrics.addWidget(frame, index // 2, index % 2)
        self.body.addWidget(metrics_widget)
        self.body.addWidget(label('PRÓXIMOS DÍAS', 'weatherHeading'))
        forecasts = QWidget()
        forecasts.setObjectName('weatherContent')
        row = QHBoxLayout(forecasts)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        days = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
        for index, day in enumerate(data.get('daily', [])):
            frame = card('weatherForecast')
            column = QVBoxLayout(frame)
            column.setContentsMargins(12, 10, 12, 10)
            try:
                date = datetime.fromisoformat(day['date'])
                title = 'Hoy' if index == 0 else days[date.weekday()]
                title += ' · ' + date.strftime('%d/%m')
            except (KeyError, TypeError, ValueError):
                title = 'Pronóstico'
            column.addWidget(label(title, 'weatherCaption'))
            column.addWidget(WeatherIcon(day.get('icon', 'cloud'), size=60))
            column.addWidget(label(number(day.get('max'), '°') + ' / ' + number(day.get('min'), '°'), 'weatherMetric'))
            column.addWidget(label(day.get('description', '—'), 'weatherSmall'))
            column.addWidget(label('Lluvia ' + number(day.get('precipitation_probability'), '%'), 'weatherSmall'))
            row.addWidget(frame, 1)
        self.body.addWidget(forecasts)
        self.body.addWidget(label('Open-Meteo · datos modelados más recientes · © OpenStreetMap contributors', 'weatherSmall'))
        self.body.addStretch()
        self.scroll.verticalScrollBar().setValue(0)

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
