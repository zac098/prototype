"""Lote do renomeador de folhas de ponto, sem nenhuma interface.

Guarda os arquivos do lote, o resultado da leitura de cada um (a "linha"), o status, o nome final e a sessão
salva em disco. Qualquer tela (hoje a Qt) só apresenta o que está aqui e chama estes métodos para agir.

Uma linha (row) é um dicionário: path, chapa, nome, mes, new (nome final), method, conf, status, category,
document_type, manual_name, chapa_source, analysis_page... Sem linha, o arquivo está "Pendente" (não analisado).
"""

import json
import logging
from pathlib import Path

from rdf.core import config
from rdf.core.naming import compose_document_filename, safe_filename
from rdf.core.parsing import confidence_percent, is_ready_confidence

LOGGER = logging.getLogger('rdf')

READY_STATUSES = {'OK', 'APROVADO', 'CORRIGIDO'}
BLOCKING_STATUSES = {'ERRO', 'FALHOU', 'NAO RECONHECIDO', 'PENDENTE'}
FILTERS = ('Todos', 'Prontos', 'Revisar', 'Bloqueados')
CATEGORY_LABELS = {'Atestados': 'Atestado', 'Declarações': 'Declaração'}


# ---- status e nomes (funções puras) ------------------------------------------------------------
def normalize_status(status):
    return (status or '').strip().upper()


def is_blocking_status(status):
    return normalize_status(status) in BLOCKING_STATUSES


def status_tone(status):
    """Como pintar o status: ok (verde), approved (azul), error (vermelho) ou review (amarelo)."""
    normalized = normalize_status(status)
    if normalized in ('OK', 'CORRIGIDO'):
        return 'ok'
    if normalized == 'APROVADO':
        return 'approved'
    if normalized in ('ERRO', 'FALHOU', 'NAO RECONHECIDO'):
        return 'error'
    return 'review'


def output_extension(output_format=None):
    fmt = (output_format or 'PDF').upper()
    if fmt in {'JPG', 'JPEG'}:
        return 'jpg'
    return fmt.lower() if fmt in config.OUTPUT_FORMATS else 'pdf'


def with_output_extension(name, output_format=None):
    """O nome com a extensão do formato escolhido, tudo em maiúsculas."""
    if not name:
        return ''
    path = Path(name).with_suffix('.' + output_extension(output_format))
    return str(path.with_name(path.name.upper()))


def fields_complete(row, options):
    include_chapa, include_nome, include_mes = options
    return (
        (not include_chapa or bool(row.get('chapa')))
        and (not include_nome or bool(row.get('nome')))
        and (not include_mes or bool(row.get('mes')))
    )


def compose_filename(row, options, output_format=None, original_sources=None):
    """Matrícula - Nome - Mês, só com as partes escolhidas; sem nada, usa o nome do arquivo original."""
    include_chapa, include_nome, include_mes = options
    parts = []
    if include_chapa and row.get('chapa'):
        parts.append(row['chapa'])
    if include_nome and row.get('nome'):
        parts.append(row['nome'])
    if include_mes and row.get('mes'):
        parts.append(row['mes'])
    if parts:
        base = safe_filename(' - '.join(parts))
    else:
        source = (original_sources or {}).get(row.get('path', ''), row.get('path', 'arquivo'))
        base = safe_filename(Path(source).stem) or 'arquivo'
    return base.upper() + '.' + output_extension(output_format).upper()


def timesheet_status(row, options):
    """OK só com a chapa vinda do documento, boa confiança e todos os campos escolhidos preenchidos."""
    ready = (
        row.get('chapa_source', 'documento') == 'documento'
        and is_ready_confidence(row.get('conf', 0))
        and fields_complete(row, options)
    )
    return 'OK' if ready else 'REVISAR'


