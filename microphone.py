"""On-demand microphone capture and Google Speech Recognition."""
import speech_recognition as sr


def listen():
    recognizer = sr.Recognizer()
    recognizer.operation_timeout = 10
    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.4)
            audio = recognizer.listen(source, timeout=4, phrase_time_limit=20)
        return recognizer.recognize_google(audio, language='es-ES')
    except sr.WaitTimeoutError as exc:
        raise TimeoutError() from exc
    except sr.UnknownValueError:
        return ''
