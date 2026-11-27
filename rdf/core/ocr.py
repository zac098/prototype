"""Análise de folhas de ponto e documentos com texto embutido e Tesseract."""

import logging

import cv2
import fitz
import numpy as np
import pytesseract

from .classifier import _classification_scores, classify_extra_document
from .fitz_lock import FITZ_LOCK
from .imaging import preprocess, render_full_page, render_header_candidates
from .parsing import is_ready_confidence, normalize_text, parse_chapa_nome, relevant_header_confidence

LOGGER = logging.getLogger("rdf")

TESSERACT_MISSING_MESSAGE = (
    'Tesseract não localizado. Reinstale o RDF ou escreva o caminho do tesseract.exe no arquivo '
    'tesseract_path.txt, na pasta do programa.'
)


OCR_TIMEOUT_SECONDS = 90  # um tesseract.exe travado não pode prender a análise (e o fechamento do app) para sempre
TESSERACT_TIMEOUT_MESSAGE = f'O Tesseract demorou mais de {OCR_TIMEOUT_SECONDS} s em uma leitura e foi interrompido.'


def _run_tesseract(function, image, **kwargs):
    try:
        return function(image, timeout=OCR_TIMEOUT_SECONDS, **kwargs)
    except RuntimeError as exc:  # o pytesseract avisa a interrupção por tempo com este erro
        if 'timeout' in str(exc).lower():
            raise RuntimeError(TESSERACT_TIMEOUT_MESSAGE) from None
        raise


def _image_to_data(image, config):
    return _run_tesseract(
        pytesseract.image_to_data, image, lang='por+eng', config=config, output_type=pytesseract.Output.DICT
    )


def _image_to_string(image, config):
    return _run_tesseract(pytesseract.image_to_string, image, lang='por+eng', config=config)


def _render_rgb(page, scale):
    """A página renderizada na escala dada, como imagem RGB (numpy)."""
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n).copy()
    if pix.n == 4:
        img = cv2.cvtColor(img, cv2.COLOR_RGBA2RGB)
    return img


def _page_data(path, index, scale=None):
    """(total de páginas, texto embutido, imagem RGB se scale) de uma página, lidos sob a trava do PyMuPDF.

    O Tesseract roda depois, fora da trava: só o acesso ao PDF é um de cada vez."""
    with FITZ_LOCK, fitz.open(path) as doc:
        total = len(doc)
        if not 0 <= index < total:
            return total, '', None
        page = doc[index]
        return total, page.get_text('text') or '', (_render_rgb(page, scale) if scale else None)


RESCUE_UPSCALE_BELOW = 1400  # cabeçalhos mais estreitos que isto (px) são ampliados na tentativa de resgate
RESCUE_TARGET_WIDTH = 1787
RESCUE_MAX_SCALE = 3.0
FULL_PAGE_WIDTH = 1900  # largura (px) da página inteira lida no último resgate


