"""Console entry point; microphone and TTS are optional at runtime."""
from __future__ import annotations
import json
import os
import sys
import threading
from pathlib import Path
from dotenv import load_dotenv
from voice import Voice
from errors import describe_error
from permissions import read_state, set_network_permission, set_gmail_permission, set_agenda_permission, set_briefing_permission
from text_links import speech_text

ROOT = Path(__file__).resolve().parent
STATE = ROOT / '.jarvis-state.json'


voice = Voice()


def speak(text):
    voice.speak(text)


def announce(text):
    print(text, flush=True)
    speak(speech_text(text))


def confirm(prompt):
    try: return input(prompt + ' Escriba SI para confirmar: ').strip() == 'SI'
    except (EOFError, KeyboardInterrupt): return False


def initial_security():
    try:
        state = json.loads(STATE.read_text(encoding='utf-8'))
        if state.get('initial_accepted') is True: return True
    except (OSError, ValueError, AttributeError):
        pass
    print('JARVIS puede ejecutar comandos y acceder a archivos con sus permisos. No lo ejecute como administrador.')
    if not confirm('¿Autoriza iniciar JARVIS en esta máquina?'): return False
    STATE.write_text(json.dumps({'initial_accepted': True}, ensure_ascii=False), encoding='utf-8')
    return True


def approve(name, args):
    print('\nSolicitud de herramienta:', name)
    print(json.dumps(args, ensure_ascii=False, indent=2, default=str))
    return confirm('¿Autoriza esta acción exacta?')


def listen():
    import speech_recognition as sr
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        print('Escuchando…')
        audio = recognizer.listen(source, timeout=8, phrase_time_limit=20)
    return recognizer.recognize_google(audio, language='es-ES')


def check_updates():
    import updater
    try:
        print('Buscando actualizaciones…')
        if updater.update():
            print('Actualización aplicada; reiniciando.', flush=True)
            updater.restart()
        print('No hay actualizaciones nuevas.')
    except (updater.UpdateError, OSError, __import__('subprocess').TimeoutExpired) as exc:
        print('No se pudo actualizar:', exc)


def main():
    load_dotenv(ROOT / '.env')
    announce('Activando protocolos de seguridad...')
    if not initial_security():
        print('Inicio cancelado.'); return 1
    if not read_state().get('network_actions_asked'):
        granted = confirm('¿Autoriza búsquedas web y música sin preguntar cada vez? Se envían consultas a servicios externos; comandos y archivos siguen requiriendo permiso.')
        try:
            set_network_permission(granted)
        except OSError:
            print('No se pudo guardar el permiso; se pedirá autorización cada vez.')
    if not read_state().get('gmail_actions_asked'):
        granted = confirm('¿Autoriza permanentemente buscar y leer Gmail, enviar correos y marcarlos importantes o spam sin preguntar cada vez? El contenido puede enviarse al proveedor del chat; JARVIS puede equivocarse o ser inducido por mensajes maliciosos. Las imágenes requieren permiso separado.')
        try:
            set_gmail_permission(granted)
        except OSError:
            print('No se pudo guardar el permiso de Gmail; se pedirá cada vez.')
    if not read_state().get('agenda_read_asked'):
        granted = confirm('¿Autoriza consultar la hora, recordatorios locales y Google Calendar sin preguntar cada vez? Sus datos pueden enviarse al proveedor de IA. Crear recordatorios requiere permiso aparte.')
        try:
            set_agenda_permission(granted)
        except OSError:
            print('No se pudo guardar el permiso de agenda; se pedirá en cada consulta.')
    if not read_state().get('startup_briefing_asked'):
        granted = confirm('¿Autoriza el resumen automático al iniciar? Consulta recordatorios locales, Google Calendar configurado, batería, memoria, disco y cantidad de errores de los registros; guarda una referencia local y la voz puede enviarse al servicio configurado; los detalles de registros solicitados pueden contener datos privados y enviarse al proveedor de IA.')
        try:
            set_briefing_permission(granted)
        except OSError:
            print('No se pudo guardar la preferencia; el resumen no se activará.')
    # The explicit environment opt-in acknowledges that updates execute remote code.
    if os.getenv('JARVIS_AUTO_UPDATE', '0') == '1': check_updates()
    from provider import create_brain
    from system_control import SystemController
    try:
        controller = SystemController()
        brain = create_brain(controller, approve)
    except (ValueError, RuntimeError) as exc:
        print('No se pudo iniciar:', exc); return 1
    if read_state().get('startup_briefing_accepted'):
        import startup_briefing
        from datetime import datetime
        announce(startup_briefing.greeting(datetime.now().astimezone()) + ', señor. ¿Cómo está hoy?')
        def run_briefing():
            try:
                result = startup_briefing.build(include_greeting=False)
            except Exception:
                result = 'No pude completar la revisión inicial.'
            if read_state().get('startup_briefing_accepted'):
                # Console remains usable; avoid playing into a microphone session.
                print('JARVIS — revisión inicial:', result, flush=True)
        threading.Thread(target=run_briefing, name='JARVIS revisión inicial', daemon=True).start()
    print('Escriba su mensaje, /voz, /actualizar o /salir.')
    while True:
        try:
            text = input('\nUsted: ').strip()
            if text.lower() in ('/salir', 'salir'): break
            if text.lower() in ('/actualizar', 'jarvis, busca actualizaciones', 'jarvis busca actualizaciones'):
                if confirm('La actualización ejecutará código y dependencias del remoto configurado. ¿Continuar?'):
                    check_updates()
                continue
            if text.lower() == '/voz':
                try:
                    text = listen(); print('Usted dijo:', text)
                except Exception as exc:
                    print('No se pudo reconocer la voz:', exc); continue
            if not text: continue
            try: announce(brain.ask(text))
            except Exception as exc:
                # Avoid exposing API keys or provider response details in the console.
                print(describe_error(exc))
        except (KeyboardInterrupt, EOFError):
            print('\nHasta pronto.'); break
    return 0


if __name__ == '__main__': sys.exit(main())
