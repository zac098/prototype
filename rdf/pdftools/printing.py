"""Impressão de um PDF pela janela de impressão do Windows.

A janela do sistema (QPrintDialog) escolhe impressora, papel, cópias, páginas, cor e frente e verso, e entrega um
QPrinter já configurado. Este módulo só desenha as páginas nele: cada página sai em pé ou deitada, como é, ajustada
à área de impressão. As páginas são desenhadas pelo próprio app (PyMuPDF + Qt), então funciona com qualquer impressora
instalada e não depende de qual programa o Windows usa para abrir PDF.

O Qt só é carregado quando se imprime: importar este módulo não puxa a interface.
"""

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
                target = QRectF(
                    area.x() + (area.width() - width_pt * factor) / 2,
                    area.y() + (area.height() - height_pt * factor) / 2,
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