def analyze_pdf(path, page_index=0, document_text=None):
    # Texto embutido primeiro. A chapa numerica do nome do arquivo serve como validacao.
    try:
        with FITZ_LOCK, fitz.open(path) as doc:
            if not 0 <= int(page_index) < len(doc):
                raise IndexError('Página de análise fora do intervalo.')
            page = doc[int(page_index)]
            blocks = sorted(page.get_text('blocks'), key=lambda b: (round(b[1] / 8), b[0]))
            text = '\n'.join(b[4] for b in blocks)
        parsed = parse_chapa_nome(text)
        if parsed:
            return parsed, 'Texto', 0.99
    except (fitz.FileDataError, RuntimeError) as exc:
        LOGGER.warning('Falha ao ler texto embutido de %s: %s', path, exc)
    except Exception:
        LOGGER.exception('Erro inesperado ao extrair texto de %s', path)
    attempts = []
    full_page_checked = False
    headers = render_header_candidates(path, page_index)
    for angle, header in headers:
        if _has_complete(attempts):
            break  # o topo já deu matrícula, nome e mês com boa confiança: o rodapé não precisa ser lido
        if document_text is not None:
            gray = cv2.cvtColor(header, cv2.COLOR_RGB2GRAY)
            binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
            try:
                data = _image_to_data(binary, '--oem 3 --psm 6')
                text = ' '.join(x for x in data['text'] if x.strip())
                parsed = parse_chapa_nome(text)
                if parsed:
                    conf = relevant_header_confidence(data, parsed[0])
                    attempts.append((parsed, conf, angle))
                    if parsed[0] and parsed[1] and parsed[2] and is_ready_confidence(conf):
                        method = 'OCR' if angle == 0 else 'OCR 180 graus'
                        return parsed, method, conf
                else:
                    document_text['header'].append(text)
                    header_text = ' '.join(document_text['header'])
                    scores = _classification_scores(header_text, path)
                    category = classify_extra_document(path, header_text)
                    if category and max(scores['Atestados'], scores['Declarações']) >= 6:
                        return None, 'Documento', 0
                    # Com um cabeçalho de folha já lido, não é atestado nem declaração: a página inteira fica de fora.
                    if not full_page_checked and not attempts:
                        full_page_checked = True
                        document_text['fast_page'] = _document_search_text(path, max_pages=1)
                        category = classify_extra_document(path, document_text['fast_page'])
                        if category:
                            return None, 'Documento', 0
            except pytesseract.TesseractNotFoundError:
                raise RuntimeError(TESSERACT_MISSING_MESSAGE) from None
        proc = preprocess(header)
        for image, config in ((proc, '--oem 3 --psm 6'), (proc, '--oem 3 --psm 11'), (header, '--oem 3 --psm 6')):
            if _has_complete(attempts):
                break  # uma leitura completa basta: as outras variações só custariam tempo
            try:
                data = _image_to_data(image, config)
                text = ' '.join(x for x in data['text'] if x.strip())
                parsed = parse_chapa_nome(text)
                if parsed:
                    conf = relevant_header_confidence(data, parsed[0])
                    attempts.append((parsed, conf, angle))
                elif document_text is not None:
                    document_text['header'].append(text)
                    header_text = ' '.join(document_text['header'])
                    scores = _classification_scores(header_text, path)
                    category = classify_extra_document(path, header_text)
                    if category and max(scores['Atestados'], scores['Declarações']) >= 6:
                        return None, 'Documento', 0
            except pytesseract.TesseractNotFoundError:
                raise RuntimeError(TESSERACT_MISSING_MESSAGE) from None
    month_found = any(parsed[2] for parsed, _conf, _angle in attempts)  # o mês de uma leitura vale para as outras
    if not any(_is_complete(parsed, conf, month_found) for parsed, conf, _angle in attempts):
        # Nada lido, ou só leituras fracas (nome truncado, mês faltando, confiança baixa): tenta o resgate e fica
        # com a melhor das leituras. Arquivos bem lidos nunca chegam aqui, então o lote não fica mais lento.
        attempts.extend(_rescue_header_attempts(path, page_index, headers))
    if attempts:
        parsed, conf, angle = _best_attempt(attempts)
        if parsed[2] is None:
            month = next((candidate[0][2] for candidate in attempts if candidate[0][2]), None)
            if month:
                parsed = (parsed[0], parsed[1], month, parsed[3])
        method = 'OCR' if angle == 0 else 'OCR 180 graus'
        return parsed, method, conf
    return None, 'Falhou', 0


def _is_complete(parsed, conf, month_found=False):
    """Matrícula, nome e mês lidos com confiança suficiente para o status OK."""
    return bool(parsed[0] and parsed[1] and (parsed[2] or month_found) and is_ready_confidence(conf))


def _best_attempt(attempts):
    """A leitura a usar: primeiro as completas (o mês pode vir de outra leitura), pela confiança; entre as
    incompletas, as que acharam o mês e depois a confiança. Uma leitura fraca não ganha de uma boa só por ter o mês:
    o mês é emprestado depois, por quem chama."""
    month_found = any(parsed[2] for parsed, _conf, _angle in attempts)

    def key(item):
        parsed, conf, _angle = item
        complete = _is_complete(parsed, conf, month_found)
        has_month = parsed[2] is not None
        return (parsed[3] == 'documento', complete, conf if complete else has_month, has_month if complete else conf)

    return max(attempts, key=key)


def _has_complete(attempts):
    """Alguma leitura já basta para o status OK (o mês de uma leitura vale para as outras)."""
    month_found = any(parsed[2] for parsed, _conf, _angle in attempts)
    return any(_is_complete(parsed, conf, month_found) for parsed, conf, _angle in attempts)


