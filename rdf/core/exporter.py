"""Exportação dos arquivos renomeados, sem interface.

Copia (PDF) ou converte em imagens (PNG, JPEG...) cada arquivo do lote para a pasta escolhida, com o nome novo.
Nunca sobrescreve: se o nome já existe, acrescenta (2), (3)... Atestados e declarações vão para subpastas.
"""

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import fitz
from PIL import Image

from rdf.core.batch import CATEGORY_LABELS, READY_STATUSES, normalize_status, output_extension
from rdf.core.fitz_lock import FITZ_LOCK
from rdf.core.naming import safe_filename

LOGGER = logging.getLogger('rdf')
EXPORTABLE_STATUSES = READY_STATUSES | {'REVISAR'}


@dataclass
class ExportResult:
    count: int = 0
    failures: list = field(default_factory=list)  # [(caminho, motivo)]
    separated: dict = field(default_factory=lambda: {'Atestados': 0, 'Declarações': 0})


def export_problems(batch, paths=None):
    """Motivos que impedem a exportação: [(caminho, motivo)]. Vazio se está tudo certo."""
    problems = []
    for path in paths if paths is not None else batch.files:
        status = normalize_status(batch.status(path))
        source = Path(path)
        new = batch.new_name(path)
        if status == 'PENDENTE':
            problems.append((path, 'análise ainda não realizada'))
        elif status == 'NAO RECONHECIDO':
            problems.append((path, 'matrícula ou nome não reconhecido'))
        elif status in {'ERRO', 'FALHOU'}:
            problems.append((path, 'erro durante a leitura do PDF'))
        elif not source.is_file():
            problems.append((path, 'arquivo original não foi encontrado'))
        elif not os.access(source, os.R_OK):
            problems.append((path, 'arquivo original sem permissão de leitura'))
        elif not new.strip():
            problems.append((path, 'novo nome está vazio'))
        elif not safe_filename(new).strip():
            problems.append((path, 'novo nome contém apenas caracteres inválidos'))
    return problems


def exportable_items(batch):
    """[(caminho, nome sem extensão)] dos arquivos que podem ser exportados agora."""
    items = []
    for path in batch.files:
        if batch.status(path) not in EXPORTABLE_STATUSES:
            continue
        new = safe_filename(batch.new_name(path)).strip()
        if new:
            items.append((path, Path(new).stem))
    return items


def planned_export_paths(source, target, output_format):
    fmt = output_format.upper()
    target = Path(target)
    target = target.with_name(target.name.upper())
    if fmt == 'PDF':
        return [target]
    extension = output_extension(fmt)
    with FITZ_LOCK, fitz.open(source) as doc:
        total = len(doc)
    if total <= 1:
        return [target.with_suffix('.' + extension.upper())]
    return [target.with_name(f'{target.stem} - PÁGINA {index + 1:03d}.{extension.upper()}') for index in range(total)]


def _copy_new(source, destination):
    """Copia sem nunca sobrescrever: o arquivo é criado só se não existir (FileExistsError se surgiu no meio)."""
    with open(source, 'rb') as origin, open(destination, 'xb') as target:
        shutil.copyfileobj(origin, target)
    shutil.copystat(source, destination)


def export_source(source, target, output_format):
    fmt = output_format.upper()
    destinations = planned_export_paths(source, target, fmt)
    if fmt == 'PDF':
        _copy_new(source, destinations[0])
        return destinations
    pil_format = 'JPEG' if fmt in {'JPEG', 'JPG'} else fmt
    created = []
    try:
        with FITZ_LOCK, fitz.open(source) as doc:
            for page, destination in zip(doc, destinations):
                pix = page.get_pixmap(matrix=fitz.Matrix(2.2, 2.2), alpha=False)
                image = Image.frombytes('RGB', [pix.width, pix.height], pix.samples)
                options = {'quality': 92, 'optimize': True} if pil_format == 'JPEG' else {}
                # 'xb': como no PDF, nunca sobrescreve um arquivo que tenha aparecido depois da conferência
                with open(destination, 'xb') as handle:
                    created.append(destination)
                    image.save(handle, pil_format, **options)
        return created
    except Exception:
        for destination in created:
            destination.unlink(missing_ok=True)
        raise


def export_batch(batch, out_dir, output_format=None, progress=None):
    """Exporta tudo o que pode ser exportado para out_dir. Erros por arquivo não param os demais.

    progress(feitos, total) é chamado antes de cada arquivo (a tela usa para continuar respondendo)."""
    out = Path(out_dir)
    fmt = (output_format or batch.output_format).upper()
    extension = output_extension(fmt)
    result = ExportResult()
    used = set()
    items = exportable_items(batch)
    for done, (path, base) in enumerate(items):
        if progress:
            progress(done, len(items))
        row = batch.rows.get(path, {})
        category = row.get('category')
        if category not in CATEGORY_LABELS:  # a sessão é um arquivo editável: nada de subpasta inventada
            category = None
        destination = out / category if category else out
        destination.mkdir(parents=True, exist_ok=True)
        candidate, number = base, 2
        while True:
            target = destination / f'{candidate}.{extension}'
            planned = planned_export_paths(path, target, fmt)
            # Uma chave por arquivo planejado, na mesma ordem: cada destino é conferido no lote e no disco.
            keys = [str(p.relative_to(out)).lower() for p in planned]
            if all(key not in used and not p.exists() for key, p in zip(keys, planned)):
                break
            candidate = f'{base} ({number})'
            number += 1
        try:
            made = export_source(path, target, fmt)
            used.update(str(p.relative_to(out)).lower() for p in made)
            result.count += len(made)
            if category:
                result.separated[category] += len(made)
        except Exception as exc:
            LOGGER.exception('Falha ao exportar %s', path)
            result.failures.append((path, str(exc)))
    return result
