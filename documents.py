"""Create local documents in common office and text formats.

Supported out of the box: txt, md, csv, json, rtf (standard library only).
With optional dependencies (see requirements.txt): pdf (fpdf2), docx
(python-docx), xlsx (openpyxl), pptx (python-pptx). Missing dependencies
return an honest error naming the package; nothing is faked.
"""
from __future__ import annotations

import csv
import json
import os
import re

BODY_LIMIT = 1_000_000
ROWS_LIMIT = 1000
COLS_LIMIT = 50
SUPPORTED = ('txt', 'md', 'csv', 'json', 'rtf', 'pdf', 'docx', 'xlsx', 'pptx')


class DocumentError(ValueError):
    pass


def _resolve_path(path):
    if not path or not isinstance(path, str):
        raise DocumentError('Indica la ruta del archivo a crear.')
    path = os.path.expanduser(path.strip())
    if not os.path.isabs(path):
        path = str(os.path.join(os.path.expanduser('~'), 'Documentos', path))
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    return path


def _check_body(body):
    if body is None:
        return ''
    if not isinstance(body, str):
        raise DocumentError('El contenido debe ser texto.')
    if len(body) > BODY_LIMIT:
        raise DocumentError('El contenido supera el límite de caracteres (1 millón).')
    return body


def _check_format(fmt):
    fmt = (fmt or '').strip().lower()
    if fmt in ('doc', 'word'):
        fmt = 'docx'
    if fmt in ('excel', 'xls'):
        fmt = 'xlsx'
    if fmt in ('text', 'texto'):
        fmt = 'txt'
    if fmt in ('markdown',):
        fmt = 'md'
    if fmt in ('powerpoint', 'power point'):
        fmt = 'pptx'
    if fmt not in SUPPORTED:
        raise DocumentError('Formato no admitido. Disponibles: ' + ', '.join(SUPPORTED))
    return fmt


def _rows_from_json(rows_json):
    if rows_json is None:
        return []
    try:
        data = json.loads(rows_json)
    except (json.JSONDecodeError, TypeError) as exc:
        raise DocumentError('La tabla debe venir como JSON válido: una lista de filas, cada una una lista de celdas.') from exc
    if not isinstance(data, list):
        raise DocumentError('La tabla debe ser una lista de filas.')
    rows = []
    for row in data[:ROWS_LIMIT]:
        if isinstance(row, dict):
            row = list(row.values())
        if not isinstance(row, list):
            raise DocumentError('Cada fila de la tabla debe ser una lista de celdas.')
        rows.append(row[:COLS_LIMIT])
    return rows


def _rt_escape(text):
    replacements = {'\\': '\\\\', '{': '\\{', '}': '\\}'}
    out = []
    for char in text:
        if char in replacements:
            out.append(replacements[char])
        elif ord(char) < 128:
            out.append(char)
        else:
            code = ord(char)
            out.append(f'\\u{code if code < 32768 else code - 65536}?')
    return ''.join(out)


def _split_sections(body):
    sections, current = [], {'title': None, 'lines': []}
    for line in (body or '').splitlines():
        if line.startswith('## ') and current is not None:
            sections.append(current)
            current = {'title': line[3:].strip(), 'lines': []}
            continue
        current['lines'].append(line)
    sections.append(current)
    return sections


def create_document(fmt, path, body=None, rows_json=None, header=False, title=None, overwrite=False):
    try:
        return _create_document(fmt, path, body, rows_json, header, title, overwrite)
    except DocumentError as exc:
        return {'error': str(exc)}


