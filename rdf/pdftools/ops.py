"""Operações de PDF: cada função recebe caminhos e devolve um Result.

Nada aqui conhece a interface. Os erros esperados (senha, intervalo inválido, arquivo
corrompido) viram PdfToolError com mensagem pronta para o usuário.
"""

import contextlib
import io
import os
import re
import secrets
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import fitz
from PIL import Image, ImageOps, ImageSequence

from rdf.core.fitz_lock import FITZ_LOCK
from rdf.pdftools.pages import PageRangeError, parse_page_groups, parse_page_ranges

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.webp', '.gif'}


class PdfToolError(ValueError):
    """Falha esperada de uma ferramenta; a mensagem é mostrada ao usuário."""


@dataclass
class Result:
    paths: list = field(default_factory=list)
    message: str = ''


def _noop(fraction, message=''):
    return None


# ---- utilidades ----------------------------------------------------------------------------


def human_size(size):
    value = float(size)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if value < 1024 or unit == 'GB':
            text = f'{value:.0f} {unit}' if unit == 'B' else f'{value:.1f} {unit}'.replace('.', ',')
            return text
        value /= 1024
    return f'{value:.1f} GB'


def unique_path(path):
    """Devolve path, ou "nome (2).ext" se já existir, sem sobrescrever nada."""
    path = Path(path)
    if not path.exists():
        return path
    for number in range(2, 10000):
        candidate = path.with_name(f'{path.stem} ({number}){path.suffix}')
        if not candidate.exists():
            return candidate
    raise PdfToolError(f'Não foi possível criar um nome livre para "{path.name}".')


