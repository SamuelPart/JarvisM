"""Interfaz de escritorio de JARVIS. Ejecutar con `python gui.py`."""
from __future__ import annotations
import json
import math
import os
import sqlite3
import sys
import threading
import tempfile
import time
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from PyQt6.QtCore import QObject, QThread, Qt, QTimer, QPointF, QRectF, QDateTime, QUrl, QPropertyAnimation, QEasingCurve, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QDesktopServices, QFont, QColor, QPixmap, QPainter, QRadialGradient, QPainterPath, QPen
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
from agenda import Agenda
from approval import is_approved
import startup_briefing
import scheduled_emails
from weather_view import WeatherView
from weather_timing import WeatherLoadingTiming
from weather_sound import write_search_cue
from orb_motion import approach
from permissions import read_state, set_network_permission, set_gmail_permission, set_agenda_permission, set_briefing_permission, set_automation_permission, set_agenda_delete_permission, set_scheduled_email_permission, set_phone_permission
from text_links import markup, speech_text
from ui_settings import DEFAULTS, OPTIONS, PALETTES, SCALES, load as load_ui, save as save_ui

UI_SETTINGS_PATH = ROOT / '.jarvis-ui.json'


class VoiceSignals(QObject):
    activity = pyqtSignal(bool)
    voice_level = pyqtSignal(object)
    briefing_ready = pyqtSignal(str)
    scheduled_email_result = pyqtSignal(object)
    weather_event = pyqtSignal(str, object)
    weather_refresh = pyqtSignal(int, object)


