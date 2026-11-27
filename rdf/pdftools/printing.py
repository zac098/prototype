"""Impressão de um PDF pela janela de impressão do Windows.

A janela do sistema (QPrintDialog) escolhe impressora, papel, cópias, páginas, cor e frente e verso, e entrega um
QPrinter já configurado. Este módulo só desenha as páginas nele: cada página sai em pé ou deitada, como é, ajustada
à área de impressão. As páginas são desenhadas pelo próprio app (PyMuPDF + Qt), então funciona com qualquer impressora
instalada e não depende de qual programa o Windows usa para abrir PDF.

O Qt só é carregado quando se imprime: importar este módulo não puxa a interface.
"""

from dataclasses import dataclass
from pathlib import Path

import fitz

from rdf.core.fitz_lock import FITZ_LOCK
from rdf.pdftools import ops

MAX_DPI = 300  # acima disso a página não fica melhor no papel e a imagem enviada à impressora só pesa mais


def selected_pages(printer, total):
    """Índices (base 0) das páginas que a janela de impressão pediu: todas, ou o intervalo "de ... até ..."."""
    from PySide6.QtPrintSupport import QPrinter

    first, last = 1, total
    if printer.printRange() == QPrinter.PageRange and printer.fromPage():
        first = max(1, printer.fromPage())
        last = min(total, printer.toPage() or printer.fromPage())
    if first > last:
        raise ops.PdfToolError(f'O PDF tem {total} páginas; o intervalo pedido ({first} a {last}) não existe.')
    return list(range(first - 1, last))


def copy_plan(printer, pages):
    """A lista de páginas a desenhar, já com as cópias que o app precisa fazer.

    Quando o driver faz as cópias (supportsMultipleCopies), o Qt as repassa e o app desenha uma só vez. Senão, o app
    repete: o documento inteiro por cópia (agrupado) ou cada página várias vezes (sem agrupar)."""
    copies = max(1, printer.copyCount())
    if printer.supportsMultipleCopies() or copies == 1:
        return list(pages)
    if printer.collateCopies():
        return list(pages) * copies
    return [page for page in pages for _ in range(copies)]


