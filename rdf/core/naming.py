"""Montagem de nomes de arquivo seguros para exportação."""

import re
import unicodedata
from pathlib import Path

MAX_NAME_LENGTH = 180  # com a pasta e a extensão, deixa folga para o limite de 260 caracteres do Windows
RESERVED_NAMES = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{n}' for n in range(1, 10)), *(f'LPT{n}' for n in range(1, 10))}


def safe_filename(s):
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip(' .')[:MAX_NAME_LENGTH].rstrip(' .')
    if s.split('.')[0].strip().upper() in RESERVED_NAMES:  # o Windows não cria CON, NUL, COM1... (nem com extensão)
        s = f'_{s}'
    return s


def compose_document_filename(path, document_type):
    """Inclui ATESTADO/DECLARAÇÃO no nome, preservando matrícula e sequência."""
    stem = safe_filename(Path(path).stem)
    label = 'ATESTADO' if document_type == 'Atestado' else 'DECLARAÇÃO'
    folded = unicodedata.normalize('NFKD', stem).encode('ascii', 'ignore').decode('ascii')
    cleaned = re.sub(r'(?i)\b(?:ATESTADO|DECLARACAO)\b', ' ', folded)
    cleaned = safe_filename(re.sub(r'\s*-\s*', ' - ', cleaned))
    lead = re.match(r'^\s*(\d{4,12})\b', cleaned)
    sequence = re.search(r'(?:^|\s*-\s*)(\d{1,3})\s*$', cleaned)
    if lead:
        result = f'{lead.group(1)} - {label}'
        if sequence and sequence.group(1) != lead.group(1):
            result += f' {sequence.group(1)}'
        return (safe_filename(result) + '.pdf').upper()
    base = cleaned.strip(' -')
    if not base:
        return (label + '.pdf').upper()
    if label == 'ATESTADO' and re.search(r'(?i)\bATESTADO\b', folded):
        return (safe_filename(stem) + '.pdf').upper()
    if label == 'DECLARAÇÃO' and re.search(r'(?i)\bDECLARACAO\b', folded):
        return (safe_filename(stem) + '.pdf').upper()
    return (safe_filename(f'{base} - {label}') + '.pdf').upper()
