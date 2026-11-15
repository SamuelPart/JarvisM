"""Interfaz de escritorio de JARVIS. Ejecutar con `python gui.py`."""
from __future__ import annotations
import json
import math
import os
import sqlite3
import sys
import threading
from datetime import datetime

from dotenv import load_dotenv
from PyQt6.QtCore import QObject, QThread, Qt, QTimer, QPointF, QDateTime, QUrl, QPropertyAnimation, QEasingCurve, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QDesktopServices, QFont, QColor, QPainter
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox,
                             QComboBox, QDateTimeEdit, QFormLayout, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                             QMainWindow, QMessageBox, QPushButton, QPlainTextEdit,
                             QScrollArea, QVBoxLayout, QWidget)

from provider import create_brain
from errors import describe_error
from main import ROOT, STATE
from system_control import SystemController
from voice import Voice
from voice_session import VoiceSession
from microphone import listen
from core_state import CoreState
from face_particles import face_points, ambient_points, motion
from agenda import Agenda
from approval import is_approved
from permissions import read_state, set_network_permission, set_gmail_permission
from text_links import markup, speech_text
from ui_settings import DEFAULTS, OPTIONS, PALETTES, SCALES, load as load_ui, save as save_ui

UI_SETTINGS_PATH = ROOT / '.jarvis-ui.json'


class VoiceSignals(QObject):
    activity = pyqtSignal(bool)


class CoreAnimation(QWidget):
    """A free-standing expressive face formed from animated particles."""
    def __init__(self, preferences):
        super().__init__()
        self.preferences = preferences.copy()
        scale = SCALES[self.preferences['size']]
        self.setFixedSize(round(300 * scale), round(260 * scale))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.mode = 'idle'
        self.phase = 0.0
        self.face = face_points()
        self.ambient = ambient_points()
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.advance)
        self.set_mode('idle')

    def set_mode(self, mode):
        self.mode = mode
        if self.preferences['animation'] != 'desactivada':
            self.timer.start()
        else:
            self.timer.stop()
        self.update()

    def configure(self, preferences):
        self.preferences = preferences.copy()
        scale = SCALES[self.preferences['size']]
        self.setFixedSize(round(300 * scale), round(260 * scale))
        self.set_mode(self.mode)

    def advance(self):
        self.phase += 0.018 if self.preferences['animation'] == 'reducida' else 0.045
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        scale = SCALES[self.preferences['size']]
        painter.scale(scale, scale)
        painter.setPen(Qt.PenStyle.NoPen)
        m = motion(self.phase, self.mode, self.preferences['animation'])
        _, accent = PALETTES[self.preferences['color']]
        # The pale points retain the photographic reference; palette colors tint them subtly.
        color = (255, 199, 117) if self.mode == 'approval' else tuple(int(220 + c * 0.13) for c in accent)

        def dot(x, y, size, alpha, tint=color):
            painter.setBrush(QColor(*tint, max(0, min(255, int(alpha)))))
            painter.drawEllipse(QPointF(x, y), size, size)

        for x, y, light, offset, size in self.ambient:
            flicker = 0.8 + 0.2 * math.sin(self.phase * 0.8 + offset)
            dot(x + m['sway'] * 0.4, y, size * 0.8, 95 * light * flicker)
        energy = 1.0 if self.mode != 'speaking' else 1.0 + 0.035 * math.sin(self.phase * 3.1)
        for x, y, light, offset, size in self.face:
            drift = 0.0
            if self.preferences['animation'] != 'desactivada':
                drift = (0.7 if self.mode == 'speaking' else 0.25) * math.sin(self.phase * 1.6 + offset)
            px = x * energy + m['sway'] + drift
            py = y + drift * 0.45
            dot(px, py, size * 0.65, 62 + 168 * light)

        # Dotted eyebrows, eye contours and pupils; a periodic blink closes both eyes.
        for side in (-1, 1):
            center = side * 29 + m['sway']
            for i in range(29):
                t = i / 28 * 2 - 1
                brow_y = -41 - 4 * (1 - t * t) + m['brow'] + side * t * (2 if self.mode == 'approval' else 0)
                dot(center + t * 18, brow_y, 0.75, 210)
                arch = math.sqrt(max(0.0, 1 - t * t)) * 6 * m['blink']
                dot(center + t * 16, -25 - arch, 0.65, 230)
                dot(center + t * 16, -25 + arch * 0.72, 0.6, 190)
            for i in range(15):
                angle = math.tau * i / 15
                dot(center + 3.5 * math.cos(angle), -25 + 3.5 * math.sin(angle) * m['blink'], 0.7, 235)

        # Nose bridge and nostrils remain defined even as the mouth moves.
        for i in range(26):
            t = i / 25
            dot(m['sway'] + 4 * math.sin(t * 3), -20 + t * 48, 0.6, 125 + 75 * t)
        for side in (-1, 1):
            for i in range(12):
                t = i / 11
                dot(m['sway'] + side * (4 + t * 9), 27 + 2 * math.sin(t * math.pi), 0.65, 200)

        for i in range(45):
            t = i / 44 * 2 - 1
            curve = math.sqrt(max(0.0, 1 - t * t))
            x = m['sway'] + t * 23
            dot(x, 51 - curve * (2 + m['mouth'] * 0.35), 0.7, 235)
            dot(x, 51 + curve * m['mouth'], 0.72, 215)
        painter.end()


