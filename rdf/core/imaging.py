"""Renderização de páginas, pré-processamento e correção de perspectiva."""

import logging

import cv2
import fitz
import numpy as np

from rdf.core.fitz_lock import FITZ_LOCK

LOGGER = logging.getLogger("rdf")

# Cada worker de análise usa uma thread do OpenCV, sem disputar CPU.
cv2.setNumThreads(1)


MIN_PAGE_CONTRAST = 12  # quanto a folha precisa ser mais clara que o fundo ao redor (0 a 255)


def _stands_out(gray, polygon):
    """True se o quadrilátero é mais claro que a faixa ao redor dele: uma folha sobre uma mesa escura.

    Em um scanner a folha ocupa a imagem toda, e o maior quadrilátero é a tabela dentro dela; cortar nele
    jogaria fora o cabeçalho (matrícula e nome). Ao redor da tabela só há margem branca, então não passa."""
    mask = np.zeros(gray.shape[:2], np.uint8)
    cv2.fillPoly(mask, [polygon.astype(np.int32)], 255)
    margin = max(15, int(min(gray.shape[:2]) * 0.05))
    ring = cv2.subtract(cv2.dilate(mask, np.ones((margin, margin), np.uint8)), mask)
    if cv2.countNonZero(ring) < gray.size * 0.01:
        return True  # a folha encosta nas bordas da foto: não há fundo para comparar
    return cv2.mean(gray, mask)[0] - cv2.mean(gray, ring)[0] >= MIN_PAGE_CONTRAST


def rectify_document_photo(image):
    """Crop and deskew a photographed sheet when a reliable page contour exists."""
    if image is None or image.ndim not in (2, 3):
        return image, False
    height, width = image.shape[:2]
    if min(height, width) < 500:
        return image, False
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 50, 150)
    edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    page_area = float(height * width)
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:25]:
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(polygon) != 4:
            continue
        area = cv2.contourArea(polygon)
        if area < page_area * 0.45 or area > page_area * 0.995:
            continue
        if not _stands_out(gray, polygon):
            continue  # um quadro dentro da própria folha (a tabela de um scanner), não a folha sobre a mesa
        points = polygon.reshape(4, 2).astype(np.float32)
        sums = points.sum(axis=1)
        diffs = np.diff(points, axis=1).ravel()
        rect = np.array(
            [points[np.argmin(sums)], points[np.argmin(diffs)], points[np.argmax(sums)], points[np.argmax(diffs)]],
            dtype=np.float32,
        )
        top_left, top_right, bottom_right, bottom_left = rect
        target_width = int(max(np.linalg.norm(bottom_right - bottom_left), np.linalg.norm(top_right - top_left)))
        target_height = int(max(np.linalg.norm(top_right - bottom_right), np.linalg.norm(top_left - bottom_left)))
        if target_width < 350 or target_height < 500:
            continue
        ratio = target_width / target_height
        if not 0.45 <= ratio <= 1.05:
            continue
        destination = np.array(
            [[0, 0], [target_width - 1, 0], [target_width - 1, target_height - 1], [0, target_height - 1]],
            dtype=np.float32,
        )
        corrected = cv2.warpPerspective(
            image,
            cv2.getPerspectiveTransform(rect, destination),
            (target_width, target_height),
            borderMode=cv2.BORDER_REPLICATE,
        )
        LOGGER.info('Perspectiva corrigida: %sx%s -> %sx%s', width, height, target_width, target_height)
        return corrected, True
    return image, False


def _pixmap_to_rgb(pix):
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n).copy()
    return cv2.cvtColor(image, cv2.COLOR_RGBA2RGB) if pix.n == 4 else image


def render_header_candidates(pdf_path, page_index=0):
    """Renderiza topo e rodape da pagina escolhida para OCR."""
    with FITZ_LOCK, fitz.open(pdf_path) as doc:
        if not 0 <= int(page_index) < len(doc):
            raise IndexError('Página de análise fora do intervalo.')
        page = doc[int(page_index)]
        rect = page.rect
        height = rect.height * 0.34
        matrix = fitz.Matrix(3, 3)
        top = page.get_pixmap(matrix=matrix, clip=fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + height), alpha=False)
        bottom = page.get_pixmap(
            matrix=matrix, clip=fitz.Rect(rect.x0, rect.y1 - height, rect.x1, rect.y1), alpha=False
        )
    return [(0, _pixmap_to_rgb(top)), (180, cv2.rotate(_pixmap_to_rgb(bottom), cv2.ROTATE_180))]


def render_full_page(pdf_path, page_index=0, width=1900):
    """A página inteira (sem recortes) com a largura dada em pixels, como RGB."""
    with FITZ_LOCK, fitz.open(pdf_path) as doc:
        if not 0 <= int(page_index) < len(doc):
            raise IndexError('Página de análise fora do intervalo.')
        page = doc[int(page_index)]
        zoom = width / page.rect.width
        return _pixmap_to_rgb(page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False))


def render_pdf_page(pdf_path, page_index=0, scale=1.8):
    """Renderiza uma pagina inteira para a previa lateral, sob demanda."""
    with FITZ_LOCK, fitz.open(pdf_path) as doc:
        total = len(doc)
        if total < 1:
            raise RuntimeError('PDF sem páginas.')
        page_index = max(0, min(int(page_index), total - 1))
        page = doc[page_index]
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n).copy()
    if pix.n == 4:
        image = cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)
    return image, total


def preprocess(img):
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    gray = cv2.resize(gray, None, fx=1.25, fy=1.25, interpolation=cv2.INTER_CUBIC)
    gray = cv2.fastNlMeansDenoising(gray, None, 12, 7, 21)
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 35, 12)
