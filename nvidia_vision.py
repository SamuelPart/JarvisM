"""Explicitly user-approved image analysis via NVIDIA NIM."""
import base64
from provider_settings import resolve_api_key
import os
from pathlib import Path
import requests

NVIDIA_URL = 'https://integrate.api.nvidia.com/v1/chat/completions'
DEFAULT_MODEL = 'mistralai/mistral-large-4-1t-a52b'
MAX_IMAGE_BYTES = 10 * 1024 * 1024


class VisionError(Exception):
    pass


def image_mime(data):
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise VisionError('La imagen debe pesar como máximo 10 MB y no estar vacía.')
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return 'image/webp'
    raise VisionError('Usa una imagen PNG, JPEG o WebP válida.')


def validate_image(data):
    image_mime(data)
    return data


def read_image(path):
    try:
        with Path(path).expanduser().open('rb') as file:
            data = file.read(MAX_IMAGE_BYTES + 1)
    except OSError as exc:
        raise VisionError('No se pudo leer la imagen seleccionada.') from exc
    return validate_image(data)


def analyze(data, question, session_factory=requests.Session):
    mime = image_mime(data)
    question = question.strip()
    if not question or len(question) > 2000:
        raise VisionError('La pregunta debe tener entre 1 y 2000 caracteres.')
    key = os.getenv('NVIDIA_VISION_API_KEY', '').strip() or resolve_api_key(os.getenv('NVIDIA_API_KEY', '').strip())
    if not key:
        raise VisionError('Configura tu clave en Ajustes → «Proveedor de IA» (o NVIDIA_VISION_API_KEY/NVIDIA_API_KEY en .env para consola). No compartas tu clave.')
    model = os.getenv('NVIDIA_VISION_MODEL', DEFAULT_MODEL)
    data_url = 'data:' + mime + ';base64,' + base64.b64encode(data).decode('ascii')
    payload = {'model': model, 'messages': [{'role': 'user', 'content': [
        {'type': 'text', 'text': question}, {'type': 'image_url', 'image_url': {'url': data_url}}
    ]}], 'max_tokens': 1024, 'stream': False, 'temperature': 0.5, 'top_p': 1}
    session = session_factory()
    # Do not silently send image bytes or credentials through proxy variables.
    session.trust_env = False
    try:
        response = session.post(NVIDIA_URL, headers={'Authorization': 'Bearer ' + key, 'Accept': 'application/json'},
                                json=payload, timeout=(10, 120), allow_redirects=False)
        if response.status_code in (401, 403):
            raise VisionError(f'NVIDIA rechazó la clave o sus permisos (HTTP {response.status_code}).')
        if response.status_code == 429:
            raise VisionError('NVIDIA alcanzó un límite de uso o cuota (HTTP 429).')
        if not 200 <= response.status_code < 300:
            raise VisionError(f'NVIDIA rechazó el análisis de imagen (HTTP {response.status_code}); verifica el modelo y su disponibilidad.')
        result = response.json()['choices'][0]['message']['content']
        if not isinstance(result, str) or not result.strip():
            raise VisionError('NVIDIA no devolvió una descripción de la imagen.')
        return result.strip()
    except requests.exceptions.SSLError as exc:
        raise VisionError('Falló la conexión segura con NVIDIA (TLS). Comprueba certificados y reloj del equipo.') from exc
    except requests.exceptions.Timeout as exc:
        raise VisionError('La conexión con NVIDIA agotó el tiempo de espera. Comprueba tu red e inténtalo de nuevo.') from exc
    except requests.exceptions.ConnectionError as exc:
        raise VisionError('No se pudo establecer conexión con NVIDIA. Comprueba DNS, Internet o restricciones de red; la clave aún no se ha validado.') from exc
    except requests.RequestException as exc:
        raise VisionError('La solicitud de visión a NVIDIA falló por un error de red.') from exc
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise VisionError('NVIDIA devolvió una respuesta inválida.') from exc
    finally:
        session.close()