def row_from_result(path, result, options, output_format, original_sources, page=0):
    """Linha do lote a partir do resultado de rdf.core.ocr.analyze_document."""
    parsed = result.get('parsed')
    method, conf, category = result['method'], result['conf'], result.get('category')
    base = {'path': path, 'manual_name': False, 'analysis_page': page}
    if category:
        new = compose_document_filename(original_sources.get(path, path), result['document_type'])
        return {
            **base,
            'chapa': None,
            'nome': None,
            'mes': None,
            'new': with_output_extension(new, output_format),
            'category': category,
            'document_type': result['document_type'],
            'method': method,
            'conf': conf,
            'status': 'OK',
        }
    if parsed:
        row = {
            **base,
            'chapa': parsed[0],
            'nome': parsed[1],
            'mes': parsed[2],
            'chapa_source': parsed[3] if len(parsed) > 3 else 'documento',
            'category': None,
            'document_type': 'Folha de ponto',
            'method': method,
            'conf': conf,
        }
        row['new'] = compose_filename(row, options, output_format, original_sources)
        row['status'] = timesheet_status(row, options)
        return row
    return {
        **base,
        'chapa': None,
        'nome': None,
        'mes': None,
        'new': '',
        'category': None,
        'document_type': 'Não identificado',
        'method': method,
        'conf': conf,
        'status': 'NAO RECONHECIDO',
    }


def error_row(path, error):
    return {
        'path': path,
        'chapa': None,
        'nome': None,
        'mes': None,
        'new': '',
        'method': 'Erro',
        'conf': 0,
        'status': 'ERRO',
        'manual_name': False,
        'error': str(error)[:300],
    }


