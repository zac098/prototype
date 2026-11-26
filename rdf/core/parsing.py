"""Leitura de matrícula, nome, mês e confiança a partir do texto do documento."""

import re
import unicodedata
from pathlib import Path


def normalize_text(s):
    s = s.replace('|', ' ').replace('\r', '\n')
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r'\n+', '\n', s)
    return s.strip()


MONTHS_PT = {
    "01": "janeiro",
    "02": "fevereiro",
    "03": "março",
    "04": "abril",
    "05": "maio",
    "06": "junho",
    "07": "julho",
    "08": "agosto",
    "09": "setembro",
    "10": "outubro",
    "11": "novembro",
    "12": "dezembro",
}
MONTH_PATTERN = "|".join(MONTHS_PT.values())
MONTH_OPTIONS = (
    "JANEIRO",
    "FEVEREIRO",
    "MARÇO",
    "ABRIL",
    "MAIO",
    "JUNHO",
    "JULHO",
    "AGOSTO",
    "SETEMBRO",
    "OUTUBRO",
    "NOVEMBRO",
    "DEZEMBRO",
)


def parse_mes_folha(text, filename=""):
    """Extrai o mês do título da folha; usa o nome do arquivo como fallback."""
    flat = re.sub(r'\s+', ' ', normalize_text(text)).lower()
    patterns = [
        rf'folha\s+de\s+ponto[^\n]{{0,100}}?({MONTH_PATTERN})\d?\s*[/\-]\s*(?:19|20)\d{{2}}',
        rf'({MONTH_PATTERN})\d?\s*[/\-]\s*(?:19|20)\d{{2}}',
    ]
    for pattern in patterns:
        found = re.search(pattern, flat, re.I)
        if found:
            return found.group(1).lower()
    # Ex.: Folha_Ponto_NOME_10_2026.pdf
    found = re.search(r'(?:^|[_\- ])(0[1-9]|1[0-2])[_\- ](?:19|20)\d{2}(?:$|[_.\- ])', Path(filename).name)
    return MONTHS_PT.get(found.group(1)) if found else None


def filename_chapa(filename):
    stem = Path(filename).stem
    match = re.fullmatch(r'\s*(\d{4,12})\s*', stem)
    return match.group(1) if match else None


# O rótulo "Chapa/Nome" como o OCR costuma devolvê-lo: "Chapa/Nome", "Chupa/Nomo" e, em fotos de baixa
# resolução, até "Chapalioma" (a barra e o N viram letras).
LABEL_PATTERN = r'ch(?:a|i?u)pa\s*[/|1l-]?[a-z]{0,3}\s*(?:n[o0]|[io]{1,2})m[e0oa]'


def parse_chapa_nome(text, filename=""):
    """Extract registration and name only from document text, never the filename."""
    flat = re.sub(r'\s+', ' ', normalize_text(text))
    label = re.search(LABEL_PATTERN + r'\s*[:.;-]?', flat, re.I)
    if not label:
        return None
    # Standard layout: label, registration, name.
    area = flat[label.end() : label.end() + 260]
    starts_with_next_label = bool(
        re.match(
            r'\s*(?:d[a-z]{0,5}\s+(?:d[aeo]\s+)?admiss|admiss|fun[a-zçã]{2,}|hor[a-zá]{2,}|lota[a-zçã]{2,})', area, re.I
        )
    )
    number = None if starts_with_next_label else re.search(r'(?<!\d)(\d{4,12})(?!\d)', area[:100])
    if number:
        chapa = number.group(1)
        after = area[number.end() :]
    else:
        # OCR may reorder a header as: registration, name, Chapa/Nome, next label.
        before = flat[max(0, label.start() - 220) : label.start()]
        candidates = list(re.finditer(r'(?<!\d)(\d{4,12})(?!\d)', before))
        if not candidates:
            return None
        number = candidates[-1]
        chapa = number.group(1)
        after = before[number.end() :]
    after = after.strip(' :-. _')
    stop_pattern = (
        rf'\b(?:{LABEL_PATTERN}|'
        r'(?:[a-z]{2,12}\s+)?d[aeo]\s+adm[iul][s5]{1,2}[a-zãç]*|adm[iul][s5]{1,2}[a-zãç]*|'
        r'fun[a-zçã]{2,}|hor[a-zá]{2,}|lota[a-zçã]{2,}|'
        r'fim(?:\s+d[aeo])?|contrat[a-z]*|hrs?\s*[/\-]?\s*seg|'
        r'dia\s+da\s+semana|entrada|sa[ií]da|assinatura)\b'
    )
    after = re.split(stop_pattern, after, maxsplit=1, flags=re.I)[0]
    name = ''.join(c for c in after if c.isalpha() or c in " À-ÖØ-öø-ÿ.'-")
    name = re.sub(r'\s+', ' ', name).strip(' .-').upper()
    name = re.sub(r'^(?:CHAPA|NOME)+\s*', '', name).strip()
    if len(name) < 5 or len(name.split()) < 2:
        return None
    return chapa, name, parse_mes_folha(text), 'documento'


def _fold_document_text(value):
    return unicodedata.normalize('NFKD', value or '').encode('ascii', 'ignore').decode('ascii').lower()


def relevant_header_confidence(data, chapa=None):
    """Confidence of the Chapa/Nome line, excluding page-wide noise."""
    texts = data.get('text', [])
    confidences = data.get('conf', [])
    size = min(len(texts), len(confidences))
    groups = {}
    for index in range(size):
        token = str(texts[index]).strip()
        if not token:
            continue
        try:
            confidence = float(confidences[index])
        except (TypeError, ValueError):
            continue
        if confidence < 0:
            continue
        key = tuple(data.get(field, [0] * size)[index] for field in ('block_num', 'par_num', 'line_num'))
        groups.setdefault(key, []).append((token, confidence))
    candidates = []
    for items in groups.values():
        line = ' '.join(token for token, _ in items)
        folded = _fold_document_text(line)
        score = 0
        if re.search(r'ch(?:a|i?u)pa.{0,15}(?:n[o0]|[io]{1,2})m[e0oa]', folded):
            score += 5
        if chapa and re.search(rf'(?<!\d){re.escape(chapa)}(?!\d)', line):
            score += 4
        if re.search(r'(?<!\d)\d{4,12}\s*[-:]', line):
            score += 2
        if score:
            candidates.append((score, sum(value for _, value in items) / len(items) / 100))
    return max(candidates, key=lambda item: (item[0], item[1]))[1] if candidates else 0


def confidence_percent(value):
    return max(0, min(100, int(float(value) * 100 + 0.5)))


def is_ready_confidence(value, minimum=72):
    return confidence_percent(value) >= minimum
