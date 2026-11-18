"""Direct routing for explicit, unambiguous Android requests."""
import re


def parse_phone_request(text):
    clean = re.sub(r'^\s*jarvis\s*[,!:;-]?\s*', '', text.strip(), flags=re.I).lower()
    if not re.search(r'\b(?:celular|tel[eé]fono|m[oó]vil|android)\b', clean):
        return None
    if re.search(r'\b(?:no|nunca)\s+(?:abras|toques|vayas|consultes)\b', clean):
        return None
    if re.search(r'\bbater[ií]a\b', clean) and not re.search(r'\b(?:ahorr[oa]|configura|desactiva|activar|activa)\b', clean):
        return 'phone_status', {}
    if re.search(r'\b(?:abre|abrir)\b', clean):
        for words, name in ((r'whatsapp', 'whatsapp'), (r'(?:google\s+)?chrome', 'chrome'), (r'youtube', 'youtube'), (r'ajustes', 'ajustes')):
            if re.search(r'\b' + words + r'\b', clean):
                return 'phone_action', {'action': name}
    if re.search(r'\b(?:vuelve|ir|ve|pulsa|presiona)\b', clean):
        if re.search(r'\b(?:inicio|home)\b', clean):
            return 'phone_action', {'action': 'inicio'}
        if re.search(r'\b(?:atr[aá]s|volver)\b', clean):
            return 'phone_action', {'action': 'atras'}
    return None


def format_phone_result(name, result):
    if not isinstance(result, dict):
        return 'No pude verificar la respuesta del teléfono.'
    if result.get('error'):
        return 'No pude controlar el teléfono: ' + str(result['error'])
    if name == 'phone_status':
        battery = result.get('battery_percent')
        if result.get('connected') and battery is not None:
            return f'El teléfono está conectado y tiene {battery} por ciento de batería.'
        if result.get('connected'):
            return 'El teléfono está conectado, pero no pude leer la batería.'
    if name == 'phone_action' and result.get('requested'):
        return 'Envié la orden al teléfono; no pude comprobar el resultado en pantalla.'
    return 'No pude verificar la respuesta del teléfono.'