class ChatMessage(QFrame):
    """A selectable, plain-text message with a short fade-in."""
    def __init__(self, author, text, parent=None):
        super().__init__(parent)
        kind = 'user' if author == 'Tú' else 'system' if author == 'Sistema' else 'jarvis'
        self.setObjectName('bubble_' + kind)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 13)
        layout.setSpacing(6)
        label = QLabel({'user': '●  TÚ', 'jarvis': '✦  JARVIS', 'system': '●  SISTEMA'}[kind])
        label.setObjectName('sender_' + kind)
        layout.addWidget(label)
        body = QLabel()
        body.setObjectName('messageText')
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse)
        body.setOpenExternalLinks(False)
        body.linkActivated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        body.setWordWrap(True)
        body.setText(markup(text))
        layout.addWidget(body)
        self.opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity)
        self.animation = QPropertyAnimation(self.opacity, b'opacity', self)
        self.animation.setDuration(260)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.start()


class ChatHistory(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setObjectName('chatHistory')
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        container.setObjectName('chatContainer')
        self.messages = QVBoxLayout(container)
        self.messages.setContentsMargins(8, 10, 8, 10)
        self.messages.setSpacing(10)
        self.messages.addStretch(1)
        self.setWidget(container)

    def add_message(self, author, text):
        # Only escaped text and explicitly recognized HTTP(S) links are rendered.
        bubble = ChatMessage(author, text)
        self.messages.insertWidget(self.messages.count() - 1, bubble)
        QTimer.singleShot(0, self.scroll_to_bottom)

    def clear_messages(self):
        while self.messages.count() > 1:
            item = self.messages.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def scroll_to_bottom(self):
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())


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


