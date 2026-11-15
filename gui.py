"""Interfaz de escritorio de JARVIS. Ejecutar con `python gui.py`."""
from __future__ import annotations
import json
import math
import os
import sys
import threading

from dotenv import load_dotenv
from PyQt6.QtCore import QObject, QThread, Qt, QTimer, QPointF, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont, QColor, QPainter, QRadialGradient
from PyQt6.QtWidgets import (QApplication, QCheckBox,
                             QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                             QPushButton, QVBoxLayout,
                             QWidget)

from brain import Brain
from main import ROOT, STATE
from system_control import SystemController
from voice import Voice
from voice_session import VoiceSession
from microphone import listen


class VoiceSignals(QObject):
    activity = pyqtSignal(bool)


class CoreAnimation(QWidget):
    """Draw a free-standing core; waves move only during audio playback."""
    def __init__(self):
        super().__init__()
        self.setFixedSize(300, 260)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.active = False
        self.phase = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.advance)

    @pyqtSlot(bool)
    def set_speaking(self, active):
        self.active = active
        if active:
            self.timer.start()
        else:
            self.timer.stop()
        self.update()

    def advance(self):
        self.phase += 0.055
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        radius = 109.0

        # A dark, transparent glow rather than a rectangular background.
        glow = QRadialGradient(QPointF(0, 0), radius * 1.12)
        glow.setColorAt(0, QColor(20, 16, 100, 18))
        glow.setColorAt(0.76, QColor(28, 28, 174, 28))
        glow.setColorAt(1, QColor(12, 10, 85, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(0, 0), radius * 1.12, radius * 1.12)

        # Latitude rings projected in 3D: points on both hemispheres make the
        # hologram look like the reference, including its dotted polar circles.
        tilt = 0.22
        points = []
        for latitude in range(1, 41):
            theta = math.pi * latitude / 41
            sin_theta, cos_theta = math.sin(theta), math.cos(theta)
            count = max(12, round(72 * sin_theta))
            for longitude in range(count):
                angle = 2 * math.pi * longitude / count + self.phase * 0.65
                x = sin_theta * math.cos(angle)
                y = cos_theta
                depth = sin_theta * math.sin(angle)
                # Tilt exposes the rings around the upper and lower poles.
                screen_y = y * math.cos(tilt) - depth * math.sin(tilt)
                z = depth * math.cos(tilt) + y * math.sin(tilt)
                pulse = 1.0
                if self.active:
                    pulse += 0.025 * math.sin(theta * 8 + self.phase * 3 + angle * 2)
                px, py = radius * x * pulse, -radius * screen_y * pulse
                alpha = int(105 + 110 * (z + 1) / 2)
                dot = 0.65 + 0.35 * (z + 1) / 2
                points.append((z, px, py, dot, alpha))

        for _, x, y, dot, alpha in sorted(points):
            painter.setBrush(QColor(70, 81, 255, max(20, alpha // 5)))
            painter.drawEllipse(QPointF(x, y), dot * 2.3, dot * 2.3)
            painter.setBrush(QColor(128, 136, 255, alpha))
            painter.drawEllipse(QPointF(x, y), dot, dot)
        painter.end()


class VoiceWorker(QObject):
    status = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, brain, voice):
        super().__init__()
        self.session = VoiceSession(brain, voice, listen, self.status.emit)

    @pyqtSlot()
    def run(self):
        try:
            self.session.run()
        finally:
            self.finished.emit()


class JarvisWindow(QMainWindow):
    def __init__(self, brain, voice):
        super().__init__()
        self.brain, self.voice = brain, voice
        self.thread = None
        self.worker = None
        self.setWindowTitle('JARVIS')
        self.resize(860, 800)
        self.setMinimumSize(560, 520)
        self.setStyleSheet(STYLE)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(30, 24, 30, 24)
        layout.setSpacing(18)

        top = QHBoxLayout()
        logo = QLabel('J  /  JARVIS')
        logo.setObjectName('brand')
        top.addWidget(logo)
        top.addStretch()
        self.pin = QCheckBox('Siempre visible')
        self.pin.toggled.connect(self.toggle_pin)
        top.addWidget(self.pin)
        layout.addLayout(top)

        heading = QLabel('Tu asistente, listo para ayudarte.')
        heading.setObjectName('heading')
        layout.addWidget(heading)
        subtitle = QLabel('Conversa, consulta y controla tu equipo con tu autorización.')
        subtitle.setObjectName('muted')
        layout.addWidget(subtitle)

        self.core = CoreAnimation()
        layout.addWidget(self.core, 0, Qt.AlignmentFlag.AlignHCenter)
        self.voice_signals = VoiceSignals(self)
        self.voice_signals.activity.connect(self.core.set_speaking)
        self.voice.on_activity = self.voice_signals.activity.emit

        layout.addStretch(1)
        self.status = QLabel('Micrófono apagado')
        self.status.setObjectName('statusBadge')
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status)
        self.mic = QPushButton('Activar micrófono')
        self.mic.setObjectName('send')
        self.mic.setMinimumHeight(60)
        self.mic.clicked.connect(self.toggle_microphone)
        layout.addWidget(self.mic)
        info = QLabel('Di “autorizo” para aprobar una acción. Usa el botón para apagar el micrófono.')
        info.setObjectName('footer')
        info.setWordWrap(True)
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info)
        layout.addStretch(1)

    def toggle_pin(self, checked):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, checked)
        self.show()

    def toggle_microphone(self):
        if self.thread is not None:
            self.worker.session.stop()
            self.status.setText('Deteniendo micrófono…')
            self.mic.setEnabled(False)
            return
        self.thread = QThread(self)
        self.worker = VoiceWorker(self.brain, self.voice)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.status.connect(self.status.setText)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.cleanup)
        self.mic.setText('Apagar micrófono')
        self.thread.start()

    @pyqtSlot()
    def cleanup(self):
        self.thread.deleteLater()
        self.thread = None
        self.worker = None
        self.status.setText('Micrófono apagado')
        self.mic.setText('Activar micrófono')
        self.mic.setEnabled(True)

    def closeEvent(self, event):
        if self.thread is not None:
            self.worker.session.stop()
            self.mic.setEnabled(False)
            self.status.setText('Deteniendo micrófono…')
            QMessageBox.information(self, 'JARVIS', 'El micrófono se está deteniendo. Espera un momento y vuelve a cerrar la ventana.')
            event.ignore()
        else:
            self.voice.on_activity = None
            event.accept()