def print_document(source, printer, progress=ops._noop):
    """Desenha o PDF no printer (já configurado pela janela do sistema). Devolve quantas páginas foram enviadas.

    Se algo falhar no meio, o documento incompleto não vai para a fila (printer.abort)."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPageLayout, QPainter
    from PySide6.QtPrintSupport import QPrinter

    name = Path(source).name
    with FITZ_LOCK, ops.open_pdf(source) as document:
        plan = copy_plan(printer, selected_pages(printer, document.page_count))

        def orientation(number):
            rect = document[number].rect
            return QPageLayout.Landscape if rect.width > rect.height else QPageLayout.Portrait

        printer.setPageOrientation(orientation(plan[0]))
        painter = QPainter()
        if not painter.begin(printer):
            raise ops.PdfToolError(f'A impressora não aceitou o documento "{name}". Confira se ela está pronta.')
        finished = False
        try:
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            for position, number in enumerate(plan):
                progress(position / len(plan), f'Imprimindo {name}: página {position + 1} de {len(plan)}')
                if position:
                    if printer.pageLayout().orientation() != orientation(number):
                        printer.setPageOrientation(orientation(number))
                    printer.newPage()
                area = printer.pageRect(QPrinter.DevicePixel)
                page = document[number]
                width_pt, height_pt = page.rect.width, page.rect.height
                factor = min(area.width() / width_pt, area.height() / height_pt)  # pixels do papel por ponto
                zoom = min(factor, MAX_DPI / 72)  # o que passa disso é ampliação da imagem já desenhada
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
                # A origem do QPainter já é o canto da área de impressão (fullPage desligado): somar area.x() e
                # area.y() contaria a margem duas vezes e cortaria a direita e o rodapé da página.
                target = QRectF(
                    (area.width() - width_pt * factor) / 2,
                    (area.height() - height_pt * factor) / 2,
                    width_pt * factor,
                    height_pt * factor,
                )
                painter.drawImage(target, image)
            finished = True
        finally:
            if not finished:
                printer.abort()
            painter.end()
    progress(1.0, '')
    return len(plan)


# ---- impressão com as opções do próprio RDF (com prévia) ----------------------------------------------------------
#
# A janela moderna de impressão do Windows 11 não mostra prévia para programas como o RDF. Por isso o RDF tem a sua
# própria tela de impressão (rdf.qt.print_dialog): ela monta as folhas com as opções abaixo e mostra cada folha antes de
# imprimir. A prévia e a impressora usam a mesma função de desenho (paint_sheet): o que aparece na tela é o que sai.

SHEET_GRIDS = {1: (1, 1), 2: (2, 1), 4: (2, 2), 6: (3, 2), 9: (3, 3)}  # páginas por folha -> (colunas, linhas)
PAPER_POINTS = {'A4': (595.0, 842.0), 'Carta': (612.0, 792.0), 'Ofício': (612.0, 1008.0), 'A3': (842.0, 1191.0)}
NORMAL_MARGIN_MM = 10.0  # margem "Normal": 1 cm, como os programas de escritório
PREVIEW_HARDWARE_MM = 4.0  # na prévia, a borda que a maioria das impressoras não alcança
GAP_MM = 3.0  # espaço entre as páginas quando há mais de uma por folha
MM_PER_POINT = 25.4 / 72


@dataclass(frozen=True)
class PrintSettings:
    pages: tuple = ()  # páginas (base 0), na ordem; vazio = todas
    per_sheet: int = 1
    orientation: str = 'auto'  # auto | portrait | landscape
    paper: str = 'A4'
    scale: str = 'fit'  # fit (ajustar à folha) | actual (tamanho real)
    margins: str = 'normal'  # normal | minimum
    grayscale: bool = False
    copies: int = 1
    collate: bool = True
    duplex: str = 'none'  # none | long | short


def sheets_for(pages, per_sheet):
    """As páginas agrupadas por folha, na ordem."""
    per_sheet = per_sheet if per_sheet in SHEET_GRIDS else 1
    pages = list(pages)
    return [pages[start : start + per_sheet] for start in range(0, len(pages), per_sheet)]


def sheet_landscape(page_size, per_sheet, orientation):
    """True se a folha sai deitada. Automática: uma página por folha segue a página; com várias, 2 e 6 por folha ficam
    melhor deitadas (páginas em pé lado a lado) e 4 e 9 em pé."""
    if orientation == 'portrait':
        return False
    if orientation == 'landscape':
        return True
    width, height = page_size
    portrait_pages = height >= width
    if per_sheet <= 1:
        return not portrait_pages
    columns, rows = SHEET_GRIDS.get(per_sheet, (1, 1))
    return (columns > rows) == portrait_pages


def grid_for(per_sheet, landscape):
    """(colunas, linhas) da folha, virando a grade para acompanhar a orientação da folha."""
    columns, rows = SHEET_GRIDS.get(per_sheet, (1, 1))
    if (landscape and rows > columns) or (not landscape and columns > rows):
        columns, rows = rows, columns
    return columns, rows


def cell_rects(content, columns, rows, gap):
    """Os espaços (x, y, largura, altura) de cada página dentro da área útil, da esquerda para a direita."""
    x, y, width, height = content
    cell_w = max(1.0, (width - gap * (columns - 1)) / columns)
    cell_h = max(1.0, (height - gap * (rows - 1)) / rows)
    return [
        (x + col * (cell_w + gap), y + row * (cell_h + gap), cell_w, cell_h)
        for row in range(rows)
        for col in range(columns)
    ]


def place_page(cell, page_size, scale, device_per_point):
    """Onde a página fica no seu espaço: ajustada (sem distorcer) ou em tamanho real, sempre centralizada."""
    x, y, width, height = cell
    page_w, page_h = page_size
    factor = min(width / page_w, height / page_h) if scale != 'actual' else device_per_point
    shown_w, shown_h = page_w * factor, page_h * factor
    return x + (width - shown_w) / 2, y + (height - shown_h) / 2, shown_w, shown_h


def _page_image(document, index, pixels_per_point, grayscale):
    from PySide6.QtGui import QImage

    page = document[index]
    zoom = max(0.05, pixels_per_point)
    colorspace = fitz.csGRAY if grayscale else fitz.csRGB
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False, colorspace=colorspace)
    image_format = QImage.Format_Grayscale8 if grayscale else QImage.Format_RGB888
    return QImage(pix.samples, pix.width, pix.height, pix.stride, image_format).copy()


def paint_sheet(painter, content, document, sheet_pages, settings, landscape, device_per_point, max_pixels_per_point):
    """Desenha as páginas de uma folha em content (QRectF, em pixels do dispositivo: tela ou impressora)."""
    from PySide6.QtCore import QRectF

    gap = GAP_MM / MM_PER_POINT * device_per_point if len(sheet_pages) > 1 or settings.per_sheet > 1 else 0.0
    columns, rows = grid_for(settings.per_sheet, landscape)
    cells = cell_rects((content.x(), content.y(), content.width(), content.height()), columns, rows, gap)
    scale = settings.scale if settings.per_sheet == 1 else 'fit'  # tamanho real só faz sentido com uma por folha
    painter.save()
    painter.setClipRect(content)
    for index, cell in zip(sheet_pages, cells):
        rect = document[index].rect
        x, y, width, height = place_page(cell, (rect.width, rect.height), scale, device_per_point)
        pixels = min(width / rect.width, max_pixels_per_point)
        painter.drawImage(QRectF(x, y, width, height), _page_image(document, index, pixels, settings.grayscale))
    painter.restore()


def preview_image(document, sheet_pages, settings, width_px):
    """A folha como vai sair, numa imagem de width_px de largura (prévia da tela de impressão)."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPen

    first = document[sheet_pages[0]].rect if sheet_pages else fitz.Rect(0, 0, 595, 842)
    landscape = sheet_landscape((first.width, first.height), settings.per_sheet, settings.orientation)
    paper_w, paper_h = PAPER_POINTS.get(settings.paper, PAPER_POINTS['A4'])
    if landscape:
        paper_w, paper_h = paper_h, paper_w
    per_point = width_px / paper_w
    image = QImage(int(width_px), int(round(paper_h * per_point)), QImage.Format_RGB32)
    image.fill(QColor('#ffffff'))
    margin_mm = NORMAL_MARGIN_MM if settings.margins == 'normal' else PREVIEW_HARDWARE_MM
    margin = margin_mm / MM_PER_POINT * per_point
    content = QRectF(margin, margin, image.width() - 2 * margin, image.height() - 2 * margin)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    painter.setRenderHint(QPainter.Antialiasing)
    paint_sheet(painter, content, document, sheet_pages, settings, landscape, per_point, per_point * 2)
    painter.setPen(QPen(QColor('#d0d7de'), 1, Qt.DashLine))  # a área útil, discreta
    painter.drawRect(content)
    painter.end()
    return image


