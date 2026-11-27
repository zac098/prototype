"""Planejamento e execução das ferramentas de PDF, sem nenhuma interface.

Decide onde cada resultado é salvo (sem nunca dois arquivos no mesmo destino), converte os valores digitados nas
opções, executa os trabalhos e resume o resultado em um texto para o usuário. Qualquer tela (Tk, Qt) usa isto.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from rdf.pdftools import ops

LOGGER = logging.getLogger('rdf')


@dataclass
class Summary:
    ok: bool
    text: str
    output_file: Path | None = None
    output_folder: Path | None = None


def parse_int(raw, label):
    """Número digitado (aceita vírgula decimal). Erro com mensagem pronta se não for um número."""
    try:
        return int(float(str(raw).replace(',', '.').strip()))
    except (ValueError, OverflowError):
        raise ops.PdfToolError(f'Digite um número válido em "{label}".') from None


def collect_values(options, raw_values):
    """Valores finais das opções: números convertidos, o resto como veio."""
    values = {}
    for option in options:
        raw = raw_values[option.key]
        values[option.key] = parse_int(raw, option.label) if option.kind == 'int' else raw
    return values


def option_visible(option, current_values):
    """True se a opção deve aparecer, dado o valor atual das outras (visible_if)."""
    if not option.visible_if:
        return True
    key, expected = option.visible_if
    current = current_values.get(key)
    return current in expected if isinstance(expected, tuple) else current == expected


def suggested_name(tool, source):
    return f'{Path(source).stem}{tool.suffix}.{getattr(tool, "output_ext", "pdf")}'


def destination_kind(tool, files):
    """ "save-as" (o usuário escolhe o nome do arquivo) ou "folder" (escolhe a pasta onde salvar)."""
    if tool.mode == 'combine' or (tool.mode == 'each' and len(files) == 1):
        return 'save-as'
    return 'folder'


def jobs_for_save_as(tool, files, target):
    if tool.mode == 'combine':
        return [(list(files), Path(target))]
    return [(files[0], Path(target))]


def jobs_for_folder(tool, files, folder):
    """Um destino por arquivo dentro da pasta. Dois arquivos de mesmo nome (de pastas diferentes) nunca
    recebem o mesmo destino: nada existe em disco ainda, então os nomes já reservados são controlados aqui."""
    folder = Path(folder)
    each = tool.mode == 'each'
    reserved = set()
    jobs = []
    for path in files:
        wanted = folder / (suggested_name(tool, path) if each else f'{Path(path).stem}{tool.suffix}')
        target = ops.unique_path(wanted)
        number = 2
        while str(target).lower() in reserved:
            target = ops.unique_path(wanted.with_name(f'{wanted.stem} ({number}){wanted.suffix}'))
            number += 1
        reserved.add(str(target).lower())
        jobs.append((path, target))
    return jobs


def inspect_file(tool, path):
    """Informações para a lista de arquivos; None se o arquivo não puder ser aberto."""
    path = Path(path)
    try:
        size = path.stat().st_size
        if tool.inputs == 'image':
            from PIL import Image

            with Image.open(path) as picture:
                return {'detail': f'{picture.width}×{picture.height}', 'size': size, 'pages': 1, 'locked': False}
        pages, locked = ops.pdf_info(path)
        if pages < 1 and not locked:
            return None
        return {'detail': 'protegido' if locked else str(pages), 'size': size, 'pages': pages, 'locked': locked}
    except Exception:
        return None


class Cancelled(Exception):
    """O usuário cancelou o trabalho; sai da operação no próximo aviso de andamento."""


def run_jobs(tool, jobs, values, report, cancelled=None):
    """Executa os trabalhos em sequência. report(fração_total, texto) informa o andamento.

    cancelled() (opcional) diz se o usuário pediu para parar: a operação em curso é interrompida no próximo aviso
    de andamento (sem deixar arquivo pela metade) e os trabalhos seguintes nem começam.

    Devolve (arquivos criados, mensagens, falhas [(nome, motivo)], total de trabalhos). Um erro esperado ou
    inesperado em um trabalho não impede os seguintes."""
    total = len(jobs)
    paths, messages, failures = [], [], []
    for index, (source, dest) in enumerate(jobs):
        if cancelled and cancelled():
            break
        label = Path(source[0] if isinstance(source, list) else source).name

        def progress(fraction, text='', index=index):
            if cancelled and cancelled():
                raise Cancelled
            report((index + max(0.0, min(1.0, fraction))) / total, text)

        try:
            result = tool.run(source, dest, values, progress)
            paths.extend(result.paths)
            messages.append(result.message)
        except Cancelled:
            break
        except ops.PdfToolError as exc:
            failures.append((label, str(exc)))
        except Exception as exc:
            LOGGER.exception('Falha na ferramenta %s', tool.id)
            failures.append((label, f'erro inesperado ({exc})'))
        report((index + 1) / total, '')
    return paths, messages, failures, total


def summarize(paths, messages, failures, total):
    """Texto final para o usuário e onde estão os arquivos gerados."""
    if not paths:
        same_reason = len({f[1] for f in failures}) == 1
        detail = (
            failures[0][1]
            if failures and (total == 1 or same_reason)
            else '; '.join(f'{n}: {m}' for n, m in failures[:3])
        )
        return Summary(False, detail or 'Nada foi gerado.')
    output_file = paths[0] if len(paths) == 1 else None
    output_folder = paths[0].parent if len(paths) == 1 else Path(os.path.commonpath([str(p.parent) for p in paths]))
    text = messages[0] if len(messages) == 1 else f'{len(messages)} de {total} arquivos processados.'
    text += f'\nSalvo em: {output_file or output_folder}'
    if failures:
        text += '\nNão foi possível processar: ' + '; '.join(f'{n} ({m})' for n, m in failures[:3])
    return Summary(True, text, output_file, output_folder)