def _create_document(fmt, path, body, rows_json, header, title, overwrite):
    fmt = _check_format(fmt)
    body = _check_body(body)
    rows = _rows_from_json(rows_json)
    path = _resolve_path(path)
    if title is None:
        title = os.path.splitext(os.path.basename(path))[0]
    if os.path.exists(path):
        if not overwrite:
            return {'error': f'El archivo ya existe: {path}. Para sobrescribirlo dilo explícitamente y lo confirmo.',
                    'exists': path}
    if fmt == 'txt':
        open(path, 'w', encoding='utf-8').write(body if body else (title + '\n'))
    elif fmt == 'md':
        text = body if body.strip().startswith(('#', '-')) else f'# {title}\n\n{body}'
        open(path, 'w', encoding='utf-8').write(text)
    elif fmt == 'csv':
        data = rows or [line.split(',') for line in body.splitlines() if line.strip()]
        if not data:
            return {'error': 'No hay datos para el CSV. Pasa filas en el parámetro de la tabla o el texto con comas.'}
        with open(path, 'w', encoding='utf-8-sig', newline='') as file:
            writer = csv.writer(file)
            writer.writerows(data)
    elif fmt == 'json':
        if rows:
            payload = {'title': title, 'rows': rows}
        elif body.strip():
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = body  # keep what the user wrote instead of inventing JSON
        else:
            payload = {}
        with open(path, 'w', encoding='utf-8') as file:
            json.dump(payload, file, ensure_ascii=False, indent=2 if not isinstance(payload, str) else None)
    elif fmt == 'rtf':
        paragraphs = re.split(r'\n{2,}', body.strip()) if body.strip() else [title]
        parts = [r'{\rtf1\ansi\ansicpg1252\deff0{\fonttbl{\f0 Helvetica;}}']
        for paragraph in paragraphs:
            parts.append(r'\pard\f0 24 ' + _rt_escape(paragraph).replace('\n', r'\par ') + r'\par')
        parts.append('}')
        open(path, 'w', encoding='utf-8').write('\n'.join(parts))
    elif fmt == 'pdf':
        try:
            from fpdf import FPDF
        except ImportError:
            return {'error': 'Falta la dependencia para PDF: instala con `pip install fpdf2` o vuelve a actualizar con requirements.txt.'}
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=18)
        pdf.add_page()
        pdf.set_font('helvetica', 'B', 20)
        pdf.multi_cell(0, 12, title, new_x='LMARGIN', new_y='NEXT')
        pdf.set_font('helvetica', '', 11)
        pdf.ln(4)
        for section in _split_sections(body):
            if section['title']:
                pdf.set_font('helvetica', 'B', 13)
                pdf.multi_cell(0, 9, _latin(section['title']), new_x='LMARGIN', new_y='NEXT')
                pdf.set_font('helvetica', '', 11)
            for line in section['lines']:
                text = _latin(line)
                if line.startswith('- '):
                    pdf.multi_cell(0, 7, '  -  ' + text[2:], new_x='LMARGIN', new_y='NEXT')
                elif line.strip():
                    pdf.multi_cell(0, 7, text, new_x='LMARGIN', new_y='NEXT')
                else:
                    pdf.ln(3)
        pdf.output(path)
    elif fmt == 'docx':
        try:
            from docx import Document
        except ImportError:
            return {'error': 'Falta la dependencia para Word: instala con `pip install python-docx` o actualiza requirements.txt y reinstala.'}
        document = Document()
        document.add_heading(title, level=0)
        for section in _split_sections(body):
            if section['title']:
                document.add_heading(section['title'], level=1)
            for line in section['lines']:
                if line.startswith('- '):
                    document.add_paragraph(line[2:], style='List Bullet')
                elif line.strip():
                    document.add_paragraph(line)
        document.save(path)
    elif fmt == 'xlsx':
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill
        except ImportError:
            return {'error': 'Falta la dependencia para Excel: instala con `pip install openpyxl` o actualiza requirements.txt y reinstala.'}
        data = rows or [line.split(',') for line in body.splitlines() if line.strip()]
        if not data:
            return {'error': 'No hay datos para la hoja. Pasa filas o un texto con comas.'}
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = (title or 'Hoja1')[:31]
        for row_index, row in enumerate(data, start=1):
            for col_index, cell in enumerate(row, start=1):
                value = cell.strip() if isinstance(cell, str) else cell
                try:
                    value = float(cell) if isinstance(cell, str) and cell.strip().replace('.', '', 1).lstrip('-').isdigit() else cell
                except (TypeError, ValueError):
                    value = cell
                sheet.cell(row=row_index, column=col_index, value=value)
        if header and data:
            fill = PatternFill('solid', fgColor='DCE6F1')
            for col_index in range(1, len(data[0]) + 1):
                cell = sheet.cell(row=1, column=col_index)
                cell.font = Font(bold=True)
                cell.fill = fill
            sheet.freeze_panes = 'A2'
        workbook.save(path)
    elif fmt == 'pptx':
        try:
            from pptx import Presentation
        except ImportError:
            return {'error': 'Falta la dependencia para PowerPoint: instala con `pip install python-pptx` o actualiza requirements.txt y reinstala.'}
        presentation = Presentation()
        first = presentation.slides.add_slide(presentation.slide_layouts[0])
        first.shapes.title.text = title
        if body.strip():
            first.placeholders[1].text = (body.strip().splitlines() or [''])[0][:200]
        for section in _split_sections(body):
            items = [line for line in section['lines'] if line.strip()]
            if not items and not section['title']:
                continue
            slide = presentation.slides.add_slide(presentation.slide_layouts[1])
            slide.shapes.title.text = (section['title'] or title)[:120]
            frame = slide.placeholders[1].text_frame
            frame.clear()
            for index, line in enumerate(items):
                bullet = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
                bullet.text = (line[2:] if line.startswith('- ') else line)[:400]
        presentation.save(path)
    size = os.path.getsize(path)
    return {'created': path, 'format': fmt, 'bytes': size}


def _latin(text):
    return text.encode('latin-1', errors='replace').decode('latin-1')