def _apply_printer_settings(printer, settings):
    from PySide6.QtGui import QPageSize
    from PySide6.QtPrintSupport import QPrinter

    sizes = {
        'A4': QPageSize.PageSizeId.A4,
        'Carta': QPageSize.PageSizeId.Letter,
        'Ofício': QPageSize.PageSizeId.Legal,
        'A3': QPageSize.PageSizeId.A3,
    }
    printer.setPageSize(QPageSize(sizes.get(settings.paper, QPageSize.PageSizeId.A4)))
    printer.setColorMode(QPrinter.GrayScale if settings.grayscale else QPrinter.Color)
    duplex = {'long': QPrinter.DuplexLongSide, 'short': QPrinter.DuplexShortSide}.get(
        settings.duplex, QPrinter.DuplexNone
    )
    printer.setDuplex(duplex)
    printer.setFullPage(False)  # a origem do desenho é o canto da área que a impressora alcança


def sheet_plan(sheets, copies, collate, driver_copies):
    """As folhas a desenhar, com as cópias que o app precisa repetir (quando o driver não faz as cópias)."""
    copies = max(1, int(copies))
    if driver_copies or copies == 1:
        return list(sheets)
    if collate:
        return list(sheets) * copies
    return [sheet for sheet in sheets for _ in range(copies)]


def print_with_settings(source, printer, settings, progress=ops._noop):
    """Imprime o PDF com as opções da tela de impressão do RDF. Devolve (páginas, folhas) enviadas à impressora.

    Se algo falhar no meio, o documento incompleto não vai para a fila (printer.abort)."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPageLayout, QPainter
    from PySide6.QtPrintSupport import QPrinter

    name = Path(source).name
    with FITZ_LOCK, ops.open_pdf(source) as document:
        total = document.page_count
        pages = list(settings.pages) or list(range(total))
        if any(not 0 <= index < total for index in pages):
            raise ops.PdfToolError(f'O PDF tem {total} páginas; confira as páginas escolhidas.')
        sheets = sheets_for(pages, settings.per_sheet)
        _apply_printer_settings(printer, settings)
        printer.setCopyCount(max(1, int(settings.copies)))
        printer.setCollateCopies(bool(settings.collate))
        driver_copies = printer.supportsMultipleCopies()
        if not driver_copies:
            printer.setCopyCount(1)  # o app repete as folhas
        plan = sheet_plan(sheets, settings.copies, settings.collate, driver_copies)

        def landscape_of(sheet):
            rect = document[sheet[0]].rect
            return sheet_landscape((rect.width, rect.height), settings.per_sheet, settings.orientation)

        def orient(sheet):
            wanted = QPageLayout.Landscape if landscape_of(sheet) else QPageLayout.Portrait
            if printer.pageLayout().orientation() != wanted:
                printer.setPageOrientation(wanted)

        orient(plan[0])
        painter = QPainter()
        if not painter.begin(printer):
            raise ops.PdfToolError(f'A impressora não aceitou o documento "{name}". Confira se ela está pronta.')
        finished = False
        try:
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            for position, sheet in enumerate(plan):
                progress(position / len(plan), f'Imprimindo {name}: folha {position + 1} de {len(plan)}')
                if position:
                    orient(sheet)
                    printer.newPage()
                area = printer.pageRect(QPrinter.DevicePixel)
                per_mm = printer.resolution() / 25.4
                content = QRectF(0, 0, area.width(), area.height())
                if settings.margins == 'normal':  # completa a borda da impressora até 1 cm
                    extra_x = max(0.0, NORMAL_MARGIN_MM * per_mm - area.x())
                    extra_y = max(0.0, NORMAL_MARGIN_MM * per_mm - area.y())
                    content.adjust(extra_x, extra_y, -extra_x, -extra_y)
                device_per_point = printer.resolution() / 72
                paint_sheet(
                    painter, content, document, sheet, settings, landscape_of(sheet), device_per_point, MAX_DPI / 72
                )
            finished = True
        finally:
            if not finished:
                printer.abort()
            painter.end()
    progress(1.0, '')
    return len(pages), len(sheets)
