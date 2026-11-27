"""Entrada de arquivos do lote, sem interface: limites, conversão de imagens e separação de páginas.

As funções devolvem dados (ou levantam erro com mensagem pronta); quem pergunta ao usuário é a tela.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

import fitz
import numpy as np
from PIL import Image, ImageOps

from rdf.core import config
from rdf.core.fitz_lock import FITZ_LOCK
from rdf.core.imaging import rectify_document_photo
from rdf.core.io_files import INPUT_EXTENSIONS, validate_input_content
from rdf.core.naming import safe_filename

LOGGER = logging.getLogger('rdf')

MAX_HEADER_WIDTH = 1787  # largura, em pixels, do cabeçalho de uma folha A4 renderizada em 3x
MIN_PAGE_DPI = 196.0  # abaixo disso a imagem seria ampliada demais só para ser lida


@dataclass
class LimitCheck:
    """Resultado da checagem de limites: o que entra, um erro que impede tudo, e arquivos grandes (só aviso)."""

    incoming: list = field(default_factory=list)
    error: tuple | None = None  # (título, mensagem)
    large: list = field(default_factory=list)  # [(nome, MB)]


_PAGE_COUNTS = {}


def input_page_count(path):
    """Páginas do arquivo. Guardado por (caminho, data, tamanho): cada adição ao lote recontava todos os arquivos.

    Uma imagem com vários quadros (TIFF de scanner) vira uma página por quadro, então conta como tal no limite."""
    path = Path(path)
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if key not in _PAGE_COUNTS:
        if path.suffix.lower() == '.pdf':
            with FITZ_LOCK, fitz.open(path) as document:
                count = len(document)
        else:
            with Image.open(path) as image:
                count = getattr(image, 'n_frames', 1)
        if len(_PAGE_COUNTS) >= 2048:
            _PAGE_COUNTS.clear()
        _PAGE_COUNTS[key] = max(1, int(count))
    return _PAGE_COUNTS[key]


def candidates_from(paths):
    """Os arquivos aceitos: pastas viram os arquivos compatíveis dentro delas (sem entrar em subpastas)."""
    found = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            found.extend(sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in INPUT_EXTENSIONS))
        elif path.suffix.lower() in INPUT_EXTENSIONS:
            found.append(path)
    return found


def check_batch_limits(current_sources, paths):
    """Confere os limites de arquivos, tamanho e páginas do lote. current_sources: originais já no lote."""
    current_sources = list(dict.fromkeys(current_sources))
    seen = {str(Path(p).resolve()).casefold() for p in current_sources if Path(p).exists()}
    incoming, oversized, large = [], [], []
    total_pages = 0
    for current in current_sources:
        try:
            total_pages += input_page_count(current)
        except Exception as exc:
            LOGGER.warning('Falha ao contar páginas do lote atual %s: %s', current, exc)
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            continue
        key = str(path.resolve()).casefold()
        if key in seen:
            continue
        seen.add(key)
        incoming.append(str(path))
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > config.MAX_FILE_SIZE_MB:
            oversized.append((path.name, size_mb))
        elif size_mb > config.LARGE_FILE_WARNING_MB:
            large.append((path.name, size_mb))
    final_count = len(current_sources) + len(incoming)
    if final_count > config.MAX_BATCH_FILES:
        return LimitCheck(
            error=(
                'Limite do lote',
                f'O lote ficaria com {final_count} arquivos. O limite é de {config.MAX_BATCH_FILES}.\n'
                'Divida o conteúdo em dois ou mais lotes.',
            )
        )
    if oversized:
        names = '\n'.join(f'- {name} ({size:.1f} MB)' for name, size in oversized[:8])
        return LimitCheck(
            error=('Arquivo acima do limite', f'O limite por arquivo é de {config.MAX_FILE_SIZE_MB} MB.\n\n{names}')
        )
    for path in incoming:
        try:
            total_pages += input_page_count(path)
        except Exception as exc:
            return LimitCheck(
                error=(
                    'Arquivo inválido',
                    f'Não foi possível verificar a quantidade de páginas de {Path(path).name}:\n{exc}',
                )
            )
        if total_pages > config.MAX_BATCH_PAGES:
            return LimitCheck(
                error=(
                    'Limite de páginas',
                    f'O lote ficaria com mais de {config.MAX_BATCH_PAGES} páginas.\nDivida o conteúdo em lotes menores.',
                )
            )
    return LimitCheck(incoming=incoming, large=large)


def large_files_message(large):
    names = '\n'.join(f'- {name} ({size:.1f} MB)' for name, size in large[:8])
    return (
        f'{len(large)} arquivo(s) possuem mais de {config.LARGE_FILE_WARNING_MB} MB.\n'
        f'O processamento poderá demorar mais.\n\n{names}\n\nDeseja continuar?'
    )


def split_pdf_pages(path):
    """Uma página por arquivo, na pasta de temporários do app. Devolve os caminhos criados."""
    source = Path(path)
    token = f'{safe_filename(source.stem)[:40]}_{hashlib.sha1(str(source.resolve()).encode("utf-8")).hexdigest()[:10]}'
    created = []
    with FITZ_LOCK, fitz.open(path) as doc:
        for index in range(len(doc)):
            target = config.SPLIT_DIR / f'{token}_pagina_{index + 1:03d}.pdf'
            target.unlink(missing_ok=True)
            part = fitz.open()
            part.insert_pdf(doc, from_page=index, to_page=index)
            part.save(target)
            part.close()
            created.append(str(target))
    return created


def image_to_pdf(path):
    """Converte uma imagem (com várias páginas, se for o caso) em PDF, endireitando fotos de folhas."""
    source = Path(path)
    digest = hashlib.sha1(str(source.resolve()).encode('utf-8')).hexdigest()[:10]
    target = config.CONVERT_DIR / f'{safe_filename(source.stem)[:40]}_{digest}.pdf'
    target.unlink(missing_ok=True)
    with Image.open(source) as image:
        frames = []
        for index in range(getattr(image, 'n_frames', 1)):
            image.seek(index)
            frame = _flatten_to_rgb(ImageOps.exif_transpose(image))  # a foto do celular vem "deitada" no EXIF
            corrected, changed = rectify_document_photo(np.array(frame))
            frames.append(Image.fromarray(corrected).copy() if changed else frame.copy())
        if not frames:
            raise RuntimeError('Imagem sem quadros válidos.')
        resolution = page_resolution(*frames[0].size)
        frames[0].save(target, 'PDF', save_all=True, append_images=frames[1:], resolution=resolution)
    return str(target)


def _flatten_to_rgb(frame):
    """RGB com fundo branco: um PNG com transparência não pode virar preto ao perder o canal alfa."""
    if frame.mode in ('RGBA', 'LA') or (frame.mode == 'P' and 'transparency' in frame.info):
        rgba = frame.convert('RGBA')
        background = Image.new('RGB', rgba.size, 'white')
        background.paste(rgba, mask=rgba.getchannel('A'))
        return background
    return frame.convert('RGB')


def page_resolution(width, height):
    """DPI da página criada a partir da imagem.

    O cabeçalho é lido renderizando a página em 3x: o tamanho da página decide quantos pixels o Tesseract recebe.
    Uma imagem pequena fica perto do tamanho real (um pouco ampliada). Uma imagem grande, como a de um scanner a
    300 dpi, é reduzida para a largura de uma folha A4 (1787 px no cabeçalho): sem o limite, o OCR de cada
    arquivo levava 4x mais tempo sem ler melhor."""
    return max(MIN_PAGE_DPI, width * 72 * 3 / MAX_HEADER_WIDTH)


def normalize_input_file(path):
    """(caminho interno em PDF, arquivo original, se foi criado um temporário). Levanta ValueError se inválido."""
    validate_input_content(path)
    original = str(Path(path))
    suffix = Path(path).suffix.lower()
    if suffix == '.pdf':
        return original, original, False
    if suffix in INPUT_EXTENSIONS:
        return image_to_pdf(path), original, True
    raise ValueError(f'Formato não suportado: {suffix or "sem extensão"}.')


def pdf_page_total(path):
    with FITZ_LOCK, fitz.open(path) as doc:
        return len(doc)


def is_managed_generated_file(path):
    try:
        resolved = Path(path).resolve()
        return resolved.is_relative_to(config.SPLIT_DIR.resolve()) or resolved.is_relative_to(
            config.CONVERT_DIR.resolve()
        )
    except (OSError, ValueError):
        return False


def cleanup_generated_files(paths):
    """Apaga só temporários criados pelo app (nunca um arquivo do usuário). Devolve os que foram tratados."""
    handled = []
    for path in set(paths):
        if not is_managed_generated_file(path):
            continue
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            LOGGER.warning('Não foi possível remover temporário %s', path, exc_info=True)
        handled.append(str(path))
    return handled