@contextlib.contextmanager
def atomic_output(dest):
    """Entrega um caminho temporário e só troca pelo destino quando tudo deu certo.

    Assim um erro no meio nunca deixa um PDF pela metade, e dá para salvar por cima do próprio original.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_name(f'.{dest.stem}.{uuid.uuid4().hex[:8]}.rdf-tmp')
    try:
        yield temp
        os.replace(temp, dest)
    finally:
        temp.unlink(missing_ok=True)


def open_pdf(path, password=None):
    """Abre um PDF; avisa com clareza quando está protegido por senha ou vazio."""
    name = Path(path).name
    try:
        document = fitz.open(path)
    except Exception as exc:
        raise PdfToolError(f'Não foi possível abrir "{name}": {exc}') from exc
    if document.needs_pass and not (password and document.authenticate(password)):
        document.close()
        if password:
            raise PdfToolError(f'Senha incorreta para "{name}".')
        raise PdfToolError(f'"{name}" está protegido por senha. Use "Desbloquear PDF" primeiro.')
    if document.page_count < 1:
        document.close()
        raise PdfToolError(f'"{name}" não tem páginas.')
    return document


@contextlib.contextmanager
def edit_pdf(source, dest, password=None):
    """Abre a origem e prepara a saída. A origem fecha antes de o destino ser gravado,
    então dá para salvar por cima do próprio arquivo (o Windows não deixa trocar um arquivo aberto)."""
    with atomic_output(dest) as temp:
        with open_pdf(source, password) as document:
            yield document, temp


_INFO_CACHE = {}
_INFO_CACHE_MAX = 1024


def pdf_info(path):
    """(páginas, protegido por senha). Usado pela lista de arquivos; nunca levanta erro.

    Guarda o resultado por arquivo (caminho, data e tamanho): a lista de arquivos pergunta isto de novo a cada
    atualização, e abrir todos os PDFs outra vez travava a janela."""
    try:
        stat = os.stat(path)
        key = (str(path), stat.st_mtime_ns, stat.st_size)
    except OSError:
        key = None
    if key is not None and key in _INFO_CACHE:
        return _INFO_CACHE[key]
    try:
        with FITZ_LOCK, fitz.open(path) as document:
            info = (document.page_count, bool(document.needs_pass))
    except Exception:
        return 0, False
    if key is not None:
        if len(_INFO_CACHE) >= _INFO_CACHE_MAX:
            _INFO_CACHE.clear()
        _INFO_CACHE[key] = info
    return info


def _pages(spec, total):
    try:
        return parse_page_ranges(spec, total)
    except PageRangeError as exc:
        raise PdfToolError(str(exc)) from exc


def _save(document, temp, **kwargs):
    document.save(temp, garbage=3, deflate=True, **kwargs)


# ---- organizar -----------------------------------------------------------------------------


def merge_pdfs(sources, dest, progress=_noop):
    if len(sources) < 2:
        raise PdfToolError('Adicione pelo menos 2 arquivos PDF para unir.')
    with atomic_output(dest) as temp:
        merged = fitz.open()
        try:
            for index, source in enumerate(sources):
                progress(index / len(sources), f'Unindo {Path(source).name}')
                with open_pdf(source) as document:
                    merged.insert_pdf(document)
            _save(merged, temp)
            total = merged.page_count
        finally:
            merged.close()
    return Result([Path(dest)], f'{len(sources)} arquivos unidos em um PDF de {total} páginas.')


def split_pdf(source, out_dir, mode, spec='', every=1, progress=_noop):
    """mode: "ranges" (um arquivo por intervalo), "every" (a cada N páginas) ou "each" (uma página por arquivo)."""
    source = Path(source)
    out_dir = Path(out_dir)
    created = []
    with open_pdf(source) as document:
        total = document.page_count
        if mode == 'ranges':
            try:
                groups = parse_page_groups(spec, total)
            except PageRangeError as exc:
                raise PdfToolError(str(exc)) from exc
        elif mode == 'every':
            step = int(every)
            if step < 1:
                raise PdfToolError('Informe quantas páginas cada arquivo deve ter (1 ou mais).')
            groups = [list(range(start, min(start + step, total))) for start in range(0, total, step)]
        else:
            groups = [[index] for index in range(total)]
        out_dir.mkdir(parents=True, exist_ok=True)
        digits = max(2, len(str(len(groups))))
        for number, group in enumerate(groups, start=1):
            progress((number - 1) / len(groups), f'Gerando parte {number} de {len(groups)}')
            if mode == 'each':
                label = f'pagina_{group[0] + 1:0{len(str(total))}d}'
            elif mode == 'ranges':
                label = f'paginas_{group[0] + 1}-{group[-1] + 1}' if len(group) > 1 else f'pagina_{group[0] + 1}'
            else:
                label = f'parte_{number:0{digits}d}'
            target = unique_path(out_dir / f'{source.stem}_{label}.pdf')
            part = fitz.open()
            try:
                for index in group:
                    part.insert_pdf(document, from_page=index, to_page=index)
                with atomic_output(target) as temp:
                    _save(part, temp)
            finally:
                part.close()
            created.append(target)
    return Result(created, f'{len(created)} arquivos criados.')


def select_pages(source, dest, spec, keep=True, progress=_noop):
    """keep=True extrai as páginas indicadas; keep=False remove as indicadas e mantém o resto."""
    with edit_pdf(source, dest) as (document, temp):
        total = document.page_count
        chosen = _pages(spec, total)
        if keep:
            order = chosen
        else:
            removed = set(chosen)
            order = [index for index in range(total) if index not in removed]
            if not order:
                raise PdfToolError('Não dá para remover todas as páginas do PDF.')
        document.select(order)
        _save(document, temp)
    verb = 'extraída' if keep else 'mantida'
    noun = f'{len(order)} página' + ('s' if len(order) != 1 else '')
    return Result([Path(dest)], f'{noun} {verb}{"s" if len(order) != 1 else ""} (de {total}).')


def reorder_pages(source, dest, mode, spec='', progress=_noop):
    """mode: "reverse" inverte a ordem; "custom" usa a ordem digitada (páginas fora da lista são descartadas)."""
    with edit_pdf(source, dest) as (document, temp):
        total = document.page_count
        if mode == 'reverse':
            order = list(range(total - 1, -1, -1))
        else:
            try:
                order = parse_page_ranges(spec, total, allow_duplicates=True)
            except PageRangeError as exc:
                raise PdfToolError(str(exc)) from exc
        document.select(order)
        _save(document, temp)
    return Result([Path(dest)], f'PDF reorganizado com {len(order)} páginas.')


# ---- otimizar ------------------------------------------------------------------------------

COMPRESSION_LEVELS = {
    'Baixa (melhor qualidade)': (None, 0),
    'Recomendada': (1600, 70),
    'Extrema (menor tamanho)': (1100, 45),
}


def _recompress_images(document, max_side, quality, progress):
    seen = set()
    total = document.page_count
    for number, page in enumerate(document):
        progress(0.9 * number / total, f'Otimizando imagens da página {number + 1} de {total}')
        for image in page.get_images(full=True):
            xref, smask = image[0], image[1]
            if xref in seen or smask:  # imagens com transparência ficam como estão
                continue
            seen.add(xref)
            try:
                info = document.extract_image(xref)
                if not info or info.get('bpc', 8) == 1 or info.get('ext') in ('jpx', 'jb2'):
                    continue
                original = info['image']
                with Image.open(io.BytesIO(original)) as picture:
                    if picture.mode == 'P' or picture.mode.endswith('A'):
                        continue
                    picture = picture.convert('L' if picture.mode == 'L' else 'RGB')
                    if max(picture.size) > max_side:
                        picture.thumbnail((max_side, max_side), Image.LANCZOS)
                    buffer = io.BytesIO()
                    picture.save(buffer, 'JPEG', quality=quality, optimize=True)
                if len(buffer.getvalue()) < len(original) * 0.95:
                    page.replace_image(xref, stream=buffer.getvalue())
            except Exception:
                continue  # uma imagem estranha não pode derrubar a compressão inteira


def compress_pdf(source, dest, level='Recomendada', progress=_noop):
    max_side, quality = COMPRESSION_LEVELS.get(level, COMPRESSION_LEVELS['Recomendada'])
    before = Path(source).stat().st_size
    with edit_pdf(source, dest) as (document, temp):
        if max_side:
            _recompress_images(document, max_side, quality, progress)
        progress(0.95, 'Gravando o PDF')
        document.save(temp, garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, clean=True)
    after = Path(dest).stat().st_size
    if after >= before:
        return Result([Path(dest)], f'O arquivo já estava otimizado ({human_size(before)}); o tamanho quase não mudou.')
    saved = round(100 * (before - after) / before)
    return Result([Path(dest)], f'De {human_size(before)} para {human_size(after)} (redução de {saved}%).')


def repair_pdf(source, dest, progress=_noop):
    with atomic_output(dest) as temp:
        try:
            document = fitz.open(source)
        except Exception as exc:
            raise PdfToolError(f'Não foi possível recuperar "{Path(source).name}": {exc}') from exc
        with document:
            if document.needs_pass:
                raise PdfToolError('O PDF está protegido por senha. Use "Desbloquear PDF" primeiro.')
            if document.page_count < 1:
                raise PdfToolError('Nada para recuperar: o arquivo não tem páginas legíveis.')
            was_repaired = document.is_repaired
            document.save(temp, garbage=4, deflate=True, clean=True)
    message = (
        'A estrutura do arquivo estava danificada e foi reconstruída.'
        if was_repaired
        else 'Nenhum dano encontrado; o arquivo foi regravado limpo.'
    )
    return Result([Path(dest)], message)


OCR_PAGE_TIMEOUT = 180  # segundos por página: um Tesseract travado não prende a ferramenta para sempre
OCR_LANGUAGES = {'Português + Inglês': 'por+eng', 'Português': 'por', 'Inglês': 'eng'}


def ocr_pdf(source, dest, language='Português + Inglês', dpi=200, progress=_noop):
    """Torna o PDF pesquisável: cada página vira imagem com uma camada invisível de texto (Tesseract)."""
    import pytesseract

    lang = OCR_LANGUAGES.get(language, 'por+eng')
    output = fitz.open()
    try:
        with open_pdf(source) as document:
            total = document.page_count
            for number, page in enumerate(document):
                progress(number / total, f'Reconhecendo texto da página {number + 1} de {total}')
                pixmap = page.get_pixmap(dpi=int(dpi))
                picture = Image.frombytes('RGB', (pixmap.width, pixmap.height), pixmap.samples)
                try:
                    data = pytesseract.image_to_pdf_or_hocr(
                        picture, lang=lang, extension='pdf', timeout=OCR_PAGE_TIMEOUT
                    )
                except pytesseract.TesseractNotFoundError as exc:
                    raise PdfToolError(
                        'O Tesseract OCR não foi encontrado. Instale-o para usar esta ferramenta.'
                    ) from exc
                except pytesseract.TesseractError as exc:
                    raise PdfToolError(f'Falha no OCR (idioma "{lang}" instalado?): {exc}') from exc
                except RuntimeError as exc:
                    if 'timeout' in str(exc).lower():
                        raise PdfToolError(
                            f'O Tesseract demorou mais de {OCR_PAGE_TIMEOUT} s na página {number + 1} e foi interrompido.'
                        ) from exc
                    raise
                with fitz.open('pdf', data) as recognized:
                    output.insert_pdf(recognized)
        with atomic_output(dest) as temp:
            _save(output, temp)
    finally:
        output.close()
    return Result([Path(dest)], 'Texto reconhecido: agora é possível pesquisar e copiar o conteúdo.')


# ---- converter -----------------------------------------------------------------------------

PAGE_SIZES = {'Ajustar à imagem': None, 'A4': (595, 842), 'Carta': (612, 792)}
MARGINS = {'Nenhuma': 0, 'Pequena': 18, 'Grande': 40}


def _image_frames(path):
    """Cada quadro da imagem como (bytes, formato, largura, altura, dpi), já com a rotação do EXIF aplicada."""
    try:
        picture = Image.open(path)
    except Exception as exc:
        raise PdfToolError(f'"{Path(path).name}" não é uma imagem válida: {exc}') from exc
    with picture:
        dpi = picture.info.get('dpi', (0, 0))[0] or 0
        is_jpeg = picture.format == 'JPEG'
        for frame in ImageSequence.Iterator(picture):
            frame = ImageOps.exif_transpose(frame.copy())
            if frame.mode in ('RGBA', 'LA', 'P'):
                rgba = frame.convert('RGBA')
                flat = Image.new('RGB', rgba.size, 'white')
                flat.paste(rgba, mask=rgba.getchannel('A'))
                frame = flat
            elif frame.mode not in ('RGB', 'L'):
                frame = frame.convert('RGB')
            buffer = io.BytesIO()
            if is_jpeg:
                frame.save(buffer, 'JPEG', quality=95)
            else:
                frame.save(buffer, 'PNG')
            yield buffer.getvalue(), frame.width, frame.height, dpi


def images_to_pdf(
    sources, dest, page_size='Ajustar à imagem', orientation='Automática', margin='Nenhuma', progress=_noop
):
    if not sources:
        raise PdfToolError('Adicione pelo menos uma imagem.')
    fixed = PAGE_SIZES.get(page_size)
    gap = MARGINS.get(margin, 0)
    output = fitz.open()
    try:
        for index, source in enumerate(sources):
            progress(index / len(sources), f'Adicionando {Path(source).name}')
            for data, width, height, dpi in _image_frames(source):
                if fixed is None:
                    scale = 72 / dpi if 72 <= dpi <= 600 else 0.75
                    page_w, page_h = width * scale + 2 * gap, height * scale + 2 * gap
                    longest = max(page_w, page_h)
                    if longest > 1800:  # fotos de celular não viram páginas gigantes
                        page_w, page_h = page_w * 1800 / longest, page_h * 1800 / longest
                else:
                    page_w, page_h = fixed
                    landscape = orientation == 'Paisagem' or (orientation == 'Automática' and width > height)
                    if landscape:
                        page_w, page_h = page_h, page_w
                page = output.new_page(width=page_w, height=page_h)
                box = fitz.Rect(gap, gap, page_w - gap, page_h - gap)
                ratio = min(box.width / width, box.height / height)
                shown = fitz.Rect(0, 0, width * ratio, height * ratio)
                shown.x0 += box.x0 + (box.width - shown.width) / 2
                shown.x1 += box.x0 + (box.width - shown.width) / 2
                shown.y0 += box.y0 + (box.height - shown.height) / 2
                shown.y1 += box.y0 + (box.height - shown.height) / 2
                page.insert_image(shown, stream=data)
        count = output.page_count
        with atomic_output(dest) as temp:
            _save(output, temp)
    finally:
        output.close()
    return Result([Path(dest)], f'PDF criado com {count} página' + ('s.' if count != 1 else '.'))


def pdf_to_images(source, out_dir, mode='Páginas como imagens', image_format='JPG', dpi=150, spec='', progress=_noop):
    source = Path(source)
    out_dir = Path(out_dir)
    extension = 'png' if image_format.upper() == 'PNG' else 'jpg'
    created = []
    with open_pdf(source) as document:
        out_dir.mkdir(parents=True, exist_ok=True)
        if mode == 'Extrair imagens do PDF':
            seen = set()
            for number, page in enumerate(document):
                progress(number / document.page_count, f'Procurando imagens na página {number + 1}')
                for image in page.get_images(full=True):
                    xref = image[0]
                    if xref in seen:
                        continue
                    seen.add(xref)
                    try:
                        info = document.extract_image(xref)
                    except Exception:
                        continue
                    if not info:
                        continue
                    target = unique_path(out_dir / f'{source.stem}_imagem_{len(created) + 1:03d}.{info["ext"]}')
                    target.write_bytes(info['image'])
                    created.append(target)
            if not created:
                raise PdfToolError(
                    'Este PDF não contém imagens embutidas. Use "Páginas como imagens" para convertê-lo.'
                )
            return Result(created, f'{len(created)} imagens extraídas.')
        indexes = _pages(spec, document.page_count) if (spec or '').strip() else range(document.page_count)
        indexes = list(indexes)
        digits = len(str(document.page_count))
        for position, index in enumerate(indexes):
            progress(position / len(indexes), f'Convertendo página {index + 1}')
            pixmap = document[index].get_pixmap(dpi=int(dpi), alpha=False)
            target = unique_path(out_dir / f'{source.stem}_pagina_{index + 1:0{digits}d}.{extension}')
            if extension == 'jpg':
                picture = Image.frombytes('RGB', (pixmap.width, pixmap.height), pixmap.samples)
                picture.save(target, 'JPEG', quality=92, dpi=(int(dpi), int(dpi)))
            else:
                pixmap.save(target)
            created.append(target)
    return Result(created, f'{len(created)} imagens criadas.')


def pdf_to_text(source, dest, layout='Texto corrido', progress=_noop):
    """Grava o texto do PDF num arquivo .txt (UTF-8), com um separador por página.

    "Manter a disposição" tenta preservar colunas e espaços (bom para tabelas); "Texto corrido" junta o texto na
    ordem de leitura. PDFs escaneados não têm texto: o erro sugere o OCR antes."""
    pages = []
    with open_pdf(source) as document:
        total = document.page_count
        for number, page in enumerate(document):
            progress(number / total, f'Lendo o texto da página {number + 1} de {total}')
            if layout == 'Manter a disposição':
                text = page.get_text('text', sort=True, flags=fitz.TEXT_PRESERVE_WHITESPACE)
            else:
                text = page.get_text('text', sort=True)
            pages.append(text.rstrip())
    if not any(text.strip() for text in pages):
        raise PdfToolError(
            f'"{Path(source).name}" não tem texto para extrair (parece escaneado). '
            'Use antes "OCR - PDF pesquisável" e depois esta ferramenta.'
        )
    body = '\n\n'.join(f'===== Página {number} =====\n{text}' for number, text in enumerate(pages, start=1))
    with atomic_output(dest) as temp:
        Path(temp).write_text(body + '\n', encoding='utf-8-sig')  # com BOM: o Bloco de Notas acerta os acentos
    filled = sum(1 for text in pages if text.strip())
    return Result([Path(dest)], f'Texto de {filled} de {total} páginas salvo em .txt.')


# ---- editar --------------------------------------------------------------------------------

ROTATIONS = {'90° para a direita': 90, '180°': 180, '90° para a esquerda': 270}


def rotate_pdf(source, dest, angle='90° para a direita', spec='', progress=_noop):
    degrees = ROTATIONS.get(angle, 90)
    with edit_pdf(source, dest) as (document, temp):
        indexes = _pages(spec, document.page_count) if (spec or '').strip() else range(document.page_count)
        indexes = list(indexes)
        for index in indexes:
            page = document[index]
            page.set_rotation((page.rotation + degrees) % 360)
        _save(document, temp)
    return Result([Path(dest)], f'{len(indexes)} página' + ('s giradas.' if len(indexes) != 1 else ' girada.'))


def crop_pdf(source, dest, top=0.0, bottom=0.0, left=0.0, right=0.0, progress=_noop):
    """Margens em milímetros, medidas a partir da página como ela aparece na tela."""
    mm = 72 / 25.4
    top, bottom, left, right = (max(0.0, float(value)) * mm for value in (top, bottom, left, right))
    if not any((top, bottom, left, right)):
        raise PdfToolError('Informe quanto cortar em pelo menos uma das margens.')
    with edit_pdf(source, dest) as (document, temp):
        for page in document:
            visible = page.rect
            if left + right >= visible.width - 10 or top + bottom >= visible.height - 10:
                raise PdfToolError('As margens são maiores do que a página; reduza os valores.')
            box = fitz.Rect(visible.x0 + left, visible.y0 + top, visible.x1 - right, visible.y1 - bottom)
            page.set_cropbox(box * page.derotation_matrix)
        _save(document, temp)
    return Result([Path(dest)], 'Margens cortadas em todas as páginas.')


NUMBER_POSITIONS = (
    'Inferior centralizado',
    'Inferior direita',
    'Inferior esquerda',
    'Superior centralizado',
    'Superior direita',
    'Superior esquerda',
)
NUMBER_FORMATS = ('1', 'Página 1', 'Página 1 de N', '1 / N')


def _format_number(style, number, total):
    return {
        'Página 1': f'Página {number}',
        'Página 1 de N': f'Página {number} de {total}',
        '1 / N': f'{number} / {total}',
    }.get(style, str(number))


def add_page_numbers(
    source,
    dest,
    position='Inferior centralizado',
    style='Página 1 de N',
    first=1,
    start_page=1,
    size=10,
    progress=_noop,
):
    with edit_pdf(source, dest) as (document, temp):
        total = document.page_count
        if not 1 <= int(start_page) <= total:
            raise PdfToolError(f'"Começar na página" deve estar entre 1 e {total}.')
        size = max(6, min(48, int(size)))
        margin = 30
        for index in range(int(start_page) - 1, total):
            page = document[index]
            text = _format_number(
                style, int(first) + index - (int(start_page) - 1), int(first) + total - int(start_page)
            )
            width = fitz.get_text_length(text, fontname='helv', fontsize=size)
            area = page.rect
            if 'direita' in position:
                x = area.x1 - margin - width
            elif 'esquerda' in position:
                x = area.x0 + margin
            else:
                x = (area.x0 + area.x1 - width) / 2
            y = area.y0 + margin + size if position.startswith('Superior') else area.y1 - margin
            point = fitz.Point(x, y) * page.derotation_matrix
            page.insert_text(
                point, text, fontsize=size, fontname='helv', color=(0.15, 0.15, 0.15), rotate=page.rotation
            )
            progress((index + 1) / total, f'Numerando página {index + 1} de {total}')
        _save(document, temp)
    return Result([Path(dest)], 'Números de página adicionados.')


WATERMARK_COLORS = {
    'Cinza': (0.5, 0.5, 0.5),
    'Vermelho': (0.8, 0.1, 0.1),
    'Azul': (0.1, 0.3, 0.75),
    'Preto': (0, 0, 0),
}


def add_watermark(source, dest, text, size=60, opacity=30, angle='Diagonal', color='Cinza', progress=_noop):
    text = (text or '').strip()
    if not text:
        raise PdfToolError('Digite o texto da marca d\'água.')
    size = max(8, min(200, int(size)))
    alpha = max(5, min(100, int(opacity))) / 100
    rgb = WATERMARK_COLORS.get(color, WATERMARK_COLORS['Cinza'])
    visual_angle = 45 if angle == 'Diagonal' else 0  # diagonal subindo da esquerda para a direita
    with edit_pdf(source, dest) as (document, temp):
        total = document.page_count
        width = fitz.get_text_length(text, fontname='helv', fontsize=size)
        for index, page in enumerate(document):
            center = (page.rect.tl + page.rect.br) / 2
            origin = fitz.Point(center.x - width / 2, center.y + size * 0.3)
            pivot = center * page.derotation_matrix
            point = origin * page.derotation_matrix
            page.insert_text(
                point,
                text,
                fontsize=size,
                fontname='helv',
                color=rgb,
                fill_opacity=alpha,
                stroke_opacity=alpha,
                rotate=page.rotation,
                morph=(pivot, fitz.Matrix(visual_angle)) if visual_angle else None,
                overlay=True,
            )
            progress((index + 1) / total, f'Aplicando marca d\'água na página {index + 1} de {total}')
        _save(document, temp)
    return Result([Path(dest)], 'Marca d\'água aplicada em todas as páginas.')


def grayscale_pdf(source, dest, progress=_noop):
    """Converte textos, desenhos e imagens para tons de cinza, mantendo o texto pesquisável (bom para imprimir)."""
    with edit_pdf(source, dest) as (document, temp):
        total = document.page_count
        for number, page in enumerate(document):
            progress(0.9 * number / total, f'Convertendo a página {number + 1} de {total}')
            page.recolor(1)
        progress(0.95, 'Gravando o PDF')
        _save(document, temp)
    return Result(
        [Path(dest)], f'{total} página' + ('s convertidas' if total != 1 else ' convertida') + ' para tons de cinza.'
    )


PAPER_SIZES = {'A4': (595.0, 842.0), 'Carta': (612.0, 792.0), 'Ofício': (612.0, 1008.0), 'A3': (842.0, 1191.0)}
SHEET_LAYOUTS = {'2 por folha': (2, 1), '4 por folha': (2, 2), '6 por folha': (3, 2), '9 por folha': (3, 3)}


def _sheet_size(paper, landscape):
    width, height = PAPER_SIZES.get(paper, PAPER_SIZES['A4'])
    return (height, width) if landscape else (width, height)


def n_up_pdf(source, dest, layout='2 por folha', paper='A4', border=False, progress=_noop):
    """Várias páginas em cada folha (economiza papel ao imprimir). A ordem é da esquerda para a direita, de cima para
    baixo; cada página mantém a proporção e fica centrada no seu espaço."""
    columns, rows = SHEET_LAYOUTS.get(layout, SHEET_LAYOUTS['2 por folha'])
    per_sheet = columns * rows
    output = fitz.open()
    try:
        with open_pdf(source) as document:
            total = document.page_count
            first = document[0].rect
            portrait_pages = first.height >= first.width
            # 2 e 6 por folha ficam melhores deitados (páginas em pé lado a lado); 4 e 9, em pé.
            landscape = (columns > rows) == portrait_pages
            sheet_w, sheet_h = _sheet_size(paper, landscape)
            if not landscape and columns > rows:
                columns, rows = rows, columns
            elif landscape and rows > columns:
                columns, rows = rows, columns
            margin, gap = 18.0, 8.0
            cell_w = (sheet_w - 2 * margin - (columns - 1) * gap) / columns
            cell_h = (sheet_h - 2 * margin - (rows - 1) * gap) / rows
            sheet = None
            for index in range(total):
                progress(index / total, f'Montando a página {index + 1} de {total}')
                position = index % per_sheet
                if position == 0:
                    sheet = output.new_page(width=sheet_w, height=sheet_h)
                row, column = divmod(position, columns)
                cell = fitz.Rect(
                    margin + column * (cell_w + gap),
                    margin + row * (cell_h + gap),
                    margin + column * (cell_w + gap) + cell_w,
                    margin + row * (cell_h + gap) + cell_h,
                )
                sheet.show_pdf_page(cell, document, index, keep_proportion=True)
                if border:
                    sheet.draw_rect(cell, color=(0.75, 0.75, 0.75), width=0.6)
        sheets = output.page_count
        with atomic_output(dest) as temp:
            _save(output, temp)
    finally:
        output.close()
    return Result([Path(dest)], f'{total} páginas em {sheets} folha' + ('s.' if sheets != 1 else '.'))


def fit_to_paper(source, dest, paper='A4', progress=_noop):
    """Deixa todas as páginas no mesmo tamanho de papel (A4, Carta...), ampliando ou reduzindo o conteúdo sem
    distorcer. Cada página mantém a sua orientação (em pé ou deitada)."""
    output = fitz.open()
    try:
        with open_pdf(source) as document:
            total = document.page_count
            for index, page in enumerate(document):
                progress(index / total, f'Ajustando a página {index + 1} de {total}')
                visible = page.rect  # já considera a rotação da página
                width, height = _sheet_size(paper, visible.width > visible.height)
                target = output.new_page(width=width, height=height)
                target.show_pdf_page(target.rect, document, index, keep_proportion=True)
        with atomic_output(dest) as temp:
            _save(output, temp)
    finally:
        output.close()
    return Result(
        [Path(dest)], f'{total} página' + ('s ajustadas' if total != 1 else ' ajustada') + f' ao tamanho {paper}.'
    )


# ---- segurança -----------------------------------------------------------------------------


ALL_PERMISSIONS = fitz.PDF_PERM_PRINT | fitz.PDF_PERM_COPY | fitz.PDF_PERM_MODIFY | fitz.PDF_PERM_ANNOTATE


def protect_pdf(
    source, dest, password, owner_password='', allow_print=True, allow_copy=False, allow_edit=False, progress=_noop
):
    if not password:
        raise PdfToolError('Digite a senha para abrir o PDF.')
    permissions = fitz.PDF_PERM_ACCESSIBILITY
    if allow_print:
        permissions |= fitz.PDF_PERM_PRINT
    if allow_copy:
        permissions |= fitz.PDF_PERM_COPY
    if allow_edit:
        permissions |= fitz.PDF_PERM_MODIFY | fitz.PDF_PERM_ANNOTATE
    # Com a mesma senha nas duas funções, quem abre o PDF entra como administrador e as restrições
    # não valem. Sem senha de administrador, usa uma aleatória (descartada): as permissões passam a valer.
    owner = owner_password or (
        secrets.token_urlsafe(24) if permissions & ALL_PERMISSIONS != ALL_PERMISSIONS else password
    )
    with edit_pdf(source, dest) as (document, temp):
        document.save(
            temp,
            garbage=3,
            deflate=True,
            encryption=fitz.PDF_ENCRYPT_AES_256,
            user_pw=password,
            owner_pw=owner,
            permissions=permissions,
        )
    return Result(
        [Path(dest)], 'PDF protegido com criptografia AES de 256 bits. Guarde a senha: ela não pode ser recuperada.'
    )


def unlock_pdf(source, dest, password='', progress=_noop):
    with atomic_output(dest) as temp:
        try:
            document = fitz.open(source)
        except Exception as exc:
            raise PdfToolError(f'Não foi possível abrir "{Path(source).name}": {exc}') from exc
        with document:
            was_protected = document.is_encrypted  # antes de autenticar: depois o PyMuPDF já diz False
            if document.needs_pass and not document.authenticate(password or ''):
                raise PdfToolError(
                    'Senha incorreta.' if password else 'Este PDF pede senha para abrir. Digite a senha.'
                )
            document.save(temp, garbage=3, deflate=True, encryption=fitz.PDF_ENCRYPT_NONE)
    message = 'Proteção removida.' if was_protected else 'O PDF não tinha proteção; uma cópia foi salva.'
    return Result([Path(dest)], message)


METADATA_FIELDS = (('title', 'Título'), ('author', 'Autor'), ('subject', 'Assunto'), ('keywords', 'Palavras-chave'))
_PDF_DATE = re.compile(r"^(?:D:)?(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?")


def format_pdf_date(value):
    """Data de PDF ("D:20261127083000-03'00'") como "27/11/2026 08:30"; vazio se não der para ler."""
    found = _PDF_DATE.match((value or '').strip())
    if not found:
        return ''
    year, month, day, hour, minute, _second = found.groups()
    if not (month and day):
        return year
    text = f'{day}/{month}/{year}'
    return f'{text} {hour}:{minute or "00"}' if hour else text


def read_metadata(path):
    """As informações do documento (título, autor, programa, datas), sem abrir erro: vazio se não der para ler."""
    try:
        with FITZ_LOCK, fitz.open(path) as document:
            if document.needs_pass:
                return {}
            metadata = dict(document.metadata or {})
            pages = document.page_count
    except Exception:
        return {}
    info = {key: (metadata.get(key) or '').strip() for key in ('title', 'author', 'subject', 'keywords')}
    info['creator'] = (metadata.get('creator') or '').strip()
    info['producer'] = (metadata.get('producer') or '').strip()
    info['created'] = format_pdf_date(metadata.get('creationDate'))
    info['modified'] = format_pdf_date(metadata.get('modDate'))
    info['pages'] = pages
    return info


def edit_metadata(source, dest, mode='Editar', title='', author='', subject='', keywords='', progress=_noop):
    """Edita ou remove as informações do documento (título, autor, programa que criou, datas...).

    "Editar": os campos preenchidos substituem os atuais; os deixados em branco ficam como estão.
    "Remover": apaga as informações, os metadados XMP, scripts, anexos e miniaturas; o conteúdo das páginas (inclusive
    o texto invisível de um PDF com OCR) não muda."""
    with edit_pdf(source, dest) as (document, temp):
        if mode == 'Remover':
            document.scrub(
                attached_files=True,
                clean_pages=False,
                embedded_files=True,
                hidden_text=False,
                javascript=True,
                metadata=True,
                redactions=False,
                remove_links=False,
                reset_fields=False,
                reset_responses=False,
                thumbnails=True,
                xml_metadata=True,
            )
            document.set_metadata({})
            message = 'Informações do documento, metadados XMP, scripts e anexos removidos.'
        else:
            values = {'title': title, 'author': author, 'subject': subject, 'keywords': keywords}
            changes = {key: str(value).strip() for key, value in values.items() if str(value or '').strip()}
            if not changes:
                raise PdfToolError('Preencha pelo menos um campo para alterar (os vazios ficam como estão).')
            metadata = dict(document.metadata or {})
            metadata.update(changes)
            document.set_metadata(metadata)
            names = ', '.join(label.lower() for key, label in METADATA_FIELDS if key in changes)
            message = f'Informações atualizadas: {names}.'
        _save(document, temp)
    return Result([Path(dest)], message)


REDACTION_PATTERNS = {
    'cpf': ('CPF', r'(?<![\d.])\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?![\d])'),
    'cnpj': ('CNPJ', r'(?<![\d.])\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?![\d])'),
    'email': ('e-mail', r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+'),
    'phone': ('telefone', r'(?<!\d)(?:\(\d{2}\)\s?|\d{2}\s)?9?\d{4}-\d{4}(?!\d)'),
}


def _redaction_terms(text, terms, patterns):
    """Os trechos do texto da página que devem ser tarjados: os termos digitados e o que casa com os padrões."""
    found = set()
    flat = ' '.join(text.split())
    for term in terms:
        if term and term.casefold() in flat.casefold():
            found.add(term)
    for key in patterns:
        found.update(match.group(0) for match in re.finditer(REDACTION_PATTERNS[key][1], flat))
    return found


def redact_pdf(source, dest, terms='', cpf=True, cnpj=False, email=False, phone=False, progress=_noop):
    """Tarja (apaga de verdade) textos do PDF: termos digitados e, se marcados, CPF, CNPJ, e-mail e telefone.

    O texto sob a tarja é removido do arquivo (não só coberto) e os pixels de imagens embaixo dela viram preto, então
    não dá para copiar nem recuperar. Precisa de texto pesquisável: num PDF escaneado, use o OCR antes."""
    wanted = [part.strip() for part in re.split(r'[,;\n]+', terms or '') if part.strip()]
    patterns = [key for key, on in (('cpf', cpf), ('cnpj', cnpj), ('email', email), ('phone', phone)) if on]
    if not wanted and not patterns:
        raise PdfToolError('Digite o que tarjar ou marque pelo menos um tipo de dado (CPF, e-mail...).')
    count = pages_hit = 0
    has_text = False
    with edit_pdf(source, dest) as (document, temp):
        total = document.page_count
        for number, page in enumerate(document):
            progress(0.9 * number / total, f'Procurando na página {number + 1} de {total}')
            text = page.get_text('text')
            if text.strip():
                has_text = True
            areas = []
            for snippet in _redaction_terms(text, wanted, patterns):
                areas.extend(page.search_for(snippet))
            if not areas:
                continue
            for area in areas:
                page.add_redact_annot(area, fill=(0, 0, 0))
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)
            count += len(areas)
            pages_hit += 1
        if not has_text:
            raise PdfToolError(
                f'"{Path(source).name}" não tem texto pesquisável (parece escaneado). '
                'Use antes "OCR - PDF pesquisável" e depois tarje o resultado.'
            )
        if not count:
            raise PdfToolError('Nada encontrado para tarjar: nenhum dos termos ou tipos de dado aparece no PDF.')
        progress(0.95, 'Gravando o PDF')
        document.save(temp, garbage=4, deflate=True, clean=True)  # garbage=4 descarta de vez o que foi apagado
    noun = 'trecho tarjado' if count == 1 else 'trechos tarjados'
    where = 'página' if pages_hit == 1 else 'páginas'
    return Result(
        [Path(dest)], f'{count} {noun} em {pages_hit} {where}. O conteúdo sob a tarja foi apagado do arquivo.'
    )