def _rescue_header_attempts(path, page_index, headers):
    """Última tentativa de ler o cabeçalho quando as leituras normais não acharam "Chapa/Nome".

    Imagens pequenas e borradas leem melhor ampliadas até a largura de uma folha A4; fotos grandes de celular,
    em cinza, com o texto menor (imagem reduzida) ou com a busca de texto solto (psm 11). Só roda nos arquivos
    que já falharam, então não pesa no lote.

    Se ainda assim nada for lido, procura o cabeçalho na página inteira: numa foto de celular a folha não começa
    no topo da imagem, então o cabeçalho fica fora das faixas do topo e do rodapé."""
    found = _rescue_from_crops(headers)
    if not found:
        found = _rescue_from_full_page(path, page_index)
    return found


def _read_header(image, config, angle, found):
    try:
        data = _image_to_data(image, config)
    except pytesseract.TesseractNotFoundError:
        raise RuntimeError(TESSERACT_MISSING_MESSAGE) from None
    parsed = parse_chapa_nome(' '.join(x for x in data['text'] if x.strip()))
    if parsed:
        found.append((parsed, relevant_header_confidence(data, parsed[0]), angle))


def _rescue_from_full_page(path, page_index):
    found = []
    page = cv2.cvtColor(render_full_page(path, page_index, FULL_PAGE_WIDTH), cv2.COLOR_RGB2GRAY)
    for angle, image in ((0, page), (180, cv2.rotate(page, cv2.ROTATE_180))):
        # As duas leituras (texto solto e por linhas) rodam sempre: uma costuma achar a matrícula e o nome, e a
        # outra o título com o mês, que o resultado final junta.
        for config in ('--oem 3 --psm 11', '--oem 3 --psm 6'):
            _read_header(image, config, angle, found)
        if found:
            break
    return found


def _rescue_from_crops(headers):
    found = []
    for angle, header in headers:
        gray = cv2.cvtColor(header, cv2.COLOR_RGB2GRAY)
        if gray.shape[1] < RESCUE_UPSCALE_BELOW:
            scale = min(RESCUE_MAX_SCALE, RESCUE_TARGET_WIDTH / gray.shape[1])
            big = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            variants = ((big, '--oem 3 --psm 6'), (big, '--oem 3 --psm 11'))
        else:
            half = cv2.resize(gray, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
            variants = ((gray, '--oem 3 --psm 11'), (half, '--oem 3 --psm 4'), (half, '--oem 3 --psm 6'))
        for image, config in variants:
            _read_header(image, config, angle, found)
            month_found = any(parsed[2] for parsed, _conf, _angle in found)
            if any(_is_complete(parsed, conf, month_found) for parsed, conf, _angle in found):
                return found  # já leu bem: não gasta as outras leituras
    return found


def _embedded_document_text(path, max_pages=3):
    """Extract embedded text without starting Tesseract."""
    collected = []
    try:
        with FITZ_LOCK, fitz.open(path) as doc:
            for index in range(min(len(doc), max_pages)):
                text = doc[index].get_text('text') or ''
                if text.strip():
                    collected.append(text)
    except Exception:
        LOGGER.exception('Falha ao extrair texto embutido de %s', path)
    return normalize_text('\n'.join(collected))


def _document_search_text(path, max_pages=2):
    """Classify extra documents with a short OCR path and a rotated fallback."""
    collected = []
    try:
        total = _page_data(path, 0)[0]
        for index in range(min(total, max_pages)):
            embedded = _page_data(path, index)[1]
            if embedded.strip():
                collected.append(embedded)
            scores = _classification_scores('\n'.join(collected), path)
            if scores['timesheet'] or max(scores['Atestados'], scores['Declarações']) >= 4:
                return normalize_text('\n'.join(collected))
            # A lower scale is sufficient for document keywords and reduces
            # pixels sent to Tesseract by roughly half versus the old 2.4x path.
            img = _page_data(path, index, 1.8)[2]
            gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
            # Most scans are upright. Try 0 and 180 degrees first, one OCR
            # layout each, and stop immediately after enough evidence.
            for angle, image in ((0, binary), (180, cv2.rotate(binary, cv2.ROTATE_180))):
                text = _image_to_string(image, '--oem 3 --psm 6')
                if text.strip():
                    collected.append(text)
                scores = _classification_scores('\n'.join(collected), path)
                if scores['timesheet'] or max(scores['Atestados'], scores['Declarações']) >= 4:
                    LOGGER.info(
                        'Documento classificado durante OCR rápido: %s, página %s, ângulo %s',
                        path,
                        index + 1,
                        angle,
                    )
                    return normalize_text('\n'.join(collected))
        # Rare sideways scans use one final pass on the first page only.
        if total:
            img = _page_data(path, 0, 1.8)[2]
            gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            for angle, image in (
                (90, cv2.rotate(gray, cv2.ROTATE_90_CLOCKWISE)),
                (270, cv2.rotate(gray, cv2.ROTATE_90_COUNTERCLOCKWISE)),
            ):
                text = _image_to_string(image, '--oem 3 --psm 6')
                if text.strip():
                    collected.append(text)
                scores = _classification_scores('\n'.join(collected), path)
                if max(scores['Atestados'], scores['Declarações']) >= 4:
                    LOGGER.info('Documento classificado no fallback: %s, ângulo %s', path, angle)
                    break
    except Exception:
        LOGGER.exception('Falha ao classificar documento %s', path)
    return normalize_text('\n'.join(collected))


def _document_search_text_exhaustive(path, max_pages=3):
    """Compatibility fallback for difficult scans that the fast path cannot classify."""
    collected = []
    try:
        total = _page_data(path, 0)[0]
        for index in range(min(total, max_pages)):
            embedded = _page_data(path, index)[1]
            if embedded.strip():
                collected.append(embedded)
            scores = _classification_scores('\n'.join(collected), path)
            if max(scores['Atestados'], scores['Declarações']) >= 6:
                return normalize_text('\n'.join(collected))
            img = _page_data(path, index, 2.4)[2]
            gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            gray = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
            threshold = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, 13)
            oriented = [
                img,
                cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE),
                cv2.rotate(img, cv2.ROTATE_180),
                cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE),
            ]
            oriented_threshold = [
                threshold,
                cv2.rotate(threshold, cv2.ROTATE_90_CLOCKWISE),
                cv2.rotate(threshold, cv2.ROTATE_180),
                cv2.rotate(threshold, cv2.ROTATE_90_COUNTERCLOCKWISE),
            ]
            for angle, (original, binary) in zip((0, 90, 180, 270), zip(oriented, oriented_threshold)):
                for image, psm in ((binary, 6), (binary, 11), (original, 11)):
                    text = _image_to_string(image, f'--oem 3 --psm {psm}')
                    if text.strip():
                        collected.append(text)
                    scores = _classification_scores('\n'.join(collected), path)
                    if max(scores['Atestados'], scores['Declarações']) >= 7:
                        LOGGER.info(
                            'Documento classificado no fallback completo: %s, página %s, ângulo %s',
                            path,
                            index + 1,
                            angle,
                        )
                        return normalize_text('\n'.join(collected))
    except Exception:
        LOGGER.exception('Falha no fallback completo de %s', path)
    return normalize_text('\n'.join(collected))


