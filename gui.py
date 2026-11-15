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
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox,
                             QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
                             QPushButton, QPlainTextEdit, QTabWidget, QVBoxLayout, QWidget)

from provider import create_brain
from errors import describe_error
from main import ROOT, STATE
from system_control import SystemController
from voice import Voice
from voice_session import VoiceSession
from microphone import listen
from core_state import CoreState


class VoiceSignals(QObject):
    activity = pyqtSignal(bool)


class CoreAnimation(QWidget):
    """Draw a free-standing core; waves move only during audio playback."""
    def __init__(self):
        super().__init__()
        self.setFixedSize(300, 260)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.mode = 'idle'
        self.phase = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.advance)

    def set_mode(self, mode):
        self.mode = mode
        if mode in ('thinking', 'speaking'):
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
        if self.mode == 'approval':
            glow.setColorAt(0, QColor(130, 65, 4, 22))
            glow.setColorAt(0.76, QColor(230, 130, 18, 38))
            glow.setColorAt(1, QColor(90, 45, 5, 0))
        else:
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
                if self.mode == 'speaking':
                    pulse += 0.06 * math.sin(self.phase * 2.5) + 0.025 * math.sin(theta * 8 + self.phase * 3 + angle * 2)
                px, py = radius * x * pulse, -radius * screen_y * pulse
                alpha = int(105 + 110 * (z + 1) / 2)
                dot = 0.65 + 0.35 * (z + 1) / 2
                points.append((z, px, py, dot, alpha))

        for _, x, y, dot, alpha in sorted(points):
            painter.setBrush(QColor(*( (255, 140, 32) if self.mode == 'approval' else (70, 81, 255) ), max(20, alpha // 5)))
            painter.drawEllipse(QPointF(x, y), dot * 2.3, dot * 2.3)
            painter.setBrush(QColor(*( (255, 195, 100) if self.mode == 'approval' else (128, 136, 255) ), alpha))
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


class ChatWorker(QObject):
    result = pyqtSignal(str)
    error = pyqtSignal(str)
    approval = pyqtSignal(str, object)
    finished = pyqtSignal()

    def __init__(self, brain, text):
        super().__init__()
        self.brain, self.text = brain, text
        self.answer = False
        self.ready = threading.Event()

    def ask_approval(self, name, args):
        self.answer = False
        self.ready.clear()
        self.approval.emit(name, args)
        self.ready.wait()
        return self.answer

    def resolve_approval(self, approved):
        self.answer = approved
        self.ready.set()

    @pyqtSlot()
    def run(self):
        try:
            self.brain.approve = self.ask_approval
            self.result.emit(self.brain.ask(self.text))
        except Exception as exc:
            self.error.emit(describe_error(exc))
        finally:
            self.finished.emit()


class ApprovalDialog(QDialog):
    def __init__(self, name, args, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Confirmar acción')
        self.resize(560, 400)
        layout = QVBoxLayout(self)
        heading = QLabel('JARVIS solicita permiso')
        heading.setObjectName('dialogTitle')
        layout.addWidget(heading)
        info = QLabel('Revisa la acción completa. Se ejecutará con tus permisos.')
        info.setWordWrap(True)
        layout.addWidget(info)
        details = QPlainTextEdit()
        details.setReadOnly(True)
        details.setPlainText(name + '\n\n' + json.dumps(args, ensure_ascii=False, indent=2, default=str))
        layout.addWidget(details)
        buttons = QDialogButtonBox()
        deny = buttons.addButton('Rechazar', QDialogButtonBox.ButtonRole.RejectRole)
        accept = buttons.addButton('Autorizar', QDialogButtonBox.ButtonRole.AcceptRole)
        accept.setObjectName('approveButton')
        deny.setDefault(True)
        deny.clicked.connect(self.reject)
        accept.clicked.connect(self.accept)
        layout.addWidget(buttons)


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
        self.core_state = CoreState()
        self.voice_signals.activity.connect(self.on_voice_activity)
        self.voice.on_activity = self.voice_signals.activity.emit

        self.status = QLabel('Micrófono apagado')
        self.status.setObjectName('statusBadge')
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        chat = QWidget()
        chat_layout = QVBoxLayout(chat)
        self.history = QPlainTextEdit()
        self.history.setReadOnly(True)
        self.history.setPlaceholderText('Tu conversación con JARVIS aparecerá aquí.')
        chat_layout.addWidget(self.history, 1)
        composer = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText('Escribe tu mensaje…')
        self.input.returnPressed.connect(self.submit_chat)
        composer.addWidget(self.input, 1)
        self.send = QPushButton('Enviar')
        self.send.setObjectName('send')
        self.send.clicked.connect(self.submit_chat)
        composer.addWidget(self.send)
        chat_layout.addLayout(composer)
        self.chat_audio = QCheckBox('Leer respuestas en voz alta')
        self.chat_audio.setChecked(True)
        chat_layout.addWidget(self.chat_audio)
        self.tabs.addTab(chat, 'Chat')

        voice_tab = QWidget()
        voice_layout = QVBoxLayout(voice_tab)
        voice_layout.addStretch(1)
        self.mic = QPushButton('Activar micrófono')
        self.mic.setObjectName('send')
        self.mic.setMinimumHeight(60)
        self.mic.clicked.connect(self.toggle_microphone)
        voice_layout.addWidget(self.mic)
        info = QLabel('Di “Jarvis” para empezar y “autorizo” para aprobar una acción.')
        info.setObjectName('footer')
        info.setWordWrap(True)
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        voice_layout.addWidget(info)
        voice_layout.addStretch(1)
        self.tabs.addTab(voice_tab, 'Voz')

    def append_chat(self, author, text):
        self.history.appendPlainText(f'{author}: {text}\n')

    def submit_chat(self):
        text = self.input.text().strip()
        if not text or self.thread is not None:
            return
        self.input.clear()
        self.append_chat('Tú', text)
        self.set_task_state('thinking')
        self.status.setText('JARVIS está pensando…')
        self.send.setEnabled(False)
        self.tabs.tabBar().setEnabled(False)
        self.thread = QThread(self)
        self.worker = ChatWorker(self.brain, text)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.approval.connect(self.request_chat_approval)
        self.worker.result.connect(self.chat_result)
        self.worker.error.connect(self.chat_error)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.cleanup)
        self.thread.start()

    @pyqtSlot(str, object)
    def request_chat_approval(self, name, args):
        self.set_task_state('approval')
        self.status.setText('Esperando tu autorización…')
        approved = ApprovalDialog(name, args, self).exec() == QDialog.DialogCode.Accepted
        self.worker.resolve_approval(approved)
        self.set_task_state('thinking')
        self.status.setText('JARVIS está trabajando…')

    @pyqtSlot(str)
    def chat_result(self, text):
        self.set_task_state('idle')
        self.append_chat('JARVIS', text)
        if self.chat_audio.isChecked():
            self.voice.speak(text)

    @pyqtSlot(str)
    def chat_error(self, error):
        self.set_task_state('idle')
        self.append_chat('Sistema', error)

    def set_task_state(self, state):
        self.core.set_mode(self.core_state.set_task(state))

    @pyqtSlot(bool)
    def on_voice_activity(self, active):
        self.core.set_mode(self.core_state.set_speaking(active))

    @pyqtSlot(str)
    def on_voice_status(self, status):
        self.status.setText(status)
        if status.startswith('Esperando autorización'):
            self.set_task_state('approval')
        elif status == 'Pensando':
            self.set_task_state('thinking')
        else:
            self.set_task_state('idle')

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
        self.worker.status.connect(self.on_voice_status)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.cleanup)
        self.mic.setText('Apagar micrófono')
        self.tabs.tabBar().setEnabled(False)
        self.thread.start()

    @pyqtSlot()
    def cleanup(self):
        self.thread.deleteLater()
        self.thread = None
        self.worker = None
        self.set_task_state('idle')
        if not self.status.text().startswith('Error'):
            self.status.setText('Micrófono apagado')
        self.mic.setText('Activar micrófono')
        self.mic.setEnabled(True)
        self.send.setEnabled(True)
        self.tabs.tabBar().setEnabled(True)

    def closeEvent(self, event):
        if self.thread is not None:
            if isinstance(self.worker, VoiceWorker):
                self.worker.session.stop()
                self.mic.setEnabled(False)
                self.status.setText('Deteniendo micrófono…')
                message = 'El micrófono se está deteniendo. Espera y vuelve a cerrar la ventana.'
            else:
                message = 'Espera a que termine la solicitud antes de cerrar la ventana.'
            QMessageBox.information(self, 'JARVIS', message)
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
QLineEdit, QTextBrowser, QPlainTextEdit { background: #111b28; border: 1px solid #283b4e; border-radius: 10px; padding: 12px; selection-background-color: #287487; }
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
        brain = create_brain(SystemController(), lambda *_: False)
    except (ValueError, RuntimeError) as exc:
        QMessageBox.critical(None, 'No se pudo iniciar', str(exc))
        return 1
    window = JarvisWindow(brain, voice)
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