STYLE = '''
QWidget { background: #0b111b; color: #e4edf7; font-family: "Segoe UI", sans-serif; font-size: 13px; }
QLabel { background: transparent; }
QLabel#brand { color: #85d9e9; font-size: 15px; font-weight: 800; letter-spacing: 3px; }
QLabel#heading { font-size: 24px; font-weight: 700; color: #f5f9fc; }
QLabel#muted, QLabel#footer { color: #8496aa; }
QLabel#footer { font-size: 11px; }
QLabel#statusBadge { color: #74d8c4; font-size: 11px; font-weight: 700; }
QLabel#model { color: #8296ab; font-size: 11px; }
QFrame#panel { background: #111b28; border: 1px solid #223447; border-radius: 16px; }
QTextBrowser, QPlainTextEdit { background: #111b28; border: 1px solid #283b4e; border-radius: 10px; padding: 12px; selection-background-color: #287487; }
QTextBrowser { border: none; line-height: 1.6; }
QPushButton { border: 1px solid #31475b; border-radius: 9px; padding: 10px 16px; background: #1c2b3b; }
QPushButton:hover { background: #294154; }
QPushButton#send, QPushButton#approveButton { background: #76d7e4; color: #07151d; border: none; font-weight: 700; }
QPushButton#send:disabled { background: #344957; color: #8296aa; }
QCheckBox { color: #a8b9c9; }
QDialog { background: #0b111b; }
QLabel#dialogTitle { font-size: 19px; font-weight: 700; }
'''


def main():
    load_dotenv(ROOT / '.env')
    app = QApplication(sys.argv)
    app.setFont(QFont('Segoe UI', 10))
    # Announce before the first-run gate, just like the console entry point.
    voice = Voice()
    print('Activando protocolos de seguridad...', flush=True)
    voice.speak('Activando protocolos de seguridad...')
    try:
        state = json.loads(STATE.read_text(encoding='utf-8'))
        accepted = state.get('initial_accepted') is True
    except (OSError, ValueError, AttributeError):
        accepted = False
    if not accepted:
        response = QMessageBox.question(None, 'Protocolo de seguridad',
            'JARVIS puede ejecutar comandos y acceder a archivos con tus permisos. No lo ejecutes como administrador. ¿Autorizas iniciar en esta máquina?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if response != QMessageBox.StandardButton.Yes:
            return 1
        try:
            STATE.write_text(json.dumps({'initial_accepted': True}), encoding='utf-8')
        except OSError:
            QMessageBox.critical(None, 'JARVIS', 'No se pudo guardar la confirmación inicial.')
            return 1
    try:
        brain = Brain(os.getenv('GEMINI_API_KEY'), SystemController(), lambda *_: False,
                      name=os.getenv('JARVIS_NAME', 'Señor'), model=os.getenv('GEMINI_MODEL', 'gemini-2.5-flash'))
    except (ValueError, RuntimeError) as exc:
        QMessageBox.critical(None, 'No se pudo iniciar', str(exc))
        return 1
    window = JarvisWindow(brain, voice)
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
