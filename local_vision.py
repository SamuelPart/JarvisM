"""Image analysis through a trusted local Ollama instance, never a remote provider."""
import base64
import os
from pathlib import Path
import requests

LOCAL_URL = 'http://127.0.0.1:11434/api/generate'
MODEL = 'llava:latest'
MAX_IMAGE_BYTES = 10 * 1024 * 1024


class VisionError(Exception):
    pass


def validate_image(data):
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise VisionError('La imagen debe pesar menos de 10 MB y no estar vacía.')
    valid = (data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'\xff\xd8\xff') or
             (data.startswith(b'RIFF') and data[8:12] == b'WEBP'))
    if not valid:
        raise VisionError('Usa una imagen PNG, JPEG o WebP válida.')
    return data


def read_image(path):
    try:
        with Path(path).expanduser().open('rb') as file:
            data = file.read(MAX_IMAGE_BYTES + 1)
    except OSError as exc:
        raise VisionError('No se pudo leer la imagen seleccionada.') from exc
    return validate_image(data)


def analyze(data, question, session_factory=requests.Session):
    data = validate_image(data)
    question = question.strip()
    if not question or len(question) > 2000:
        raise VisionError('La pregunta debe tener entre 1 y 2000 caracteres.')
    session = session_factory()
    # Ignore proxy environment variables so image bytes only go to loopback.
    session.trust_env = False
    try:
        response = session.post(LOCAL_URL, json={'model': MODEL, 'prompt': question,
                                'images': [base64.b64encode(data).decode('ascii')],
                                'stream': False, 'keep_alive': '5m'}, timeout=(5, 300), allow_redirects=False)
        if response.status_code == 404:
            raise VisionError('No se encontró el modelo local llava. Ejecuta: ollama pull llava')
        if not 200 <= response.status_code < 300:
            raise VisionError(f'El servicio local de visión devolvió HTTP {response.status_code}.')
        result = response.json().get('response')
        if not isinstance(result, str) or not result.strip():
            raise VisionError('El modelo local no devolvió una respuesta.')
        return result.strip()
    except requests.RequestException as exc:
        raise VisionError('No se pudo conectar con Ollama en este equipo. Comprueba que esté instalado y ejecutándose.') from exc
    except (ValueError, AttributeError) as exc:
        raise VisionError('El servicio local devolvió una respuesta inválida.') from exc
    finally:
        session.close()
