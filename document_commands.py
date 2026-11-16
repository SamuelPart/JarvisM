"""Deterministic handling of simple create/delete-of-test-file requests.

«créame un archivo pdf de prueba en escritorio» needs no path, no choices and
no model round-trip. Deletion is bounded to files recorded in the local action
ledger as created by JARVIS — never arbitrary user files, never directories.
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path

import action_log
import documents

CREATE_VERBS = r'(?:cr[eé]a|cr[eé]ame|crea|creame|prep[aá]ra|prep[aá]rame|haz|hazme|gen[eé]ra|gen[eé]rame)'
DELETE_VERBS = r'(?:elimina|eliminar|elim[ií]name|b[oó]rrame|borra|borrar|qu[ií]ta|quitar|qu[ií]tame)'

_FORMAT_WORDS = {'pdf': 'pdf', 'word': 'docx', 'docx': 'docx', 'doc': 'docx',
                 'excel': 'xlsx', 'xlsx': 'xlsx', 'xls': 'xlsx',
                 'powerpoint': 'pptx', 'pptx': 'pptx',
                 'csv': 'csv', 'json': 'json', 'markdown': 'md', 'md': 'md',
                 'txt': 'txt', 'texto': 'txt', 'rtf': 'rtf'}

CREATE_MAX = 10


def _format_of(text):
    lowered = text.lower()
    for word, fmt in _FORMAT_WORDS.items():
        if re.search(r'\b' + re.escape(word) + r'\b', lowered):
            return fmt
    return 'pdf'


def _format_filter_of(text):
    lowered = text.lower()
    for word, fmt in _FORMAT_WORDS.items():
        if re.search(r'\b' + re.escape(word) + r'\b', lowered):
            return fmt
    return None


def parse_create(clean):
    """Return {'count', 'format', 'dest'} for «créame … un archivo … de prueba …»."""
    match = re.match(r'^' + CREATE_VERBS + r'\s+(.+)$', (clean or '').strip(), re.I)
    if not match:
        return None
    rest = match.group(1).strip(' .!¡?¿')
    if not re.search(r'\b(prueba|test)\b', rest, re.I):
        return None
    if not re.search(r'\b(archivos?|documentos?|pdfs?|hojas?\s+de\s+c[aá]lculo|presentaciones?)\b', rest, re.I):
        return None
    count_match = re.match(r'^(\d{1,2})\b', rest)
    count = int(count_match.group(1)) if count_match else 1
    if not 1 <= count <= CREATE_MAX:
        return None
    lowered = rest.lower()
    if re.search(r'\b(escritorio|desktop)\b', lowered):
        dest = 'desktop'
    elif re.search(r'\ben\s+(?:mis\s+)?documentos?\b', lowered):
        dest = 'documents'
    else:
        dest = 'desktop'  # what the user means by «en escritorio» every time
    return {'count': count, 'format': _format_of(rest), 'dest': dest}


def _folder_for(dest):
    if dest == 'documents':
        folder = Path.home() / 'Documentos'
        folder.mkdir(parents=True, exist_ok=True)
        return folder
    return documents.desktop_dir()


def _unique_name(folder, ext):
    candidate, index = 'prueba.' + ext, 1
    while (folder / candidate).exists():
        index += 1
        candidate = f'prueba-{index}.{ext}'
    return candidate


def handle_create(command):
    fmt = command['format']
    folder = _folder_for(command['dest'])
    stamp = datetime.now().astimezone().strftime('%d/%m/%Y a las %H:%M')
    body = f'Archivo de prueba creado por JARVIS el {stamp}.'
    results = []
    for _ in range(command['count']):
        name = _unique_name(folder, fmt)  # the filesystem sees each file as it is created
        target = f'escritorio/{name}' if command['dest'] == 'desktop' else str(folder / name)
        result = documents.create_document(fmt, target, body=body, title='Prueba', overwrite=True)
        action_log.record('create_document', {'format': fmt, 'path': result.get('created') or target}, result)
        results.append(result)
    report = documents.creation_report(results)
    return report + ' ¿Necesitas algo más?'


def parse_delete(clean):
    """Return {'format', 'plural', 'prueba'} for «elimina … (los) … archivo(s) …»."""
    match = re.match(r'^' + DELETE_VERBS + r'\s*(.+)$', (clean or '').strip(), re.I)
    if not match:
        return None
    rest = match.group(1).strip(' .!¡?¿')
    provenance = re.search(r'\bque\s+(cre\w+|hiciste)\b', rest, re.I)
    pruebaish = re.search(r'\b(prueba|test)\b', rest, re.I)
    fileish = re.search(r'\b(archivos?|pdfs?|documentos?|word|excel|presentaciones?|hojas?)\b', rest, re.I)
    if not (provenance or (pruebaish and fileish)):
        return None
    plural = bool(re.search(r'\b(los|las|todos|todas)\b', rest.lower()))
    return {'format': _format_filter_of(rest), 'plural': plural,
            'prueba': 'prueba' in rest.lower()}


def delete_candidates(command):
    """Unique existing files recorded in the ledger as created by JARVIS."""
    out = []
    for entry in action_log.entries(200):
        path = (entry.get('detail') or {}).get('created') if isinstance(entry, dict) else None
        if not path:
            continue
        candidate = Path(path)
        if candidate in out or not candidate.is_file():
            continue
        if command['format'] and candidate.suffix.lower().lstrip('.') != command['format']:
            continue
        if command['prueba'] and 'prueba' not in candidate.name.lower():
            continue
        out.append(candidate)
    return out


def delete_paths(paths):
    """Delete exactly the given ledger-verified files; refuse anything inside JARVIS's folder."""
    root = Path(__file__).resolve().parent
    deleted, problems = [], []
    for path in paths:
        target = Path(path)
        try:
            relative = target.resolve().relative_to(root)
        except ValueError:
            relative = None
        if relative is not None:
            problems.append(f'No borro nada dentro de la carpeta de JARVIS: {target}')
            action_log.record('delete_created_file', {'path': str(target)}, {'error': 'dentro de la carpeta de JARVIS'})
            continue
        if not target.is_file():
            problems.append(f'Ya no existe: {target}')
            action_log.record('delete_created_file', {'path': str(target)}, {'error': 'ya no existe'})
            continue
        try:
            target.unlink()
        except OSError as exc:
            problems.append(f'No pude eliminar {target}')
            action_log.record('delete_created_file', {'path': str(target)}, {'error': str(exc)[:120]})
            continue
        deleted.append(str(target))
        action_log.record('delete_created_file', {'path': str(target)}, {'deleted': str(target)})
    parts = []
    if deleted:
        parts.append('Eliminé: ' + ', '.join(deleted))
    if problems:
        parts.append('; '.join(problems))
    return '. '.join(parts) + '.' if parts else 'No eliminé nada.'


