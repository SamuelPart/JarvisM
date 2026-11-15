"""Console entry point; microphone and TTS are optional at runtime."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from voice import Voice
from errors import describe_error
from permissions import read_state, set_network_permission
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
    # The explicit environment opt-in acknowledges that updates execute remote code.
    if os.getenv('JARVIS_AUTO_UPDATE', '0') == '1': check_updates()
    from provider import create_brain
    from system_control import SystemController
    try:
        brain = create_brain(SystemController(), approve)
    except (ValueError, RuntimeError) as exc:
        print('No se pudo iniciar:', exc); return 1
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
