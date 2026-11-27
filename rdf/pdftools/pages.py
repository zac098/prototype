"""Leitura de intervalos de páginas digitados pelo usuário ("1-3, 5, 8-")."""

import re


class PageRangeError(ValueError):
    """Intervalo de páginas inválido; a mensagem já está pronta para o usuário."""


_TOKEN = re.compile(r'^(\d+)?\s*(-)?\s*(\d+)?$')


def parse_page_ranges(text, total, *, allow_duplicates=False):
    """Converte "1-3, 5, 8-" em índices de página (base 0), na ordem digitada.

    - "5" é a página 5; "2-4" são as páginas 2 a 4; "8-" vai da 8 até a última; "-3" são as 3 primeiras.
    - Vírgula, ponto e vírgula e espaço separam os trechos.
    - Páginas repetidas só são mantidas com allow_duplicates=True.
    """
    cleaned = (text or '').strip()
    if not cleaned:
        raise PageRangeError('Informe as páginas, por exemplo: 1-3, 5, 8-')
    # Espaços ao redor do hífen fazem parte do mesmo trecho ("2 - 4").
    cleaned = re.sub(r'\s*-\s*', '-', cleaned)
    pages = []
    seen = set()
    for token in re.split(r'[,;\s]+', cleaned):
        if not token:
            continue
        match = _TOKEN.match(token)
        if not match or not (match.group(1) or match.group(3)):
            raise PageRangeError(f'Trecho inválido: "{token}". Use o formato 1-3, 5, 8-')
        start_text, dash, end_text = match.groups()
        if not dash:
            start = end = int(start_text)
        else:
            start = int(start_text) if start_text else 1
            end = int(end_text) if end_text else total
        if start < 1 or end < 1:
            raise PageRangeError('As páginas começam em 1.')
        if start > end:
            raise PageRangeError(f'Intervalo invertido: "{token}". Escreva o menor número primeiro.')
        for number in (start, end):
            if number > total:
                noun = 'página' if total == 1 else 'páginas'
                raise PageRangeError(f'A página {number} não existe: o PDF tem {total} {noun}.')
        for number in range(start, end + 1):
            if allow_duplicates or number not in seen:
                seen.add(number)
                pages.append(number - 1)
    return pages


def parse_page_groups(text, total):
    """Cada trecho separado por vírgula vira um grupo de páginas: "1-3, 5, 8-" -> [[0,1,2],[4],[7..]]."""
    cleaned = (text or '').strip()
    if not cleaned:
        raise PageRangeError('Informe os intervalos, por exemplo: 1-3, 4-6, 7-')
    groups = []
    for part in re.split(r'[,;]+', cleaned):
        if part.strip():
            groups.append(parse_page_ranges(part, total, allow_duplicates=True))
    if not groups:
        raise PageRangeError('Informe os intervalos, por exemplo: 1-3, 4-6, 7-')
    return groups


def format_page_ranges(indexes, keep_order=False):
    """O contrário de parse_page_ranges: índices (base 0) viram "1-3, 5, 8".

    Sem keep_order, as páginas são ordenadas e repetições somem (seleção). Com keep_order, a sequência é mantida e só
    trechos crescentes e seguidos viram intervalo (ordem personalizada): [2, 0, 1, 3] -> "3, 1-2, 4"."""
    numbers = [int(index) + 1 for index in indexes]
    if not keep_order:
        numbers = sorted(set(numbers))
    parts = []
    start = previous = None
    for number in numbers:
        if previous is not None and number == previous + 1:
            previous = number
            continue
        if start is not None:
            parts.append(str(start) if start == previous else f'{start}-{previous}')
        start = previous = number
    if start is not None:
        parts.append(str(start) if start == previous else f'{start}-{previous}')
    return ', '.join(parts)