class VisualSettingsDialog(QDialog):
    def __init__(self, preferences, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Ajustes visuales')
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        title = QLabel('Personaliza el núcleo')
        title.setObjectName('dialogTitle')
        layout.addWidget(title)
        info = QLabel('El color ámbar se reserva para solicitudes de autorización.')
        info.setWordWrap(True)
        layout.addWidget(info)
        form = QFormLayout()
        self.fields = {}
        for key, label in (('color', 'Color'), ('size', 'Tamaño'), ('animation', 'Animación')):
            combo = QComboBox()
            for value in OPTIONS[key]:
                combo.addItem(value.capitalize(), value)
            combo.setCurrentIndex(combo.findData(preferences[key]))
            form.addRow(label, combo)
            self.fields[key] = combo
        layout.addLayout(form)
        self.network_permission = QCheckBox('Permitir búsquedas y música sin preguntar cada vez')
        self.network_permission.setChecked(read_state().get('network_actions_accepted') is True)
        self.network_permission.setToolTip('Las búsquedas y la música usan servicios externos; las acciones críticas siguen pidiendo permiso.')
        layout.addWidget(self.network_permission)
        self.gmail_permission = QCheckBox('Permitir Gmail sin preguntar cada vez')
        self.gmail_permission.setChecked(read_state().get('gmail_actions_accepted') is True)
        self.gmail_permission.setToolTip('Incluye leer, enviar y marcar mensajes importantes o spam. Puede haber errores y correos maliciosos. Las imágenes siguen requiriendo autorización.')
        layout.addWidget(self.gmail_permission)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('Guardar')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Cancelar')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        return {key: combo.currentData() for key, combo in self.fields.items()}


class MemoryDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle('Memoria de JARVIS')
        self.resize(540, 410)
        layout = QVBoxLayout(self)
        title = QLabel('Memoria y preferencias')
        title.setObjectName('dialogTitle')
        layout.addWidget(title)
        info = QLabel('Se guardan las conversaciones completadas en este equipo. Las últimas intervenciones y estas preferencias se envían al proveedor de IA. No guardes contraseñas ni claves aquí.')
        info.setWordWrap(True)
        layout.addWidget(info)
        layout.addWidget(QLabel('Preferencias que quieres que JARVIS recuerde:'))
        self.profile = QPlainTextEdit()
        self.profile.setPlaceholderText('Por ejemplo: Prefiero respuestas breves en español.')
        self.profile.setPlainText(window.brain.memory.get_preferences())
        layout.addWidget(self.profile)
        delete = QPushButton('Borrar conversaciones y preferencias')
        delete.clicked.connect(self.clear_memory)
        layout.addWidget(delete)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('Guardar preferencias')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Cerrar')
        buttons.accepted.connect(self.save_preferences)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save_preferences(self):
        try:
            self.window.brain.memory.set_preferences(self.profile.toPlainText())
        except (ValueError, sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, 'Memoria', 'No se pudieron guardar las preferencias. Máximo: 2000 caracteres.')
            return
        self.accept()

    def clear_memory(self):
        result = QMessageBox.question(self, 'Borrar memoria',
            '¿Borrar todas las conversaciones y preferencias guardadas en este equipo? Los ajustes visuales y las claves no se borrarán.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            self.window.brain.clear_memory()
        except (sqlite3.Error, OSError):
            QMessageBox.warning(self, 'Memoria', 'No se pudo borrar la memoria local.')
            return
        self.profile.clear()
        self.window.history.clear_messages()
        QMessageBox.information(self, 'Memoria', 'Conversaciones y preferencias borradas de la memoria local.')


class AgendaDialog(QDialog):
    def __init__(self, agenda, parent=None):
        super().__init__(parent)
        self.agenda = agenda
        self.setWindowTitle('Agenda y recordatorios')
        self.resize(580, 440)
        layout = QVBoxLayout(self)
        heading = QLabel('Agenda')
        heading.setObjectName('dialogTitle')
        layout.addWidget(heading)
        note = QLabel('Avisos locales únicos. JARVIS debe estar abierto para avisar a tiempo; si estuvo cerrado, avisará al volver a abrirlo.')
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.title = QLineEdit()
        self.title.setMaxLength(300)
        self.title.setPlaceholderText('Ejemplo: llamar a mamá')
        self.when = QDateTimeEdit(QDateTime.currentDateTime().addSecs(120))
        self.when.setDisplayFormat('dd/MM/yyyy HH:mm')
        self.when.setCalendarPopup(True)
        form.addRow('Recordatorio', self.title)
        form.addRow('Fecha y hora local', self.when)
        layout.addLayout(form)
        add = QPushButton('Guardar recordatorio')
        add.clicked.connect(self.add_reminder)
        layout.addWidget(add)
        self.items = QListWidget()
        layout.addWidget(self.items, 1)
        row = QHBoxLayout()
        delete = QPushButton('Eliminar seleccionado')
        delete.clicked.connect(self.delete_selected)
        close = QPushButton('Cerrar')
        close.clicked.connect(self.accept)
        row.addWidget(delete)
        row.addStretch()
        row.addWidget(close)
        layout.addLayout(row)
        self.refresh()

    def refresh(self):
        self.items.clear()
        for reminder in self.agenda.list():
            when = datetime.fromtimestamp(reminder['due']).astimezone().strftime('%d/%m/%Y %H:%M')
            status = 'Avisado' if reminder['notified'] else 'Pendiente'
            item = QListWidgetItem(f"{when}  ·  {status}  ·  {reminder['title']}")
            item.setData(Qt.ItemDataRole.UserRole, reminder['id'])
            self.items.addItem(item)

    def add_reminder(self):
        try:
            self.agenda.add(self.title.text(), self.when.dateTime().toSecsSinceEpoch())
            self.title.clear()
            self.refresh()
        except ValueError as exc:
            QMessageBox.warning(self, 'Agenda', str(exc))
        except (sqlite3.Error, OSError):
            QMessageBox.warning(self, 'Agenda', 'No se pudo guardar el recordatorio.')

    def delete_selected(self):
        item = self.items.currentItem()
        if item is None:
            return
        if QMessageBox.question(self, 'Eliminar recordatorio', '¿Eliminar el recordatorio seleccionado?',
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.agenda.delete(item.data(Qt.ItemDataRole.UserRole))
            self.refresh()
        except (sqlite3.Error, OSError):
            QMessageBox.warning(self, 'Agenda', 'No se pudo eliminar el recordatorio.')


class JarvisWindow(QMainWindow):
    def __init__(self, brain, voice):
        super().__init__()
        self.brain, self.voice = brain, voice
        self.agenda = Agenda()
        self.reminder_windows = {}
        self.preferences = load_ui(UI_SETTINGS_PATH)
        self.thread = None
        self.worker = None
        self.approval_pending = False
        self.compact = False
        self.expanded_geometry = None
        self.expanded_maximized = False
        self.setWindowTitle('JARVIS')
        self.resize(860, 800)
        self.setMinimumSize(560, 520)
        self.setStyleSheet(STYLE)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        self.root_layout = layout
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
        self.agenda_button = QPushButton('Agenda')
        self.agenda_button.clicked.connect(self.open_agenda)
        top.addWidget(self.agenda_button)
        self.memory_button = QPushButton('Memoria')
        self.memory_button.clicked.connect(self.open_memory)
        top.addWidget(self.memory_button)
        self.settings_button = QPushButton('Ajustes')
        self.settings_button.clicked.connect(self.open_visual_settings)
        top.addWidget(self.settings_button)
        self.compact_toggle = QPushButton('Modo compacto')
        self.compact_toggle.clicked.connect(self.toggle_compact)
        top.addWidget(self.compact_toggle)
        layout.addLayout(top)

        self.heading = QLabel('Tu asistente, listo para ayudarte.')
        self.heading.setObjectName('heading')
        layout.addWidget(self.heading)
        self.subtitle = QLabel('Conversa, consulta y controla tu equipo con tu autorización.')
        self.subtitle.setObjectName('muted')
        layout.addWidget(self.subtitle)

        self.core = CoreAnimation(self.preferences)
        layout.addWidget(self.core, 0, Qt.AlignmentFlag.AlignHCenter)
        self.voice_signals = VoiceSignals(self)
        self.core_state = CoreState()
        self.voice_signals.activity.connect(self.on_voice_activity)
        self.voice.on_activity = self.voice_signals.activity.emit

        self.status = QLabel('Micrófono apagado')
        self.status.setObjectName('statusBadge')
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status)
        controls = QHBoxLayout()
        controls.addStretch()
        self.chat_toggle = QPushButton('💬')
        self.chat_toggle.setObjectName('modeIcon')
        self.chat_toggle.setCheckable(True)
        self.chat_toggle.setToolTip('Mostrar u ocultar chat')
        self.chat_toggle.setAccessibleName('Mostrar u ocultar chat')
        self.chat_toggle.toggled.connect(self.toggle_chat)
        controls.addWidget(self.chat_toggle)
        self.mic = QPushButton('🎙')
        self.mic.setObjectName('modeIcon')
        self.mic.setCheckable(True)
        self.mic.setToolTip('Activar micrófono')
        self.mic.setAccessibleName('Activar o apagar micrófono')
        self.mic.clicked.connect(self.toggle_microphone)
        controls.addWidget(self.mic)
        controls.addStretch()
        layout.addLayout(controls)

        self.chat_panel = QWidget()
        chat_layout = QVBoxLayout(self.chat_panel)
        self.history = ChatHistory()
        for message in self.brain.memory.recent():
            self.history.add_message('Tú' if message['role'] == 'user' else 'JARVIS', message['content'])
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
        self.chat_panel.hide()
        layout.addWidget(self.chat_panel, 1)
        self.agenda_timer = QTimer(self)
        self.agenda_timer.setInterval(5000)
        self.agenda_timer.timeout.connect(self.check_reminders)
        self.agenda_timer.start()
        QTimer.singleShot(0, self.check_reminders)

    @pyqtSlot(bool)
    def toggle_chat(self, enabled):
        if enabled and self.compact:
            self.toggle_compact()
        self.chat_panel.setVisible(enabled and not self.compact)
        if enabled and not self.compact:
            self.input.setFocus()

    def append_chat(self, author, text):
        self.history.add_message(author, text)

    def submit_chat(self):
        text = self.input.text().strip()
        if not text:
            return
        if self.approval_pending:
            self.input.clear()
            self.approval_pending = False
            approved = is_approved(text)
            self.append_chat('Tú', text)
            self.append_chat('Sistema', 'Acción autorizada.' if approved else 'Acción rechazada.')
            self.input.setPlaceholderText('Escribe tu mensaje…')
            self.send.setEnabled(False)
            self.set_task_state('thinking')
            self.status.setText('JARVIS está trabajando…')
            self.worker.resolve_approval(approved)
            return
        if self.thread is not None:
            return
        self.input.clear()
        self.append_chat('Tú', text)
        self.set_task_state('thinking')
        self.status.setText('JARVIS está pensando…')
        self.send.setEnabled(False)
        self.mic.setEnabled(False)
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
        self.status.setText('Esperando tu autorización en el chat…')
        self.approval_pending = True
        privacy = ('\nSe capturará la pantalla completa y se enviará a NVIDIA; la descripción puede enviarse al proveedor del chat.'
                   if name == 'inspect_screen' else '\nLa imagen se enviará a NVIDIA; su descripción puede enviarse al proveedor del chat.'
                   if name == 'inspect_image' else '\nSe buscarán correos en Gmail y sus metadatos pueden enviarse al proveedor del chat.'
                   if name == 'search_gmail' else '\nSe descargará el adjunto de Gmail y se enviará a NVIDIA; su descripción puede enviarse al proveedor del chat.'
                   if name == 'inspect_gmail_image' else ' El contenido del correo se enviará al proveedor del chat.'
                   if name == 'read_gmail' else ' Se enviará el correo completo al destinatario indicado.'
                   if name in ('send_gmail', 'reply_gmail') else ' Se modificará la clasificación de este correo en Gmail.'
                   if name == 'classify_gmail' else ' Se consultará tu agenda y los datos pueden enviarse al proveedor del chat.'
                   if name in ('list_calendar_events', 'list_reminders') else '')
        details = json.dumps(args, ensure_ascii=False, indent=2, default=str)
        self.append_chat('Sistema', 'Permiso solicitado para: ' + name + '\n' + details + privacy +
                         '\nEscribe AUTORIZO para aprobar o NO para rechazar.')
        if self.compact:
            self.toggle_compact()
        self.chat_toggle.setChecked(True)
        self.chat_panel.show()
        self.input.setPlaceholderText('Responde AUTORIZO o NO')
        self.input.setEnabled(True)
        self.send.setEnabled(True)
        self.input.setFocus()

    @pyqtSlot(str)
    def chat_result(self, text):
        self.set_task_state('idle')
        self.append_chat('JARVIS', text)
        if self.chat_audio.isChecked():
            self.voice.speak(speech_text(text))

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

    def open_agenda(self):
        try:
            AgendaDialog(self.agenda, self).exec()
        except (sqlite3.Error, OSError):
            QMessageBox.warning(self, 'Agenda', 'No se pudo abrir la agenda local.')

    @pyqtSlot()
    def check_reminders(self):
        try:
            reminders = self.agenda.claim_due()
        except (sqlite3.Error, OSError):
            self.status.setText('No se pudo consultar la agenda local')
            return
        for reminder in reminders:
            title = reminder['title']
            box = QMessageBox(self)
            box.setWindowTitle('Recordatorio de JARVIS')
            box.setTextFormat(Qt.TextFormat.PlainText)
            box.setText(title)
            box.setInformativeText('Aviso de tu agenda local')
            box.setStandardButtons(QMessageBox.StandardButton.Ok)
            box.setWindowModality(Qt.WindowModality.NonModal)
            self.reminder_windows[reminder['id']] = box
            box.finished.connect(lambda _result, key=reminder['id']: self.reminder_windows.pop(key, None))
            box.show()
            # Never play a reminder into an active microphone/consent session.
            if not isinstance(self.worker, VoiceWorker):
                self.voice.speak('Señor, recordatorio: ' + title)

    def open_memory(self):
        if self.thread is not None:
            QMessageBox.information(self, 'Memoria', 'Detén el micrófono o espera a que termine la solicitud antes de modificar la memoria.')
            return
        try:
            MemoryDialog(self).exec()
        except (sqlite3.Error, OSError):
            QMessageBox.warning(self, 'Memoria', 'No se pudo abrir la memoria local.')

    def open_visual_settings(self):
        dialog = VisualSettingsDialog(self.preferences, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.preferences = save_ui(UI_SETTINGS_PATH, dialog.values())
            set_network_permission(dialog.network_permission.isChecked())
            set_gmail_permission(dialog.gmail_permission.isChecked())
        except OSError:
            QMessageBox.warning(self, 'Ajustes', 'No se pudieron guardar los ajustes visuales.')
            return
        self.core.configure(self.preferences)

    def toggle_pin(self, checked):
        # Compact mode remains floating; expanded mode respects the checkbox.
        geometry = self.geometry()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, checked or self.compact)
        self.show()
        self.setGeometry(geometry)

    def toggle_compact(self):
        if not self.compact:
            self.expanded_geometry = self.geometry()
            self.expanded_maximized = self.isMaximized()
            self.showNormal()
            self.compact = True
            self.settings_button.hide()
            self.memory_button.hide()
            self.agenda_button.hide()
            self.heading.hide()
            self.subtitle.hide()
            self.chat_toggle.setChecked(False)
            self.chat_panel.hide()
            self.compact_toggle.setText('Abrir chat')
            self.root_layout.setContentsMargins(10, 10, 10, 10)
            self.root_layout.setSpacing(6)
            self.setMinimumSize(320, 350)
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            self.show()
            self.resize(360, 390)
        else:
            self.compact = False
            self.settings_button.show()
            self.memory_button.show()
            self.agenda_button.show()
            self.heading.show()
            self.subtitle.show()
            self.chat_toggle.setChecked(True)
            self.chat_panel.show()
            self.compact_toggle.setText('Modo compacto')
            self.root_layout.setContentsMargins(30, 24, 30, 24)
            self.root_layout.setSpacing(18)
            self.setMinimumSize(560, 520)
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.pin.isChecked())
            self.show()
            if self.expanded_maximized:
                self.showMaximized()
            elif self.expanded_geometry is not None:
                self.setGeometry(self.expanded_geometry)

    def toggle_microphone(self):
        if self.thread is not None:
            if not isinstance(self.worker, VoiceWorker):
                return
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
        self.mic.setChecked(True)
        self.mic.setToolTip('Apagar micrófono')
        self.input.setEnabled(False)
        self.send.setEnabled(False)
        self.thread.start()

    @pyqtSlot()
    def cleanup(self):
        self.thread.deleteLater()
        self.thread = None
        self.worker = None
        self.approval_pending = False
        self.input.setPlaceholderText('Escribe tu mensaje…')
        self.set_task_state('idle')
        if not self.status.text().startswith('Error'):
            self.status.setText('Micrófono apagado')
        self.mic.setChecked(False)
        self.mic.setToolTip('Activar micrófono')
        self.mic.setEnabled(True)
        self.input.setEnabled(True)
        self.send.setEnabled(True)

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
QScrollArea#chatHistory { background: #0c1522; border: 1px solid #1e3548; border-radius: 14px; }
QWidget#chatContainer { background: transparent; }
QFrame#bubble_user { background-color: rgba(20, 57, 75, 210); border: 1px solid #28627a; border-left: 3px solid #5dd9ef; border-radius: 11px; }
QFrame#bubble_jarvis { background-color: rgba(22, 30, 52, 225); border: 1px solid #344269; border-left: 3px solid #8696ff; border-radius: 11px; }
QFrame#bubble_system { background-color: rgba(61, 42, 25, 220); border: 1px solid #765738; border-left: 3px solid #e6aa5c; border-radius: 11px; }
QLabel#sender_user { color: #80ddea; font-size: 10px; font-weight: 800; }
QLabel#sender_jarvis { color: #a8b2ff; font-size: 10px; font-weight: 800; }
QLabel#sender_system { color: #f0bd7c; font-size: 10px; font-weight: 800; }
QLabel#messageText { color: #edf4fa; font-size: 13px; background: transparent; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 4px; }
QScrollBar::handle:vertical { background: #34566b; min-height: 25px; border-radius: 3px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QPushButton { border: 1px solid #31475b; border-radius: 9px; padding: 10px 16px; background: #1c2b3b; }
QPushButton:hover { background: #294154; }
QPushButton#modeIcon { font-size: 22px; min-width: 40px; padding: 8px; }
QPushButton#modeIcon:checked { background: #186979; border: 1px solid #7fe4ee; }
QPushButton#modeIcon:disabled { color: #6c7d89; background: #1a2731; }
QPushButton#send, QPushButton#approveButton { background: #76d7e4; color: #07151d; border: none; font-weight: 700; }
QPushButton#send:disabled { background: #344957; color: #8296aa; }
QComboBox { background: #172838; color: #e4edf7; border: 1px solid #355266; border-radius: 7px; padding: 7px; }
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
    if not read_state().get('network_actions_asked'):
        answer = QMessageBox.question(None, 'Permiso para búsquedas y música',
            '¿Permites que JARVIS busque en Internet y reproduzca música sin preguntar cada vez? Las consultas se enviarán a servicios externos. Los comandos, archivos y demás acciones seguirán requiriendo autorización.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        try:
            set_network_permission(answer == QMessageBox.StandardButton.Yes)
        except OSError:
            QMessageBox.warning(None, 'Permisos', 'No se pudo guardar la preferencia. Se pedirá permiso para cada acción.')
    if not read_state().get('gmail_actions_asked'):
        answer = QMessageBox.question(None, 'Permiso permanente para Gmail',
            '¿Permites que JARVIS busque y lea correos, envíe mensajes y los marque como importantes o spam sin pedir permiso cada vez? Los mensajes pueden enviarse al proveedor del chat. JARVIS puede equivocarse o ser influido por contenido malicioso, y podría enviar o clasificar correos incorrectamente. Puedes desactivarlo en Ajustes. Las imágenes enviadas a NVIDIA seguirán requiriendo permiso.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        try:
            set_gmail_permission(answer == QMessageBox.StandardButton.Yes)
        except OSError:
            QMessageBox.warning(None, 'Permisos', 'No se pudo guardar el permiso de Gmail; se pedirá en cada acción.')
    try:
        controller = SystemController()
        brain = create_brain(controller, lambda *_: False)
    except (ValueError, RuntimeError) as exc:
        QMessageBox.critical(None, 'No se pudo iniciar', str(exc))
        return 1
    try:
        window = JarvisWindow(brain, voice)
    except (sqlite3.Error, OSError):
        QMessageBox.critical(None, 'JARVIS', 'No se pudo abrir la agenda o la memoria local.')
        return 1
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
