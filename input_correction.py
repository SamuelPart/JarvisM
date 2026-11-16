"""Corrector determinista de entrada (tolerante a errores de tipeo y del ASR).

Se aplica tanto a texto escrito como a la transcripción de voz, justo antes
de que el resto del sistema interprete la petición. Filosofía: nunca inventar
intención — solo se «pega» un token a una palabra del vocabulario de comandos
cuando está a ≥78 % de similitud (y tiene ≥4 caracteres); todo lo demás queda
intacto (rutas, URLs, correo, extensiones, números, nombres raros).
"""
from __future__ import annotations

import difflib
import re
import unicodedata

_EXACT = {'alo': 'hola', 'wenas': 'buenas'}

# Vocabulario de intención (sin acentos, ya «foldado») para los comandos que
# el sistema entiende hoy. Deliberadamente incluye los lexemas de las acciones.
_VOCAB = sorted({
    'crear', 'crea', 'archivo', 'archivos', 'documento', 'documentos', 'pdf', 'word',
    'excel', 'powerpoint', 'hoja', 'diapositiva', 'presentacion', 'csv', 'json',
    'tabla', 'texto', 'escritorio', 'carpeta', 'folder',
    'elimina', 'eliminar', 'borra', 'borrar', 'borrado', 'quita', 'limpiar',
    'clima', 'tiempo', 'temperatura', 'lluvia', 'soleado', 'nublado', 'viento',
    'pronostico', 'maxima', 'minima', 'humedad', 'grados',
    'hora', 'fecha', 'hoy', 'manana', 'ayer',
    'abre', 'abrir', 'cierra', 'cerrar', 'captura', 'pantalla', 'screenshot',
    'musica', 'cancion', 'artist', 'album', 'pausa', 'siguiente', 'anterior',
    'prueba', 'prueva', 'puebra',  # palabra de dominio (archivos de prueba); nunca aplastar
    'ahora', 'mismo', 'entonces', 'despues', 'luego',  # palabras comunes vecinas de «hora»; nunca aplastar
    'envie', 'envio', 'enviaste', 'mande', 'mandaste', 'envieste',  # formas conjugadas de «enviar», no aplastar
    'tarde', 'noche', 'manana',  # partes del día / fecha comunes junto a «tarea»; nunca aplastar
    'enviado', 'enviada', 'enviando', 'enviados', 'enviadas', 'mandado', 'mandar', 'mande',  # conjugaciones de enviar
    'volumen', 'reproduce', 'reproducir', 'detente', 'continua', 'pon',
    'recuerda', 'recuerdame', 'recordatorio', 'agenda', 'cita', 'tarea',
    'telefono', 'llamar', 'marca', 'whatsapp', 'mensaje',
    'envia', 'enviar', 'manda', 'correo', 'email', 'gmail', 'enviarme',
    'memoria', 'recordar', 'olvida', 'nombre', 'prefiero', 'prefieres',
    'busca', 'buscar', 'google', 'calcula', 'suma', 'resta', 'multiplica', 'divide',
    'planifica', 'plan', 'orquesta', 'agente',
    'autorizo', 'autoriza', 'aprobar', 'aprueba', 'rechazo', 'rechazado',
    'resume', 'resumen', 'traduce', 'explica', 'explica', 'informe', 'estado',
    'bateria', 'wifi', 'brillo', 'apaga', 'enciende', 'reinicia', 'apagar',
    'hola', 'jarvis',
})

_VOCAB_SET = frozenset(_VOCAB)
_TOKEN = re.compile(r"^([^a-záéíóúüñ]*)([a-záéíóúüñ]+)([^a-záéíóúüñ]*)$", re.IGNORECASE)
_MAX_TOKENS = 26
_MAX_REPLACEMENTS = 6
_MIN_FUZZY_LEN = 5


def fold(text: str) -> str:
    """minúsculas, sin acentos, espacios normalizados — la forma en que el resto del sistema ya trabaja."""
    folded = unicodedata.normalize('NFKD', (text or '').casefold())
    plain = ''.join(char for char in folded if unicodedata.category(char) != 'Mn')
    return re.sub(r'\s+', ' ', plain).strip()


def correct(text: str) -> str:
    """Corrige solo tokens dudosos; conserva mayúsculas, acentos y separadores del original."""
    raw = re.sub(r'\s+', ' ', (text or '').strip())
    if not raw:
        return raw
    pieces = raw.split(' ')
    if len(pieces) > _MAX_TOKENS:
        return raw  # prosa larga: la entiende el modelo; no tocar ni acentos ni nombres
    replaced = 0
    out = []
    for piece in pieces:
        if any(ch in piece for ch in '/\\@~') or any(ch.isdigit() for ch in piece):
            out.append(piece)  # rutas, URLs, correos, porcentajes… intocables
            continue
        match = _TOKEN.match(piece)
        if not match or replaced >= _MAX_REPLACEMENTS:
            out.append(piece)
            continue
        prefix, core, suffix = match.groups()
        stem = fold(core)
        if stem in _VOCAB_SET:
            out.append(piece)
            continue
        if stem in _EXACT:
            out.append(prefix + _EXACT[stem] + suffix)
            replaced += 1
            continue
        if len(stem) < _MIN_FUZZY_LEN:
            out.append(piece)
            continue
        fuzzy = difflib.get_close_matches(stem, _VOCAB, n=1, cutoff=0.80)
        if fuzzy:
            out.append(prefix + fuzzy[0] + suffix)
            replaced += 1
        else:
            out.append(piece)
    return ' '.join(out)