class CoreAnimation(QWidget):
    """Classic dotted JARVIS core, animated continuously."""
    def __init__(self, preferences):
        super().__init__()
        self.preferences = preferences.copy()
        self.compact_display = False
        self.display_scale = 1.0
        self.weather_searching = False
        scale = SCALES[self.preferences['size']]
        self.setFixedSize(round(300 * scale), round(260 * scale))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.mode = 'idle'
        self.variant = 0
        self.visual_variant = 0.0
        self.phase = 0.0
        self.last_frame = time.monotonic()
        self.think_mix = 0.0
        self.speak_mix = 0.0
        self.approval_mix = 0.0
        self.voice_level = None
        self.smoothed_level = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.advance)
        self.timer.start()

    def set_mode(self, mode):
        if mode != self.mode and mode in ('thinking', 'speaking'):
            self.variant = (self.variant + 1) % 3
        self.mode = mode
        self.update()

    def configure(self, preferences):
        self.preferences = preferences.copy()
        self.set_compact_display(self.compact_display)
        self.set_mode(self.mode)

    def set_voice_level(self, level):
        self.voice_level = max(0.0, min(1.0, float(level))) if isinstance(level, (int, float)) and math.isfinite(level) else None

    def set_weather_searching(self, searching):
        self.weather_searching = searching
        self.update()

    def set_compact_display(self, compact):
        self.compact_display = compact
        # The timer eases the size, so the sphere doesn't shrink in one frame.
        self.update()

    def advance(self):
        speed = 0.09 if self.weather_searching else 0.075 if self.mode == 'speaking' else 0.045 if self.mode == 'thinking' else 0.025
        now = time.monotonic()
        elapsed = max(0.0, min(now - self.last_frame, .15))
        self.last_frame = now
        self.phase += speed * elapsed / .04 * (0.45 if self.preferences['animation'] == 'reducida' else 1.0)
        self.visual_variant = approach(self.visual_variant, self.variant, elapsed, .5)
        target_scale = .38 if self.compact_display else 1.0
        self.display_scale = approach(self.display_scale, target_scale, elapsed, .23)
        if abs(target_scale - self.display_scale) < .002:
            self.display_scale = target_scale
        size = SCALES[self.preferences['size']] * self.display_scale
        new_width, new_height = round(300 * size), round(260 * size)
        if self.width() != new_width or self.height() != new_height:
            self.setFixedSize(new_width, new_height)
        # Blend state changes instead of snapping between two unrelated shapes.
        thinking = (self.weather_searching or self.mode == 'thinking') and self.mode != 'approval'
        self.think_mix = approach(self.think_mix, 1.0 if thinking else 0.0, elapsed, .26)
        self.speak_mix = approach(self.speak_mix, 1.0 if self.mode == 'speaking' and not thinking else 0.0, elapsed, .26)
        self.approval_mix = approach(self.approval_mix, 1.0 if self.mode == 'approval' else 0.0, elapsed, .18)
        target = self.voice_level if self.voice_level is not None else .35 + .2 * math.sin(self.phase * 2.1)
        self.smoothed_level = approach(self.smoothed_level, target, elapsed, .06 if target > self.smoothed_level else .11)
        self.update()

    def paint_thought_streams(self, painter, radius, opacity):
        reduced = self.preferences['animation'] == 'reducida'
        for layer in range(4):
            angle = layer * .72 + self.phase * (.18 + layer * .025)
            spread = radius * (.48 + layer * .10)
            path = QPainterPath()
            # Project differently tilted elliptical paths into the core.
            for step in range(41):
                t = step * math.tau / 40
                u = math.cos(t) * spread
                v = math.sin(t) * spread * (.26 + layer * .065)
                x = u * math.cos(angle) - v * math.sin(angle)
                y = u * math.sin(angle) + v * math.cos(angle)
                if not step:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(76, 191, 255, int((18 if reduced else 34) * opacity)), .8))
            painter.drawPath(path)
            position = (self.phase * (1.2 + layer * .18) + layer * 1.7) % math.tau
            u = math.cos(position) * spread
            v = math.sin(position) * spread * (.26 + layer * .065)
            x, y = u * math.cos(angle) - v * math.sin(angle), u * math.sin(angle) + v * math.cos(angle)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(117, 226, 255, int((90 if reduced else 160) * opacity)))
            painter.drawEllipse(QPointF(x, y), 2.1, 2.1)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        scale = SCALES[self.preferences['size']] * self.display_scale
        painter.scale(scale, scale)
        radius = 100.0
        # A dark, transparent glow rather than a rectangular background.
        glow = QRadialGradient(QPointF(0, 0), radius * 1.12)
        amber = self.approval_mix
        glow.setColorAt(0, QColor(round(20 + 110 * amber), round(16 + 49 * amber), round(100 - 96 * amber), 18 + round(4 * amber)))
        glow.setColorAt(0.76, QColor(round(28 + 202 * amber), round(28 + 102 * amber), round(174 - 156 * amber), 28 + round(10 * amber)))
        glow.setColorAt(1, QColor(round(12 + 78 * amber), round(10 + 35 * amber), round(85 - 85 * amber), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(0, 0), radius * 1.12, radius * 1.12)

        # Thin, asymmetric internal channels carry traveling light pulses.
        # They fade in with thought and remain inside the existing point sphere.
        if self.think_mix > .01:
            self.paint_thought_streams(painter, radius, self.think_mix)

        # Latitude rings projected in 3D: points on both hemispheres make the
        # hologram look like the reference, including its dotted polar circles.
        tilt = 0.22
        points = []
        reduced = self.preferences['animation'] == 'reducida'
        strength = .4 if reduced else 1.0
        variant = self.visual_variant
        thinking = self.think_mix
        speaking = self.speak_mix
        stretch = 1 + strength * (thinking * (0.11 + variant * .025) * math.sin(self.phase * (.7 + variant * .22))
                                  + speaking * .035 * self.smoothed_level * math.sin(self.phase * (1.4 + variant * .25)))
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
                pulse += strength * thinking * (0.10 * math.sin(self.phase * (1.7 + variant * .3) + theta * (3 + variant) + angle * 2)
                                               + .035 * math.sin(angle * (3 + variant) - self.phase * 2.3))
                # Edge playback drives this from actual audio RMS; local speech
                # falls back to a gentle procedural movement when unavailable.
                pulse += strength * speaking * self.smoothed_level * (0.15 + .055 * math.sin(theta * (6 + variant) + self.phase * 3 + angle * (2 + variant)))
                px, py = radius * x * pulse * stretch, -radius * screen_y * pulse / stretch
                # Narrow luminous currents sweep across the particle layers.
                current = max(0.0, math.sin(angle * 2 + theta * 3 - self.phase * 2.6)) ** 5
                alpha = min(255, int(95 + 100 * (z + 1) / 2 + thinking * current * 60
                                     + speaking * self.smoothed_level * 35))
                dot = 0.65 + 0.35 * (z + 1) / 2 + thinking * current * .35
                points.append((z, px, py, dot, alpha))

        # Smoothly interpolate the palette alongside the deformation.
        def blend(a, b, amount):
            return tuple(round(x + (y - x) * max(0.0, min(1.0, amount))) for x, y in zip(a, b))
        dim_color, bright_color = PALETTES[self.preferences['color']]
        for palette, amount in ((PALETTES['violeta'], thinking), (PALETTES['cian'], speaking),
                                (((255, 140, 32), (255, 195, 100)), self.approval_mix)):
            dim_color, bright_color = blend(dim_color, palette[0], amount), blend(bright_color, palette[1], amount)
        for _, x, y, dot, alpha in sorted(points):
            painter.setBrush(QColor(*dim_color, max(20, alpha // 5)))
            painter.drawEllipse(QPointF(x, y), dot * 2.3, dot * 2.3)
            painter.setBrush(QColor(*bright_color, alpha))
            painter.drawEllipse(QPointF(x, y), dot, dot)
        if thinking > .02:
            # Moving sparks and brief highlights emerge from the same dots.
            for i in range(10):
                angle = i * math.tau / 10 + self.phase * .38
                intensity = max(0.0, math.sin(self.phase * 2.2 + i * 2.0)) ** 6
                if intensity < .08:
                    continue
                distance = 74 + 30 * math.sin(i * 2.2 + self.phase * .4)
                x, y = distance * math.cos(angle), distance * math.sin(angle) * .78
                reduced = self.preferences['animation'] == 'reducida'
                size = 3 + intensity * (4 if reduced else 10)
                painter.setPen(QPen(QColor(163, 245, 255, int((85 if reduced else 210) * intensity * thinking)), 1.4))
                painter.drawLine(QPointF(x - size, y), QPointF(x + size, y))
                painter.drawLine(QPointF(x, y - size), QPointF(x, y + size))
            painter.setPen(Qt.PenStyle.NoPen)
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
    conversation_changed = pyqtSignal(bool)
    finished = pyqtSignal()

    def __init__(self, brain, voice, conversation_changed=True):
        super().__init__()
        callback = self.conversation_changed.emit if conversation_changed else None
        self.session = VoiceSession(brain, voice, listen, self.status.emit, conversation_changed=callback)

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
    def __init__(self, preferences, conversation_enabled=False, parent=None):
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
        for key, label in (('color', 'Color'), ('size', 'Tamaño'), ('animation', 'Animación'), ('weather_sound', 'Sonidos tecnológicos al pensar')):
            combo = QComboBox()
            for value in OPTIONS[key]:
                combo.addItem(value.capitalize(), value)
            combo.setCurrentIndex(combo.findData(preferences[key]))
            form.addRow(label, combo)
            self.fields[key] = combo
        layout.addLayout(form)
        self.conversation_live = QCheckBox('Conversación libre (no decir «Jarvis»)')
        self.conversation_live.setChecked(conversation_enabled)
        self.conversation_live.setToolTip('Solo para esta ejecución del programa; no se guarda al cerrarlo. Con el micrófono encendido es como si hubieras dicho «Jarvis»: todo lo que escuche será una orden hasta que digas «eso es todo», desmarques la casilla o apagues el micrófono. No actives esto si hay otras personas hablando cerca.')
        layout.addWidget(self.conversation_live)
        self.automation_permission = QCheckBox('Automatización amplia y actualizaciones al iniciar')
        self.automation_permission.setChecked(read_state().get('automation_accepted') is True)
        self.automation_permission.setToolTip('Permite abrir aplicaciones y sitios, crear recordatorios y leer, crear, modificar o mover archivos sin preguntar. Activa actualizaciones automáticas de código. Shell, control de pantalla e imágenes requieren permiso aparte. Desactivar esta opción no revoca Gmail, búsquedas, agenda ni resumen: cambia también esas casillas abajo.')
        layout.addWidget(self.automation_permission)
        self.network_permission = QCheckBox('Permitir búsquedas, clima y música sin preguntar cada vez')
        self.network_permission.setChecked(read_state().get('network_actions_accepted') is True)
        self.network_permission.setToolTip('Las búsquedas, el clima y la música usan servicios externos; las acciones críticas siguen pidiendo permiso.')
        layout.addWidget(self.network_permission)
        self.gmail_permission = QCheckBox('Permitir Gmail sin preguntar cada vez')
        self.gmail_permission.setChecked(read_state().get('gmail_actions_accepted') is True)
        self.gmail_permission.setToolTip('Incluye leer, enviar y marcar mensajes importantes o spam. Puede haber errores y correos maliciosos. Las imágenes siguen requiriendo autorización.')
        layout.addWidget(self.gmail_permission)
        self.agenda_permission = QCheckBox('Consultar agenda y calendario sin preguntar cada vez')
        self.agenda_permission.setChecked(read_state().get('agenda_read_accepted') is True)
        self.agenda_permission.setToolTip('Incluye hora, recordatorios y eventos de Google Calendar. Los datos pueden enviarse al proveedor de IA; crear recordatorios requiere permiso aparte.')
        layout.addWidget(self.agenda_permission)
        self.scheduled_email_permission = QCheckBox('Permitir programar y enviar correos sin preguntar cada vez')
        self.scheduled_email_permission.setChecked(read_state().get('scheduled_email_accepted') is True)
        self.scheduled_email_permission.setToolTip('Guarda destinatario, asunto, mensaje y fecha localmente. Al llegar la fecha JARVIS intenta enviarlos por Gmail si está abierto y conectado; si estuvo cerrado, lo intenta al abrir. Revocar pausa los pendientes; no interrumpe un envío ya iniciado. Errores o contenido malicioso pueden provocar envíos no deseados.')
        layout.addWidget(self.scheduled_email_permission)
        self.agenda_delete_permission = QCheckBox('Eliminar recordatorios locales sin preguntar cada vez')
        self.agenda_delete_permission.setChecked(read_state().get('agenda_delete_accepted') is True)
        self.agenda_delete_permission.setToolTip('Permite eliminar recordatorios locales al pedirlo. No elimina eventos de Google Calendar.')
        layout.addWidget(self.agenda_delete_permission)
        self.briefing_permission = QCheckBox('Resumen automático al iniciar')
        self.briefing_permission.setChecked(read_state().get('startup_briefing_accepted') is True)
        self.briefing_permission.setToolTip('Consulta recordatorios, calendario configurado, estado del equipo y cantidad de errores recientes en los registros. La voz puede enviarse a un servicio externo; los detalles de registros solicitados pueden enviarse al proveedor de IA.')
        layout.addWidget(self.briefing_permission)
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


class PhoneWorker(QThread):
    outcome = pyqtSignal(object)

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.outcome.emit(self.operation())
        except Exception as exc:
            from android_phone import PhoneError
            self.outcome.emit({'error': str(exc) if isinstance(exc, PhoneError) else 'No se pudo completar la operación del teléfono.'})
        finally:
            self.operation = None


class PhoneScreenLabel(QLabel):
    def __init__(self, tap_callback):
        super().__init__()
        self.tap_callback = tap_callback
        self.original_size = None
        self.setMinimumSize(250, 360)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setText('Cargando pantalla…')

    def mousePressEvent(self, event):
        pixmap = self.pixmap()
        if event.button() != Qt.MouseButton.LeftButton or pixmap is None or pixmap.isNull() or self.original_size is None:
            return
        left = (self.width() - pixmap.width()) / 2
        top = (self.height() - pixmap.height()) / 2
        x, y = event.position().x() - left, event.position().y() - top
        if 0 <= x < pixmap.width() and 0 <= y < pixmap.height():
            self.tap_callback(int(x * self.original_size.width() / pixmap.width()),
                              int(y * self.original_size.height() / pixmap.height()))


class PhoneScreenDialog(QDialog):
    def __init__(self, phone, parent=None):
        super().__init__(parent)
        self.phone, self.worker = phone, None
        self.setWindowTitle('Pantalla de Android')
        self.resize(420, 700)
        layout = QVBoxLayout(self)
        info = QLabel('Captura local: pulsa Actualizar para ver la pantalla actual. Algunas aplicaciones protegidas pueden aparecer en negro.')
        info.setWordWrap(True)
        layout.addWidget(info)
        self.image = PhoneScreenLabel(self.tap)
        layout.addWidget(self.image, 1)
        self.allow_taps = QCheckBox('Permitir toques en esta sesión')
        layout.addWidget(self.allow_taps)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.refresh_button = QPushButton('Actualizar pantalla')
        self.refresh_button.clicked.connect(self.refresh)
        layout.addWidget(self.refresh_button)
        QTimer.singleShot(0, self.refresh)

    def run_operation(self, operation):
        if self.worker is not None:
            return
        self.refresh_button.setEnabled(False)
        self.worker = PhoneWorker(operation, self)
        self.worker.outcome.connect(self.on_result)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def refresh(self):
        self.status.setText('Solicitando captura al teléfono…')
        self.run_operation(lambda: {'image': self.phone.screenshot()})

    def tap(self, x, y):
        if not self.allow_taps.isChecked():
            self.status.setText('Activa “Permitir toques” para controlar la pantalla.')
            return
        self.status.setText('Enviando toque…')
        self.run_operation(lambda: self.phone.action('tocar', x, y))

    @pyqtSlot(object)
    def on_result(self, result):
        if result.get('error'):
            self.status.setText(result['error'])
        elif 'image' in result:
            image = QPixmap()
            if not image.loadFromData(result['image'], 'PNG'):
                self.status.setText('No se pudo mostrar la captura del teléfono.')
                return
            self.image.original_size = image.size()
            self.image.setPixmap(image.scaled(self.image.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            self.status.setText('Captura local. Actualiza para ver cambios.')
        else:
            self.status.setText('Toque enviado. Actualiza para comprobar el resultado.')

    @pyqtSlot()
    def on_finished(self):
        self.worker = None
        self.refresh_button.setEnabled(True)

    def reject(self):
        if self.worker is None:
            super().reject()

    def closeEvent(self, event):
        if self.worker is not None:
            event.ignore()
        else:
            event.accept()


class PhoneDialog(QDialog):
    def __init__(self, phone, parent=None):
        super().__init__(parent)
        self.phone = phone
        self.worker = None
        self.setWindowTitle('Conectar Android')
        self.resize(560, 480)
        layout = QVBoxLayout(self)
        heading = QLabel('Tu teléfono Android')
        heading.setObjectName('dialogTitle')
        layout.addWidget(heading)
        note = QLabel('En Android 11 o posterior, activa Opciones de desarrollador y Depuración inalámbrica. '
                      'En “Emparejar dispositivo con código” aparecen la dirección de emparejamiento y el código. '
                      'Después, usa la dirección principal de Depuración inalámbrica para conectar: normalmente el puerto es distinto. '
                      'La conexión es por red local; el teléfono debe autorizarla. No escribas el código en el chat.')
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.pair_address = QLineEdit()
        self.pair_address.setPlaceholderText('Dirección y puerto de emparejamiento')
        self.code = QLineEdit()
        self.code.setPlaceholderText('Código temporal de seis dígitos')
        self.code.setEchoMode(QLineEdit.EchoMode.Password)
        self.code.setMaxLength(6)
        self.address = QLineEdit()
        self.address.setPlaceholderText('Dirección y puerto de conexión')
        form.addRow('Para emparejar', self.pair_address)
        form.addRow('Código de Android', self.code)
        form.addRow('Para conectar', self.address)
        layout.addLayout(form)
        self.permission = QCheckBox('Permitir batería, navegación y apertura de apps compatibles sin preguntar cada vez')
        self.permission.setChecked(read_state().get('phone_basic_accepted') is True)
        self.permission.setToolTip('La captura de pantalla y tocar coordenadas siguen pidiendo autorización individual. Puedes desactivar esta casilla aquí.')
        self.permission.toggled.connect(self.change_permission)
        layout.addWidget(self.permission)
        self.message = QLabel('Usa el botón Emparejar una vez y después Conectar. Si ya estaba emparejado, puedes conectar directamente.')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        row = QHBoxLayout()
        self.pair_button = QPushButton('Emparejar')
        self.pair_button.clicked.connect(self.pair)
        self.connect_button = QPushButton('Conectar')
        self.connect_button.clicked.connect(self.connect_phone)
        self.screen_button = QPushButton('Ver pantalla')
        self.screen_button.clicked.connect(self.open_screen)
        self.disconnect_button = QPushButton('Desconectar')
        self.disconnect_button.clicked.connect(lambda: self.start_operation(self.phone.disconnect))
        self.close_button = QPushButton('Cerrar')
        self.close_button.clicked.connect(self.accept)
        for button in (self.pair_button, self.connect_button, self.screen_button, self.disconnect_button, self.close_button):
            row.addWidget(button)
        layout.addLayout(row)

    def change_permission(self, checked):
        try:
            set_phone_permission(checked)
        except OSError:
            self.permission.blockSignals(True)
            self.permission.setChecked(not checked)
            self.permission.blockSignals(False)
            self.message.setText('No se pudo guardar el permiso del teléfono.')

    def pair(self):
        endpoint, code = self.pair_address.text().strip(), self.code.text()
        self.code.clear()
        self.start_operation(lambda: self.phone.pair(endpoint, code))

    def open_screen(self):
        if not self.phone.serial:
            self.message.setText('Primero conecta el teléfono.')
            return
        PhoneScreenDialog(self.phone, self).exec()

    def connect_phone(self):
        endpoint = self.address.text().strip()
        self.start_operation(lambda: self.phone.connect(endpoint))

    def start_operation(self, operation):
        if self.worker is not None:
            return
        for button in (self.pair_button, self.connect_button, self.screen_button, self.disconnect_button, self.close_button):
            button.setEnabled(False)
        self.message.setText('Conectando con Android…')
        self.worker = PhoneWorker(operation, self)
        self.worker.outcome.connect(self.finish_operation)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.finished.connect(self.worker_finished)
        self.worker.start()

    @pyqtSlot(object)
    def finish_operation(self, result):
        self.message.setText(result.get('error') or ('Emparejado. Ahora introduce la dirección de conexión y pulsa Conectar.' if result.get('paired') else
                             'Teléfono conectado. Puedes cerrar esta ventana.' if result.get('connected') else
                             'Teléfono desconectado de esta sesión.'))

    @pyqtSlot()
    def worker_finished(self):
        self.worker = None
        for button in (self.pair_button, self.connect_button, self.screen_button, self.disconnect_button, self.close_button):
            button.setEnabled(True)

    def reject(self):
        if self.worker is None:
            super().reject()

    def closeEvent(self, event):
        if self.worker is not None:
            event.ignore()
        else:
            event.accept()


class JarvisWindow(QMainWindow):
    def __init__(self, brain, voice):
        super().__init__()
        self.brain, self.voice = brain, voice
        self.agenda = Agenda()
        self.reminder_windows = {}
        self.weather_query = None
        self.weather_generation = 0
        self.weather_refresh_in_flight = False
        self.weather_sound = None
        self.weather_sound_dir = None
        self.sound_variant = 0
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
        self.phone_button = QPushButton('Teléfono')
        self.phone_button.clicked.connect(self.open_phone)
        top.addWidget(self.phone_button)
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

        self.weather_loading = QLabel('Buscando el clima…')
        self.weather_loading.setTextFormat(Qt.TextFormat.PlainText)
        self.weather_loading.setObjectName('weatherLoading')
        self.weather_loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.weather_loading.hide()
        layout.addWidget(self.weather_loading)
        self.weather_view = WeatherView(self.dismiss_weather)
        self.weather_view.hide()
        layout.addWidget(self.weather_view, 1, Qt.AlignmentFlag.AlignHCenter)
        self.core = CoreAnimation(self.preferences)
        layout.addWidget(self.core, 0, Qt.AlignmentFlag.AlignHCenter)
        self.voice_signals = VoiceSignals(self)
        self.core_state = CoreState()
        self.voice_signals.activity.connect(self.on_voice_activity)
        self.voice_signals.voice_level.connect(self.core.set_voice_level)
        self.voice_signals.briefing_ready.connect(self.on_briefing_ready)
        self.voice_signals.scheduled_email_result.connect(self.on_scheduled_email_result)
        self.voice_signals.weather_event.connect(self.on_weather_event)
        self.voice_signals.weather_refresh.connect(self.on_weather_refresh)
        self.weather_refresh_timer = QTimer(self)
        self.weather_refresh_timer.setInterval(10 * 60 * 1000)
        self.weather_refresh_timer.timeout.connect(self.refresh_weather)
        signals_for_weather = self.voice_signals
        weather_timing = WeatherLoadingTiming()
        def relay_weather(event, payload):
            # This callback is invoked in the chat/voice worker, not the UI thread.
            # Delaying success keeps spoken and visual results synchronized.
            weather_timing.wait_for_event(event)
            try:
                signals_for_weather.weather_event.emit(event, payload)
            except RuntimeError:
                pass
        self.brain.weather_event = relay_weather
        self.voice.on_activity = self.voice_signals.activity.emit
        self.voice.on_level = self.voice_signals.voice_level.emit

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
        signals = self.voice_signals
        def notify_scheduled(result):
            try:
                signals.scheduled_email_result.emit(result)
            except RuntimeError:
                pass
        self.email_scheduler = scheduled_emails.Scheduler(notify_scheduled)
        self.email_scheduler.start()
        if not read_state().get('startup_briefing_accepted'):
            QTimer.singleShot(0, self.check_reminders)

    def play_thinking_sound(self, kind='thinking'):
        if self.preferences.get('weather_sound') != 'activado' or self.core_state.speaking:
            return
        try:
            # Qt plays asynchronously and independently of the voice mixer.
            # Missing multimedia support or an audio device must not block JARVIS.
            from PyQt6.QtMultimedia import QSoundEffect
            if self.weather_sound is None:
                self.weather_sound_dir = tempfile.TemporaryDirectory(prefix='jarvis-effects-')
                self.weather_sound = QSoundEffect(self)
                self.weather_sound.setVolume(0.35)
            self.sound_variant = (self.sound_variant + 1) % 3
            path = Path(self.weather_sound_dir.name) / f'{kind}-{self.sound_variant}.wav'
            if not path.exists():
                write_search_cue(path, kind=kind, variant=self.sound_variant)
            self.weather_sound.stop()
            self.weather_sound.setSource(QUrl.fromLocalFile(str(path)))
            self.weather_sound.play()
        except Exception:
            pass  # Weather remains usable without sound hardware or Qt multimedia.

    def stop_weather_sound(self):
        if self.weather_sound is not None:
            self.weather_sound.stop()

    def dismiss_weather(self):
        self.stop_weather_sound()
        self.weather_generation += 1
        self.weather_query = None
        self.weather_refresh_timer.stop()
        self.weather_view.hide()
        self.weather_loading.hide()
        self.core.set_weather_searching(False)
        self.core.set_compact_display(False)
        self.root_layout.setAlignment(self.core, Qt.AlignmentFlag.AlignHCenter)
        if not self.compact:
            self.heading.show()
            self.subtitle.show()

    @pyqtSlot(str, object)
    def on_weather_event(self, event, data):
        if event == 'loading':
            if self.compact:
                self.toggle_compact()
            self.dismiss_weather()
            location = str(data.get('location', ''))[:150] if isinstance(data, dict) else ''
            self.weather_loading.setText('Buscando el clima de ' + location + '…' if location else 'Buscando el clima…')
            self.weather_loading.show()
            self.core.set_weather_searching(True)
            self.play_thinking_sound('weather')
            self.status.setText('Buscando datos del clima…')
            self.set_task_state('thinking')
        elif event == 'result' and isinstance(data, dict) and data.get('ok') is True:
            self.weather_loading.hide()
            self.core.set_weather_searching(False)
            self.stop_weather_sound()
            try:
                self.weather_view.show_data(data)
                self.weather_query = data.get('requested')
                if read_state().get('network_actions_accepted') is True:
                    self.weather_refresh_timer.start()
                self.heading.hide()
                self.subtitle.hide()
                self.weather_view.show()
                self.core.set_compact_display(True)
                self.root_layout.setAlignment(self.core, Qt.AlignmentFlag.AlignLeft)
                self.status.setText('Clima actualizado')
            except (KeyError, TypeError, ValueError):
                self.dismiss_weather()
                self.status.setText('No se pudo mostrar la vista del clima.')
        elif event == 'error':
            self.dismiss_weather()
            message = data.get('error') if isinstance(data, dict) else None
            self.status.setText(str(message or 'Necesito que indiques la ubicación del clima.'))

    @pyqtSlot()
    def refresh_weather(self):
        if (not self.weather_query or not self.weather_view.isVisible() or self.weather_refresh_in_flight
                or read_state().get('network_actions_accepted') is not True):
            return
        self.weather_refresh_in_flight = True
        token, query, signals = self.weather_generation, self.weather_query, self.voice_signals
        self.weather_view.set_notice('Actualizando…')
        def work():
            try:
                import weather
                result = weather.get_weather(query)
            except Exception:
                result = {'error': 'No se pudo actualizar el clima.'}
            try:
                signals.weather_refresh.emit(token, result)
            except RuntimeError:
                pass
        threading.Thread(target=work, name='JARVIS clima', daemon=True).start()

    @pyqtSlot(int, object)
    def on_weather_refresh(self, token, data):
        self.weather_refresh_in_flight = False
        if token != self.weather_generation or not self.weather_view.isVisible():
            return
        if isinstance(data, dict) and data.get('ok') is True:
            try:
                self.weather_view.show_data(data)
                self.status.setText('Clima actualizado')
            except (KeyError, ValueError, TypeError):
                self.weather_view.set_notice('No se pudo actualizar')
        else:
            self.weather_view.set_notice('Sin actualizar · datos anteriores')

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
        privacy = ('\nAl autorizar, permites programar y enviar correos futuros sin preguntar cada vez. Se guardan en este equipo; si JARVIS estuvo cerrado intentará enviarlos al abrirse. Puedes desactivarlo en Ajustes; un envío ya iniciado no se interrumpe.'
                   if name == 'schedule_email_permission' else '\nAl autorizar, permites eliminar recordatorios locales cuando lo pidas sin volver a preguntar. Puedes revocarlo en Ajustes. Se eliminará el recordatorio solicitado.'
                   if name == 'delete_reminder_permission' else '\nSe abrirá un borrador de WhatsApp; no se enviará automáticamente. Revisa el número y el texto y pulsa Enviar en WhatsApp.'
                   if name == 'whatsapp_prepare' else '\nSe capturará la pantalla completa y se enviará a NVIDIA; la descripción puede enviarse al proveedor del chat.'
                   if name in ('inspect_screen', 'phone_inspect_screen') else '\nLa imagen se enviará a NVIDIA; su descripción puede enviarse al proveedor del chat.'
                   if name == 'inspect_image' else '\nLos nombres de archivos del teléfono pueden contener información privada y se enviarán al proveedor del chat.'
                   if name == 'phone_list_files' else '\nSe buscarán correos en Gmail y sus metadatos pueden enviarse al proveedor del chat.'
                   if name == 'search_gmail' else '\nSe descargará el adjunto de Gmail y se enviará a NVIDIA; su descripción puede enviarse al proveedor del chat.'
                   if name == 'inspect_gmail_image' else ' El contenido del correo se enviará al proveedor del chat.'
                   if name == 'read_gmail' else ' Se enviará el correo completo al destinatario indicado.'
                   if name in ('send_gmail', 'reply_gmail') else ' Se modificará la clasificación de este correo en Gmail.'
                   if name == 'classify_gmail' else ' Se consultará tu agenda y los datos pueden enviarse al proveedor del chat.'
                   if name in ('list_calendar_events', 'list_reminders') else '\nLos registros solicitados pueden contener datos sensibles y enviarse al proveedor del chat.'
                   if name == 'review_startup_logs' else '')
        if name == 'schedule_email_permission':
            details = ('Para: ' + str(args.get('to', '')) + '\nAsunto: ' + str(args.get('subject', '')) + '\nMensaje: ' + str(args.get('body', '')) + '\nCuándo: ' + str(args.get('when', '')))
            heading = 'Permiso para programar correos'
        elif name == 'delete_reminder_permission':
            try:
                when = datetime.fromisoformat(args['when']).strftime('%d/%m a las %H:%M')
                details = f"Recordatorio: {args.get('title', '')}, {when}"
            except (KeyError, TypeError, ValueError):
                details = 'Recordatorio solicitado.'
            heading = 'Permiso para eliminar recordatorios'
        else:
            details = json.dumps(args, ensure_ascii=False, indent=2, default=str)
            heading = 'Permiso solicitado para: ' + name
        self.append_chat('Sistema', heading + '\n' + details + privacy +
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
        previous = self.core_state.task
        self.core.set_mode(self.core_state.set_task(state))
        if state == 'thinking' and previous != 'thinking' and not self.core.weather_searching:
            self.play_thinking_sound()
        elif state != 'thinking' and previous == 'thinking' and not self.core.weather_searching:
            self.stop_weather_sound()

    @pyqtSlot(bool)
    def on_voice_activity(self, active):
        if active:
            self.stop_weather_sound()
        self.core.set_mode(self.core_state.set_speaking(active))

    @pyqtSlot(str)
    @pyqtSlot(bool)
    def on_conversation_changed(self, enabled):
        self.conversation_enabled = enabled
        self.status.setText('Conversando · te escucho' if enabled else 'Esperando que digas Jarvis')

    def on_voice_status(self, status):
        self.status.setText(status)
        if status.startswith('Esperando autorización'):
            self.set_task_state('approval')
        elif status == 'Pensando':
            self.set_task_state('thinking')
        else:
            self.set_task_state('idle')

    def open_phone(self):
        if self.thread is not None:
            self.status.setText('Espera a que termine la solicitud antes de conectar el teléfono.')
            return
        PhoneDialog(self.brain.brain.controller.phone, self).exec()

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
            box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            self.reminder_windows[reminder['id']] = box
            box.finished.connect(lambda _result, key=reminder['id']: self.reminder_windows.pop(key, None))
            box.show()
            # The voice session speaks between listening cycles, never during consent.
            if isinstance(self.worker, VoiceWorker):
                self.worker.session.queue_reminder(title)
            else:
                self.voice.speak('Señor, recordatorio: ' + title)

    @pyqtSlot(object)
    def on_scheduled_email_result(self, result):
        if result.get('state') == 'sent':
            message = 'Se envió el correo programado con asunto ' + result.get('subject', '') + '.'
        else:
            message = ('No se pudo confirmar el envío del correo programado con asunto ' + result.get('subject', '')
                       + '. Revisa Enviados antes de reintentarlo.')
        self.append_chat('Sistema', message)
        self.status.setText(message)
        if isinstance(self.worker, VoiceWorker):
            self.worker.session.queue_announcement(message)
        elif self.thread is None and self.chat_audio.isChecked():
            self.voice.speak(speech_text(message))

    def open_memory(self):
        if self.thread is not None:
            QMessageBox.information(self, 'Memoria', 'Detén el micrófono o espera a que termine la solicitud antes de modificar la memoria.')
            return
        try:
            MemoryDialog(self).exec()
        except (sqlite3.Error, OSError):
            QMessageBox.warning(self, 'Memoria', 'No se pudo abrir la memoria local.')

    def start_briefing(self):
        if not read_state().get('startup_briefing_accepted'):
            return
        greeting = startup_briefing.greeting(datetime.now().astimezone()) + ', señor. ¿Cómo está hoy?'
        self.append_chat('JARVIS', greeting)
        if self.chat_audio.isChecked() and self.thread is None:
            self.voice.speak(speech_text(greeting))
        signals = self.voice_signals
        def run():
            try:
                result = startup_briefing.build(include_greeting=False)
            except Exception:
                result = 'No pude completar la revisión inicial.'
            try:
                signals.briefing_ready.emit(result)
            except RuntimeError:
                pass  # The window may have closed while the review was running.
        threading.Thread(target=run, name='JARVIS revisión inicial', daemon=True).start()

    @pyqtSlot(str)
    def on_briefing_ready(self, text):
        if not read_state().get('startup_briefing_accepted'):
            return
        self.append_chat('JARVIS', text)
        # Never speak over microphone capture or an active chat/approval request.
        if self.chat_audio.isChecked() and self.thread is None:
            self.voice.speak(speech_text(text))
        elif self.thread is not None:
            self.status.setText('Revisión inicial disponible en el chat')

    def open_visual_settings(self):
        dialog = VisualSettingsDialog(self.preferences, self.conversation_enabled, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.preferences = save_ui(UI_SETTINGS_PATH, dialog.values())
            if dialog.automation_permission.isChecked() != (read_state().get('automation_accepted') is True):
                set_automation_permission(dialog.automation_permission.isChecked())
            set_network_permission(dialog.network_permission.isChecked())
            set_gmail_permission(dialog.gmail_permission.isChecked())
            set_agenda_permission(dialog.agenda_permission.isChecked())
            set_agenda_delete_permission(dialog.agenda_delete_permission.isChecked())
            set_scheduled_email_permission(dialog.scheduled_email_permission.isChecked())
            set_briefing_permission(dialog.briefing_permission.isChecked())
            self.conversation_enabled = dialog.conversation_live.isChecked()
            if isinstance(self.worker, VoiceWorker):
                self.worker.session.set_conversation_mode(self.conversation_enabled)
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
            if self.weather_view.isVisible() or self.weather_loading.isVisible():
                self.dismiss_weather()
            self.expanded_geometry = self.geometry()
            self.expanded_maximized = self.isMaximized()
            self.showNormal()
            self.compact = True
            self.phone_button.hide()
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
            self.phone_button.show()
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
        self.worker.conversation_changed.connect(self.on_conversation_changed)
        if self.conversation_enabled:
            self.worker.session.set_conversation_mode(True)
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
        if isinstance(self.worker, VoiceWorker):
            # If listening was stopped before queued reminders were spoken,
            # deliver them after the microphone has actually stopped.
            import queue
            while True:
                try:
                    message = self.worker.session.reminders.get_nowait()
                except queue.Empty:
                    break
                self.voice.speak(message)
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
            self.stop_weather_sound()
            if self.weather_sound is not None:
                self.weather_sound.setSource(QUrl())
            if self.weather_sound_dir is not None:
                self.weather_sound_dir.cleanup()
            self.email_scheduler.stop()
            self.voice.on_activity = None
            self.voice.on_level = None
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
QLabel#weatherLoading { color: #8de8ff; font-size: 15px; font-weight: 700; }
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



class UpdateSignals(QObject):
    done = pyqtSignal(str, bool)


def check_gui_updates():
    """Check in a worker before any conversation, then restart the GUI if updated."""
    from PyQt6.QtCore import QEventLoop
    import updater
    waiting = QDialog()
    waiting.setWindowTitle('JARVIS')
    waiting.setWindowFlags(waiting.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint)
    layout = QVBoxLayout(waiting)
    layout.addWidget(QLabel('Buscando actualizaciones de JARVIS…'))
    signals = UpdateSignals()
    loop = QEventLoop()
    result = {'error': '', 'updated': False}
    def finished(error, updated):
        result.update(error=error, updated=updated)
        loop.quit()
    signals.done.connect(finished)
    def work():
        try:
            updated = updater.update()
            signals.done.emit('', updated)
        except Exception as exc:
            signals.done.emit(str(exc)[:500], False)
    waiting.show()
    threading.Thread(target=work, name='JARVIS actualizaciones', daemon=True).start()
    loop.exec()
    waiting.close()
    if result['error']:
        message = ('Hay cambios locales; no se actualizó JARVIS.' if 'Hay cambios locales' in result['error']
                   else 'No se pudo actualizar JARVIS. Comprueba la conexión, el remoto Git y las dependencias.')
        QMessageBox.warning(None, 'Actualización', message)
        if 'Código actualizado, pero falló' in result['error']:
            return True  # Avoid running a partially upgraded environment.
    if result['updated']:
        try:
            updater.restart('gui.py')
        except OSError:
            QMessageBox.warning(None, 'Actualización', 'JARVIS se actualizó pero no pudo reiniciarse; ábrelo de nuevo.')
            return True
    return False

def main():
    load_dotenv(ROOT / '.env')
    app = QApplication(sys.argv)
    # Keep the user's launcher current when the project moves or is updated.
    if sys.platform.startswith('linux'):
        try:
            import desktop_launcher
            desktop_launcher.install()
        except (OSError, ValueError):
            pass  # Desktop integration is optional; never block JARVIS.
    app.setFont(QFont('Segoe UI', 10))
    # Announce before the first-run gate, just like the console entry point.
    voice = Voice()
    print('Activando protocolos de seguridad...', flush=True)
    voice.speak('Activando protocolos de seguridad...')
    state = read_state()
    if not state.get('automation_asked') or not state.get('initial_accepted'):
        first = state.get('initial_accepted') is not True
        text = ('JARVIS funcionará con los permisos de tu usuario; no lo ejecutes como administrador.\n\n'
                '¿Autorizas de forma persistente, sin preguntar cada vez, búsquedas, clima, música, abrir aplicaciones y páginas, '
                'consultar y crear recordatorios, leer, crear, modificar y mover archivos, controlar volumen y brillo, '
                'buscar, leer, enviar, responder y clasificar Gmail? También activará el resumen inicial y '
                'las actualizaciones automáticas de código y dependencias desde el remoto Git configurado.\n\n'
                'Puede cometer errores o seguir contenido malicioso; tus datos pueden enviarse a proveedores externos. '
                'Cada borrador de WhatsApp, las acciones de administrador, comandos de terminal, control directo del ratón y teclado e imágenes seguirán requiriendo autorización. '
                'Puedes cambiar los permisos en Ajustes.\n\n'
                + ('Sí: iniciar con automatización. No: iniciar sin concederla. Cancelar: no iniciar.' if first else
                   'Sí: activar. No: mantener desactivada. Cancelar: salir.'))
        answer = QMessageBox.question(None, 'Autorización de JARVIS', text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Cancel:
            return 1
        try:
            set_automation_permission(answer == QMessageBox.StandardButton.Yes)
            if first:
                state = read_state()
                state['initial_accepted'] = True
                # Reuse the atomic writer; no code or credentials go in this file.
                from permissions import _write_state
                _write_state(state)
        except OSError:
            QMessageBox.critical(None, 'JARVIS', 'No se pudo guardar la autorización. No se iniciará.')
            return 1
    if read_state().get('automation_accepted') is True or os.getenv('JARVIS_AUTO_UPDATE', '0') == '1':
        if check_gui_updates():
            return 1
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
    QTimer.singleShot(0, window.start_briefing)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
