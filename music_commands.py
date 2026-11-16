"""Conservative direct routing for explicit music requests."""
import re


def parse_music_request(text):
    text = re.sub(r'^\s*(?:jarvis\s*[,!:;-]?\s*)', '', text.strip(), flags=re.I)
    text = re.sub(r'\s*[,;]?\s*por favor[.!?]*\s*$', '', text, flags=re.I).strip(' .!¡?¿')
    stop = re.fullmatch(r'(?:pausa|pausar|det[eé]n|detener|para|parar|apaga|corta)\s+(?:(?:la|el|esa|esta)\s+)?(?:m[uú]sica|canci[oó]n|tema|reproducci[oó]n|video|v[ií]deo)', text, re.I)
    if stop:
        return 'stop_music', {}
    match = re.match(r'^(?:pon(?:me)?|reproduce|reproducir|escuchar|quiero\s+escuchar|(?:quiero|puedes|puede|podr[ií]as)\s+(?:que\s+)?(?:me\s+)?(?:pongas|reproduzcas|poner|reproducir)|abre\s+en\s+youtube)\s+(.+)$', text, re.I)
    if not match:
        return None
    query = match.group(1).strip()
    # "Pon <title>" is commonly a music request, but do not hijack common
    # system, alarm, communication or application commands.
    if re.match(r'^(?:(?:el|la|los|las|un|una|mi|mis)\s+)?(?:brillo|volumen|alarma|temporizador|cron[oó]metro|recordatorio|reloj|hora|fecha|modo|pantalla|micr[oó]fono|c[aá]mara|wifi|bluetooth|silencio|correo|mensaje|whatsapp|aplicaci[oó]n|programa|ventana|idioma|fondo)\b', query, re.I):
        return None
    if not re.search(r'\b(?:m[uú]sica|canci[oó]n|tema|audio|youtube)\b', query, re.I) and not re.match(r'^(?:pon(?:me)?|reproduce|reproducir|quiero\s+escuchar)\b', text, re.I):
        return None
    query = re.sub(r'^(?:(?:la|el|una|un)\s+)?(?:canci[oó]n|tema|m[uú]sica|audio)\s+(?:(?:de|del|llamada|que se llama)\s+)?', '', query, flags=re.I)
    query = re.sub(r'\s+(?:en|de)\s+youtube$', '', query, flags=re.I).strip(' "\'.,!¡?¿')
    if not query or len(query) > 300:
        return None
    return 'play_music', {'query': query}


def is_music_action_request(text):
    """Guard action claims even when the wording is handled by the model."""
    if re.search(r'\b(?:no|nunca)\s+(?:pongas|reproduzcas|pauses|detengas)\b', text, re.I):
        return False
    action = re.search(r'\b(?:pon(?:me|ga|gas|er)?|pusieras|reproduc(?:e|ir|es|irla|irlo|e?zcas)|escuchar|escuche|o[ií]r|paus(?:a|ar|es)|det[eé]n|detener|detengas|parar|para|abr(?:e|ir|es|as))\b', text, re.I)
    subject = re.search(r'\b(?:m[uú]sica|canci[oó]n|canciones|tema|audio|youtube|v[ií]deo)\b', text, re.I)
    return bool(action and subject)


class MusicTrace:
    """Record only real music tool calls, not LLM claims."""
    def __init__(self, controller):
        self.controller = controller
        self.results = []

    def __getattr__(self, name):
        target = getattr(self.controller, name)
        if name not in ('play_music', 'stop_music', 'whatsapp_prepare'):
            return target
        def tracked(*args, **kwargs):
            try:
                result = target(*args, **kwargs)
            except Exception as exc:
                if name == 'whatsapp_prepare':
                    known = {
                        'Indique el número internacional con código de país y solo dígitos.':
                            'Necesito el número con código de país y solo dígitos.',
                        'El mensaje debe tener entre 1 y 4000 caracteres.':
                            'El mensaje está vacío o supera los 4000 caracteres.',
                    }
                    reason = known.get(str(exc)) if isinstance(exc, ValueError) else None
                    if reason is None and isinstance(exc, OSError):
                        reason = 'No se pudo iniciar el navegador.'
                    self.results.append((name, {'error': reason or 'Ocurrió un error al preparar WhatsApp; no conozco la causa.'}))
                else:
                    self.results.append((name, {'error': 'La herramienta de música falló.'}))
                raise
            self.results.append((name, result))
            return result
        return tracked


def format_result(name, result):
    if not isinstance(result, dict):
        return 'No pude verificar el resultado de la música, señor.'
    if result.get('error'):
        return 'No pude completar la solicitud: ' + str(result['error'])
    if name == 'play_music':
        if result.get('requested') is True:
            return 'Ya pedí abrir la canción en Chrome, señor.'
        if result.get('opened') is True and result.get('playing') is True:
            return 'Listo, señor.'
        if result.get('opened') is True:
            return str(result.get('note') or 'Abrí la página, pero no pude confirmar la reproducción.')
        return 'No pude abrir la canción en el navegador, señor.'
    if result.get('paused') is True:
        return 'La música está en pausa, señor.'
    if result.get('stopped') is True:
        return 'Detuve el reproductor, señor.'
    return str(result.get('note') or 'No pude confirmar que se pausara la música, señor.')
