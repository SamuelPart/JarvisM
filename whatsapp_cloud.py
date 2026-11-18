"""WhatsApp Business Cloud API for JARVIS (opt-in; same app, not another system).

Envs (en .env): WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_RECIPIENT
(dígitos internacionales del dueño, p. ej. 51987654321), WHATSAPP_VERIFY_TOKEN
(webhook GET), WHATSAPP_APP_SECRET (firma X-Hub-Signature-256; obligatoria para
POST: sin ella, el webhook rechaza todo), WHATSAPP_GRAPH_VERSION (opcional).

El token vive en .env (gitignored). Nunca se registra en el historial ni en la
memoria ancha. Sin estas variables JARVIS sigue funcionando igual; WhatsApp es
solo una salida más.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re

import requests

_GRAPH_VERSION = os.environ.get('WHATSAPP_GRAPH_VERSION', 'v21.0')
_API_ROOT = f'https://graph.facebook.com/{_GRAPH_VERSION}'
_MAX_TEXT = 4096


def digits(number):
    return re.sub(r'\D', '', str(number or ''))


def config():
    return os.environ.get('WHATSAPP_TOKEN'), os.environ.get('WHATSAPP_PHONE_NUMBER_ID')


def recipient():
    return digits(os.environ.get('WHATSAPP_RECIPIENT'))


def is_configured():
    token, phone_number_id = config()
    return bool(token and phone_number_id)


def send_message(body, to=None, timeout=20):
    """Envía un mensaje de texto; informa éxito solo si la API lo confirma."""
    token, phone_number_id = config()
    target = digits(to) or recipient()
    if not (token and phone_number_id):
        return {'error': 'WhatsApp no está configurado: faltan WHATSAPP_TOKEN y/o WHATSAPP_PHONE_NUMBER_ID en .env.'}
    if not target:
        return {'error': 'No hay destinatario: define WHATSAPP_RECIPIENT (dígitos con código de país) en .env.'}
    text = (body or '').strip()
    if not text:
        return {'error': 'El mensaje está vacío.'}
    if len(text) > _MAX_TEXT:
        return {'error': f'El mensaje supera {_MAX_TEXT} caracteres.'}
    if len(target) < 8:
        return {'error': 'Número no válido: se esperan dígitos internacionales (p. ej. 51987654321).'}
    payload = {'messaging_product': 'whatsapp', 'to': target, 'type': 'text',
               'text': {'preview_url': False, 'body': text}}
    try:
        response = requests.post(
            f'{_API_ROOT}/{phone_number_id}/messages',
            data=json.dumps(payload),
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            timeout=timeout)
    except requests.RequestException as exc:
        return {'error': f'No se pudo contactar con WhatsApp Cloud API: {type(exc).__name__}'}
    try:
        data = response.json()
    except ValueError:
        data = {}
    if 200 <= response.status_code < 300:
        messages = data.get('messages') if isinstance(data, dict) else None
        message_id = messages[0].get('id') if isinstance(messages, list) and messages else None
        return {'sent': True, 'message_id': message_id, 'to': target}
    detail = ''
    if isinstance(data, dict):
        error = data.get('error')
        if isinstance(error, dict):
            detail = str(error.get('message') or error.get('error_user_msg') or '').strip()
    detail = detail or str(data)[:300]
    return {'error': f'WhatsApp Cloud API respondió {response.status_code}: {detail or "sin detalle"}'}


def verify_webhook(params):
    """GET de verificación de Meta: devuelve el challenge solo si el token coincide."""
    if params.get('hub.mode') == 'subscribe':
        verify = os.environ.get('WHATSAPP_VERIFY_TOKEN')
        if verify and params.get('hub.verify_token') == verify:
            return str(params.get('hub.challenge') or '')
    return None


def verify_signature(raw_body, signature_header):
    """X-Hub-Signature-256 con WHATSAPP_APP_SECRET; sin el secreto, todo se rechaza."""
    secret = os.environ.get('WHATSAPP_APP_SECRET')
    if not secret:
        return False
    if not raw_body or not signature_header or not signature_header.startswith('sha256='):
        return False
    digest = hmac.new(secret.encode('utf-8'), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest('sha256=' + digest, signature_header)


def parse_inbound(payload):
    """Extrae mensajes de texto de un webhook de Meta; otro contenido se ignora."""
    out = []
    if not isinstance(payload, dict):
        return out
    for entry in payload.get('entry', []) if isinstance(payload.get('entry'), list) else []:
        for change in entry.get('changes', []) if isinstance(entry, dict) else []:
            value = change.get('value') if isinstance(change, dict) else {}
            if not isinstance(value, dict):
                continue
            contacts = {}
            for contact in value.get('contacts', []) if isinstance(value.get('contacts'), list) else []:
                if isinstance(contact, dict):
                    contacts[contact.get('wa_id')] = (contact.get('profile') or {}).get('name', '')
            for message in value.get('messages', []) if isinstance(value.get('messages'), list) else []:
                if not isinstance(message, dict) or message.get('type') != 'text':
                    continue
                text = (message.get('text') or {}).get('body') if isinstance(message.get('text'), dict) else ''
                sender = digits(message.get('from'))
                if sender and text:
                    out.append({'from': sender, 'id': message.get('id'), 'text': str(text),
                                'name': contacts.get(message.get('from') or '', '')})
    return out