def select_delete(command):
    """Return (paths_to_delete, None) or (candidates, question) when ambiguous."""
    files = delete_candidates(command)
    if not files:
        return [], 'No hay ningún archivo creado por mí que coincida; no borro archivos que no creé. ¿Necesitas algo más?'
    if len(files) == 1 or command['plural']:
        return files, None
    listing = ', '.join(f'{index}. {path.name}' for index, path in enumerate(files, 1))
    return files, (f'Hay varios archivos que creé: {listing}. ¿Cuáles elimino: todos, el primero, el segundo…?')


def resolve_delete_choice(clean, files):
    """Answer a pending 'which ones?' question with paths, or None to abandon it."""
    lowered = (clean or '').strip().lower().strip(' .!¡?¿')
    if re.fullmatch(r'(cancela|cancelar|no|ninguno|olv[ií]dalo)', lowered):
        return []
    if re.fullmatch(r'(todos|todas|los\s+dos|los\s+tres|los\s+cuatro|los\s+cinco|ambos|ambas)', lowered):
        return list(files)
    ordinals = {'primero': 1, 'primera': 1, 'segundo': 2, 'segunda': 2, 'tercero': 3,
                'tercera': 3, 'cuarto': 4, 'cuarto': 4, 'quinto': 5, 'último': len(files), 'ultimo': len(files)}
    picked, used = [], set()
    for word, index in ordinals.items():
        if re.search(r'\b' + re.escape(word) + r'\b', lowered) or re.search(r'\b' + str(index) + r'\b', lowered):
            if 1 <= index <= len(files) and index not in used:
                picked.append(files[index - 1])
                used.add(index)
    if picked:
        return picked
    matches = [path for path in files if lowered and lowered in path.name.lower()]
    if matches:
        return matches
    return None
