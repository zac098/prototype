"""Tela "Unir PDF": a tela padrão das ferramentas, com o botão Imprimir ao lado do Unir.

"Imprimir..." junta a lista (na ordem) em um documento só e abre a janela de impressão do Windows: lá se escolhe a
impressora, o papel, as cópias, as páginas, a cor e a frente e verso. Com um único arquivo na lista, ele é impresso
sozinho.
"""

import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QPushButton

from rdf.core.fitz_lock import FITZ_LOCK
from rdf.pdftools import ops, printing
from rdf.qt.busy import Responsive
from rdf.qt.tool_page import ToolPage


class MergePage(ToolPage):
    # ---- botão Imprimir ------------------------------------------------------------------------
    def build_action_extras(self):
        self.print_button = QPushButton('Imprimir…')
        self.print_button.setToolTip(
            'Abre a janela de impressão do Windows com os arquivos da lista, na ordem (Ctrl+P). Não precisa unir antes.'
        )
        self.print_button.clicked.connect(self.print_files)
        self.print_button.setEnabled(False)
        shortcut = QShortcut(QKeySequence('Ctrl+P'), self, activated=self.print_files)
        shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        return [self.print_button]

    def update_print_button(self):
        self.print_button.setEnabled(bool(self.files) and not self.running)

    def refresh_files(self):
        super().refresh_files()
        if hasattr(self, 'print_button'):
            self.update_print_button()

    def start_worker(self, job_list, values):
        super().start_worker(job_list, values)
        self.update_print_button()

    def on_finished(self, result):
        super().on_finished(result)
        self.update_print_button()

    # ---- impressão -------------------------------------------------------------------------------
    def printable_pdf(self):
        """Um PDF só com todos os arquivos da lista, na ordem (o próprio arquivo, se for um só)."""
        responsive = Responsive()
        pdfs = []
        for position, path in enumerate(self.files, start=1):
            self.set_message(f'Preparando {position} de {len(self.files)}: {Path(path).name}', 'info')
            responsive.pulse()
            pdfs.append(self.cache.resolve(path))
        with FITZ_LOCK:
            if len(pdfs) == 1:
                ops.open_pdf(pdfs[0]).close()  # protegido por senha ou vazio: erro com mensagem pronta
                return pdfs[0]
            folder = self.cache.folder / 'impressao'
            shutil.rmtree(folder, ignore_errors=True)
            joined = folder / 'juntados.pdf'
            ops.merge_pdfs(pdfs, joined)
        return str(joined)

    def make_printer(self):
        from PySide6.QtPrintSupport import QPrinter

        return QPrinter(QPrinter.HighResolution)

    def make_print_dialog(self, printer):
        from PySide6.QtPrintSupport import QPrintDialog

        return QPrintDialog(printer, self)

    def print_files(self):
        if self.running:
            return
        if not self.files:
            self.set_message('Adicione os arquivos que quer imprimir.', 'error')
            return
        try:
            pdf = self.printable_pdf()
            with FITZ_LOCK, ops.open_pdf(pdf) as document:
                total = document.page_count
            printer = self.make_printer()
            names = [Path(path).name for path in self.files]
            printer.setDocName(names[0] if len(names) == 1 else f'RDF - {len(names)} arquivos')
            printer.setFromTo(1, total)
            dialog = self.make_print_dialog(printer)
            dialog.setMinMax(1, total)
            if not dialog.exec():
                self.set_message('Impressão cancelada.', 'info')
                return
            responsive = Responsive()

            def progress(fraction, text=''):
                if text:
                    self.set_message(text, 'info')
                responsive.pulse()

            sent = printing.print_document(pdf, printer, progress)
        except ops.PdfToolError as exc:
            self.set_message(str(exc), 'error')
            return
        except Exception as exc:
            self.set_message(f'Não foi possível imprimir: {exc}', 'error')
            return
        where = printer.printerName() or 'a impressora'
        self.set_message(f'{sent} página(s) enviada(s) para "{where}". Acompanhe na fila da impressora.', 'ok')
