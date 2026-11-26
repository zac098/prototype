"""Classificação de atestados e declarações por sinais combinados."""

import re
from pathlib import Path

from .parsing import _fold_document_text


def _classification_scores(raw, filename=''):
    """Pontua familias de sinais, evitando depender de um unico modelo de documento."""
    flat = re.sub(r'\s+', ' ', _fold_document_text(raw))
    name = re.sub(r'[_\-.]+', ' ', _fold_document_text(Path(filename).stem))
    timesheet_patterns = (
        r'folha\s+de\s+ponto',
        r'cartao\s+de\s+ponto',
        r'espelho\s+de\s+ponto',
        r'controle\s+de\s+frequencia',
        r'entrada.{0,30}saida',
        r'jornada\s+de\s+trabalho',
        r'chapa.{0,20}nome.{0,80}(?:entrada|saida)',
    )
    if sum(bool(re.search(x, flat)) for x in timesheet_patterns) >= 1:
        return {'Atestados': 0, 'Declarações': 0, 'timesheet': True}
    atestado_groups = (
        (4, (r'\batestado\s+(?:medico|odontologico|de\s+saude)\b', r'\batestado\b')),
        (3, (r'\batesto\s+(?:para|que|a)\b', r'necessita.{0,35}(?:afastamento|repouso)', r'incapacidade\s+laboral')),
        (
            2,
            (
                r'\bcid\s*[-:]?\s*[a-z]?\s*\d',
                r'\bdias?\s+de\s+(?:repouso|afastamento)',
                r'afastad[aeo].{0,30}(?:trabalho|atividade)',
            ),
        ),
        (1, (r'medico\b', r'crm\b', r'cirurgiao\s+dentista', r'cro\b', r'paciente\b')),
    )
    declaracao_groups = (
        (4, (r'\bdeclaracao\s+(?:de\s+)?(?:comparecimento|estagio|presenca|atendimento)\b', r'\bdeclaracao\b')),
        (3, (r'\bdeclaro\s+(?:para|que|a)\b', r'declaramos\s+(?:para|que)', r'compareceu\s+(?:a|ao|nesta|neste)')),
        (2, (r'para\s+os\s+devidos\s+fins', r'permaneceu.{0,40}(?:atendimento|consulta)', r'esteve\s+presente')),
        (1, (r'comprovacao', r'horario\s+de\s+atendimento', r'declaramos')),
    )

    def score(groups):
        total = 0
        for weight, patterns in groups:
            if any(re.search(pattern, flat) for pattern in patterns):
                total += weight
        return total

    a = score(atestado_groups)
    d = score(declaracao_groups)
    # O nome ajuda, mas nunca classifica sozinho: e apenas desempate apos algum sinal do documento.
    if a and re.search(r'\batestad', name):
        a += 2
    if d and re.search(r'\bdeclar', name):
        d += 2
    return {'Atestados': a, 'Declarações': d, 'timesheet': False}


def classify_extra_document(path, text=None):
    """Retorna Atestados, Declarações ou None por evidencias combinadas."""
    if text is None:
        from .ocr import _document_search_text

        text = _document_search_text(path)
    raw = text
    scores = _classification_scores(raw, path)
    if scores['timesheet']:
        return None
    a = scores['Atestados']
    d = scores['Declarações']
    if a >= 4 and a >= d:
        return 'Atestados'
    if d >= 4 and d > a:
        return 'Declarações'
    return None