# ---- o lote ------------------------------------------------------------------------------------
class Batch:
    def __init__(self):
        self.files = []  # caminhos internos (podem ser páginas separadas ou PDFs convertidos de imagem), ordenados
        self.rows = {}  # caminho -> linha (só dos arquivos já lidos)
        self.original_sources = {}  # caminho interno -> arquivo que o usuário escolheu
        self.analysis_pages = {}  # caminho -> página usada na leitura (0 = a primeira)
        self.generated_files = set()  # arquivos temporários criados pelo app (páginas separadas, conversões)
        self.include_chapa = True
        self.include_nome = True
        self.include_mes = True
        self.output_format = 'PDF'
        self.filter_status = 'Todos'
        self.persistence_disabled = False

    # -- opções --
    @property
    def options(self):
        return (self.include_chapa, self.include_nome, self.include_mes)

    def set_options(self, chapa, nome, mes):
        self.include_chapa, self.include_nome, self.include_mes = bool(chapa), bool(nome), bool(mes)

    def set_output_format(self, value):
        value = (value or 'PDF').upper()
        self.output_format = value if value in config.OUTPUT_FORMATS else 'PDF'
        return self.output_format

    # -- consulta --
    def status(self, path):
        row = self.rows.get(path)
        return row.get('status', 'REVISAR') if row else 'Pendente'

    def new_name(self, path):
        row = self.rows.get(path)
        return (row.get('new') or '') if row else ''

    def source(self, path):
        return self.original_sources.get(path, path)

    def display_name(self, path):
        """Nome do arquivo original; se outro arquivo do lote tem o mesmo nome, mostra também a pasta."""
        source = Path(self.source(path))
        same_name = []
        for internal in self.files:
            candidate = Path(self.source(internal))
            if candidate.name.casefold() == source.name.casefold():
                same_name.append(candidate)
        if len({str(item.resolve()).casefold() for item in same_name}) > 1:
            return f'{source.name}  [{source.parent.name}]'
        return source.name

    def confidence_text(self, row):
        return 'N/A' if row.get('category') else f'{confidence_percent(row.get("conf", 0))}%'

    def row_values(self, path):
        """(arquivo, novo nome, leitura, confiança, status) como aparecem na tabela."""
        row = self.rows.get(path)
        if row is None:
            return (self.display_name(path), '', '', '', 'Pendente')
        return (
            self.display_name(path),
            row.get('new', ''),
            row.get('method', ''),
            self.confidence_text(row),
            row.get('status', 'REVISAR'),
        )

    def counts(self):
        """(total, prontos, para revisar, bloqueados)."""
        ready = review = blocked = 0
        for path in self.files:
            status = normalize_status(self.status(path))
            if status in READY_STATUSES:
                ready += 1
            elif is_blocking_status(status):
                blocked += 1
            elif status == 'REVISAR':
                review += 1
        return len(self.files), ready, review, blocked

    def summary_text(self):
        total, ready, review, blocked = self.counts()
        return f'{total} arquivos  |  {ready} prontos  |  {review} para revisar  |  {blocked} bloqueados'

    def matches_filter(self, path, wanted=None):
        wanted = wanted or self.filter_status
        status = normalize_status(self.status(path))
        if wanted == 'Todos':
            return True
        if wanted == 'Prontos':
            return status in READY_STATUSES
        if wanted == 'Revisar':
            return status == 'REVISAR'
        if wanted == 'Bloqueados':
            return is_blocking_status(status)
        return True

    def visible_paths(self, wanted=None):
        return [path for path in self.files if self.matches_filter(path, wanted)]

    # -- arquivos --
    def load(self, paths):
        """Troca o lote inteiro pelos PDFs indicados (sem linhas: tudo pendente)."""
        self.persistence_disabled = False
        self.files = sorted({str(Path(p)) for p in paths if str(p).lower().endswith('.pdf')})
        self.rows = {}
        self.original_sources = {p: self.original_sources.get(p, p) for p in self.files}
        self.analysis_pages = {p: int(self.analysis_pages.get(p, 0)) for p in self.files}
        self.filter_status = 'Todos'

    def add(self, paths):
        """Acrescenta PDFs ao lote mantendo o que já foi lido. Devolve quantos são novos."""
        incoming = [str(Path(p)) for p in paths if str(p).lower().endswith('.pdf')]
        merged = sorted(set(self.files).union(incoming))
        added = len(merged) - len(self.files)
        if not added:
            return 0
        previous = dict(self.rows)
        self.load(merged)
        self.rows = {path: row for path, row in previous.items() if path in self.files}
        return added

    def remove(self, paths):
        """Tira arquivos do lote (os originais nunca são apagados). Devolve os caminhos removidos."""
        removed = [path for path in paths if path in set(self.files)]
        gone = set(removed)
        self.files = [path for path in self.files if path not in gone]
        for path in removed:
            self.rows.pop(path, None)
            self.analysis_pages.pop(path, None)
            self.original_sources.pop(path, None)
        return removed

    def clear(self):
        self.files, self.rows = [], {}
        self.analysis_pages, self.original_sources = {}, {}
        self.generated_files.clear()
        self.filter_status = 'Todos'

    # -- nomes --
    def compose(self, row, output_format=None):
        return compose_filename(row, self.options, output_format or self.output_format, self.original_sources)

    def refresh_names(self):
        """Recalcula os nomes (e o status das folhas) depois de mudar as opções ou o formato.

        As opções só mudam o nome do arquivo: nunca a confiança da leitura nem o status de quem já foi
        aprovado ou corrigido à mão."""
        options = self.options
        for row in self.rows.values():
            failed = row.get('method') in ('Erro', 'Falhou')
            settled = row.get('status') in ('APROVADO', 'CORRIGIDO')
            if row.get('category'):
                row['new'] = with_output_extension(row.get('new', ''), self.output_format)
                if not settled and not failed:
                    row['status'] = 'OK'
            elif not row.get('manual_name'):
                row['new'] = self.compose(row)
                if not failed and not settled:
                    row['status'] = timesheet_status(row, options)

    # -- análise --
    def begin_analysis(self, paths, selected_only):
        """Prepara a análise: guarda um retrato do estado atual (para poder descartar) e limpa as linhas."""
        snapshot = {path: dict(row) for path, row in self.rows.items()}
        if selected_only:
            chosen = set(paths)
            self.rows = {path: row for path, row in self.rows.items() if path not in chosen}
        else:
            self.rows = {}
        return snapshot

    def accept_row(self, row):
        self.rows.pop(row['path'], None)
        self.rows[row['path']] = row

    def set_error(self, path, error):
        self.accept_row(error_row(path, error))

    def restore_snapshot(self, snapshot):
        """Volta ao estado de antes da análise (usado ao cancelar descartando os resultados)."""
        self.rows = {path: dict(snapshot[path]) for path in self.files if path in snapshot}

    def pending(self, paths):
        return [path for path in paths if path in set(self.files) and self.status(path) == 'Pendente']

    # -- ações sobre os selecionados --
    def approve(self, paths):
        """Aprova como folha de ponto quem já tem nome. Pendentes e com erro não podem ser aprovados."""
        changed = 0
        for path in paths:
            row = self.rows.get(path)
            if not row or not (row.get('new') or '').strip() or is_blocking_status(row.get('status')):
                continue
            row['category'] = None
            row['document_type'] = 'Folha de ponto'
            row['status'] = 'APROVADO'
            changed += 1
        return changed

    def approve_as_category(self, paths, category):
        """Corrige a classificação sem inventar matrícula, nome ou mês."""
        label = CATEGORY_LABELS[category]
        changed = 0
        for path in paths:
            row = self.rows.get(path)
            if row is None:
                row = {'path': path, 'chapa': None, 'nome': None, 'mes': None, 'manual_name': False}
                self.rows[path] = row
            row.update(
                {
                    'category': category,
                    'document_type': label,
                    'method': 'Classificação manual',
                    'conf': 1.0,
                    'status': 'APROVADO',
                    'new': with_output_extension(
                        compose_document_filename(self.source(path), label), self.output_format
                    ),
                }
            )
            changed += 1
        return changed

    def mark_review(self, paths):
        changed = 0
        for path in paths:
            row = self.rows.get(path)
            if not row or is_blocking_status(row.get('status')):
                continue
            row['status'] = 'REVISAR'
            changed += 1
        return changed

    def correct(self, path, data):
        """Correção manual de matrícula, nome e mês: o status vira CORRIGIDO."""
        row = self.rows.get(path)
        if row is None:
            row = {'path': path, 'method': 'Manual', 'conf': 1.0, 'manual_name': False}
            self.rows[path] = row
        row.update({key: safe_filename(value or '') for key, value in data.items()})
        row.update(
            {'chapa_source': 'manual', 'method': 'Manual', 'conf': 1.0, 'status': 'CORRIGIDO', 'manual_name': False}
        )
        row['new'] = self.compose(row)
        return row

    # -- sessão --
    def session_data(self):
        rows = []
        for path in self.files:
            row = dict(self.rows.get(path, {'path': path, 'status': 'Pendente'}))
            row.pop('header', None)
            rows.append(row)
        return {
            'version': 2,
            'files': self.files,
            'rows': rows,
            'analysis_pages': self.analysis_pages,
            'generated_files': list(self.generated_files),
            'original_sources': self.original_sources,
            'options': list(self.options),
            'filter': self.filter_status,
            'output_format': self.output_format,
        }

    def save_session(self):
        """Grava a sessão (por cima da anterior, sem nunca deixar o arquivo pela metade). True se gravou."""
        if self.persistence_disabled:
            return False
        try:
            temp = config.SESSION_FILE.with_suffix('.tmp')
            temp.write_text(json.dumps(self.session_data(), ensure_ascii=False, indent=2), encoding='utf-8')
            temp.replace(config.SESSION_FILE)
            return True
        except Exception:
            LOGGER.exception('Falha ao salvar sessão')
            return False

    @staticmethod
    def discard_session_file():
        config.SESSION_FILE.unlink(missing_ok=True)
        config.SESSION_FILE.with_suffix('.tmp').unlink(missing_ok=True)

    def restore_session(self, data, existing):
        """Reconstrói o lote a partir da sessão salva; existing são os arquivos que ainda existem."""
        self.persistence_disabled = False
        opts = data.get('options', [True, True, True])
        self.set_options(*opts[:3])
        self.analysis_pages = {str(k): int(v) for k, v in data.get('analysis_pages', {}).items() if str(k) in existing}
        self.generated_files = {p for p in data.get('generated_files', []) if Path(p).is_file()}
        self.original_sources = {str(k): str(v) for k, v in data.get('original_sources', {}).items()}
        self.load(existing)
        saved = {r.get('path'): r for r in data.get('rows', [])}
        for path in existing:
            row = saved.get(path)
            if not row:
                continue
            row.setdefault('path', path)
            row.setdefault('chapa_source', 'desconhecida')
            row.setdefault('new', '')
            row.setdefault('method', '')
            row.setdefault('conf', 0)
            row.setdefault('status', 'Pendente')
            row.setdefault('manual_name', False)
            if row.get('category') not in (None, *CATEGORY_LABELS):
                row['category'] = None
            if row.get('chapa_source') == 'desconhecida' and row.get('status') == 'OK':
                row['status'] = 'REVISAR'
            self.rows[path] = row
        self.filter_status = data.get('filter', 'Todos')
        self.set_output_format(data.get('output_format', 'PDF'))
        return len(existing)


def read_session_file():
    """A sessão salva, como dicionário; None se não houver. Levanta exceção se estiver danificada."""
    if not config.SESSION_FILE.exists():
        return None
    return json.loads(config.SESSION_FILE.read_text(encoding='utf-8'))