def analyze_document(path, page_index=0):
    """Use cheap evidence first and reserve full-page OCR for unresolved files."""
    embedded = _embedded_document_text(path)
    if embedded:
        category = classify_extra_document(path, embedded)
        if category:
            label = 'Atestado' if category == 'Atestados' else 'Declaração'
            return {'category': category, 'document_type': label, 'method': 'Documento', 'conf': 0.90}
    # Timesheets are the dominant workload. Header OCR is much cheaper than the
    # previous full-page, four-rotation document classification.
    ocr_context = {'header': [], 'fast_page': None}
    parsed, method, conf = analyze_pdf(path, page_index, ocr_context)
    if parsed:
        return {'category': None, 'document_type': 'Folha de ponto', 'parsed': parsed, 'method': method, 'conf': conf}
    category = classify_extra_document(path, ' '.join(ocr_context['header']))
    if category:
        label = 'Atestado' if category == 'Atestados' else 'Declaração'
        return {'category': category, 'document_type': label, 'method': 'Documento', 'conf': 0.90}
    # Fast document OCR handles common scans. If it remains unresolved,
    # restore the proven exhaustive routine only for that difficult file.
    fast_text = ocr_context['fast_page']
    if fast_text is None:
        fast_text = _document_search_text(path)
    category = classify_extra_document(path, fast_text)
    if not category:
        exhaustive_text = _document_search_text_exhaustive(path)
        category = classify_extra_document(path, exhaustive_text)
    if category:
        label = 'Atestado' if category == 'Atestados' else 'Declaração'
        return {'category': category, 'document_type': label, 'method': 'Documento', 'conf': 0.90}
    return {'category': None, 'document_type': 'Não identificado', 'parsed': None, 'method': method, 'conf': conf}
