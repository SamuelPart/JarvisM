"""Interfaz de escritorio de JARVIS. Ejecutar con `python gui.py`."""
from __future__ import annotations
import json
import os
import sys
import threading

from dotenv import load_dotenv
from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox,
                             QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                             QPushButton, QPlainTextEdit, QTextBrowser, QVBoxLayout,
                             QWidget)

from brain import Brain
from main import ROOT, STATE
from system_control import SystemController
from voice import Voice


class AgentWorker(QObject):
    result = pyqtSignal(str)
    error = pyqtSignal(str)
    approval = pyqtSignal(str, object)
    finished = pyqtSignal()

    def __init__(self, brain, message):
        super().__init__()
        self.brain, self.message = brain, message
        self.answer_ready = threading.Event()
        self.approved = False

    def ask_approval(self, name, args):
        self.approved = False
        self.answer_ready.clear()
        self.approval.emit(name, args)
        self.answer_ready.wait()
        return self.approved

    def set_approval(self, approved):
        self.approved = approved
        self.answer_ready.set()

    @pyqtSlot()
    def run(self):
        try:
            self.brain.approve = self.ask_approval
            self.result.emit(self.brain.ask(self.message))
        except Exception as exc:
            # Avoid exposing secrets from provider exceptions.
            self.error.emit(f'No se pudo completar la solicitud ({type(exc).__name__}).')
        finally:
            self.finished.emit()


class ApprovalDialog(QDialog):
    def __init__(self, name, args, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Confirmar acción')
        self.resize(560, 390)
        layout = QVBoxLayout(self)
        title = QLabel('JARVIS solicita permiso')
        title.setObjectName('dialogTitle')
        layout.addWidget(title)
        info = QLabel('Revisa la herramienta y sus argumentos antes de autorizar. La acción se ejecutará con tus permisos.')
        info.setWordWrap(True)
        layout.addWidget(info)
        details = QPlainTextEdit()
        details.setReadOnly(True)
        details.setPlainText(name + '\n\n' + json.dumps(args, ensure_ascii=False, indent=2, default=str))
        layout.addWidget(details)
        buttons = QDialogButtonBox()
        reject = buttons.addButton('Rechazar', QDialogButtonBox.ButtonRole.RejectRole)
        accept = buttons.addButton('Autorizar esta acción', QDialogButtonBox.ButtonRole.AcceptRole)
        accept.setObjectName('approveButton')
        reject.clicked.connect(self.reject)
        accept.clicked.connect(self.accept)
        layout.addWidget(buttons)


class JarvisWindow(QMainWindow):
    def __init__(self, brain, voice):
        super().__init__()
        self.brain, self.voice = brain, voice
        self.thread = None
        self.worker = None
        self.setWindowTitle('JARVIS')
        self.resize(860, 690)
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

        panel = QFrame()
        panel.setObjectName('panel')
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(18, 16, 18, 16)
        bar = QHBoxLayout()
        status_label = QLabel('●  SISTEMA ACTIVO')
        status_label.setObjectName('statusBadge')
        bar.addWidget(status_label)
        bar.addStretch()
        model_label = QLabel(self.brain.model)
        model_label.setObjectName('model')
        bar.addWidget(model_label)
        panel_layout.addLayout(bar)
        self.history = QTextBrowser()
        self.history.setOpenExternalLinks(False)
        self.history.setPlaceholderText('La conversación aparecerá aquí…')
        panel_layout.addWidget(self.history, 1)
        layout.addWidget(panel, 1)

        self.status = QLabel('Listo para recibir instrucciones')
        self.status.setObjectName('muted')
        layout.addWidget(self.status)
        composer = QHBoxLayout()
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText('Escribe tu mensaje para JARVIS…')
        self.input.setMaximumHeight(100)
        self.input.setMinimumHeight(68)
        composer.addWidget(self.input, 1)
        self.send = QPushButton('Enviar  ↗')
        self.send.setObjectName('send')
        self.send.setMinimumHeight(68)
        self.send.clicked.connect(self.submit)
        composer.addWidget(self.send)
        layout.addLayout(composer)
        footer = QLabel('Las acciones sobre tu equipo requieren confirmación explícita.')
        footer.setObjectName('footer')
        layout.addWidget(footer)
        self.append_message('JARVIS', 'Activando protocolos de seguridad...')

    def append_message(self, author, text):
        # insertPlainText prevents HTML injection from model/user content.
        cursor = self.history.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        if not self.history.document().isEmpty():
            cursor.insertText('\n\n')
        cursor.insertText(author.upper() + '\n' + text)
        self.history.setTextCursor(cursor)
        self.history.ensureCursorVisible()

    def toggle_pin(self, checked):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, checked)
        self.show()

    def submit(self):
        message = self.input.toPlainText().strip()
        if not message or self.thread is not None:
            return
        self.input.clear()
        self.append_message('Tú', message)
        self.status.setText('JARVIS está pensando…')
        self.send.setEnabled(False)
        self.thread = QThread(self)
        self.worker = AgentWorker(self.brain, message)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.approval.connect(self.request_approval)
        self.worker.result.connect(self.on_result)
        self.worker.error.connect(self.on_error)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.cleanup)
        self.thread.start()

    @pyqtSlot(str, object)
    def request_approval(self, name, args):
        self.status.setText('Esperando tu autorización…')
        accepted = ApprovalDialog(name, args, self).exec() == QDialog.DialogCode.Accepted
        self.worker.set_approval(accepted)
        self.status.setText('JARVIS está trabajando…')

    @pyqtSlot(str)
    def on_result(self, text):
        self.append_message('JARVIS', text)
        self.voice.speak(text)

    @pyqtSlot(str)
    def on_error(self, error):
        self.append_message('Sistema', error)

    @pyqtSlot()
    def cleanup(self):
        self.thread.deleteLater()
        self.thread = None
        self.worker = None
        self.status.setText('Listo para recibir instrucciones')
        self.send.setEnabled(True)

    def closeEvent(self, event):
        if self.thread is not None:
            QMessageBox.information(self, 'JARVIS está trabajando', 'Espera a que termine la solicitud antes de cerrar la ventana.')
            event.ignore()
        else:
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
