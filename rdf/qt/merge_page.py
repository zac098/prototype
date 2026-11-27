"""Tela "Unir PDF": a tela padrão das ferramentas, com o botão Imprimir ao lado do Unir.

"Imprimir..." junta a lista (na ordem) em um documento só e abre a janela de impressão do Windows: lá se escolhe a
impressora, o papel, as cópias, as páginas, a cor e a frente e verso. Com um único arquivo na lista, ele é impresso
sozinho. Nada é salvo: o PDF juntado fica numa pasta temporária só enquanto a impressão é preparada e é apagado logo
depois (impresso, cancelado ou com erro). Para guardar o PDF, o botão é o "Unir PDF".
"""

import shutil
import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QLabel, QPushButton

from rdf.core.fitz_lock import FITZ_LOCK
from rdf.pdftools import ops, printing
from rdf.qt.busy import Responsive
from rdf.qt.tool_page import ToolPage


class MergePage(ToolPage):
    # ---- botão Imprimir ------------------------------------------------------------------------
    def build_action_extras(self):
        self.print_button = QPushButton('Imprimir…')
        self.print_button.setProperty('variant', 'success')
        self.print_button.setMinimumHeight(42)
        self.print_button.setToolTip(
            'Junta os arquivos da lista, na ordem, e abre a janela de impressão do Windows (Ctrl+P). '
            'Não salva nenhum arquivo.'
        )
        self.print_button.clicked.connect(self.print_files)
        self.print_button.setEnabled(False)
        shortcut = QShortcut(QKeySequence('Ctrl+P'), self, activated=self.print_files)
        shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self.print_hint = QLabel(
            '"Unir PDF" salva o PDF juntado onde você escolher. "Imprimir" junta só para imprimir: nada fica salvo.'
        )
        self.print_hint.setObjectName('hint')
        self.print_hint.setWordWrap(True)
        return [self.print_button, self.print_hint]

    def empty_options_text(self):
        return (
            'Adicione os arquivos e ponha na ordem certa. Depois, "Unir PDF" para salvar um PDF só, ou "Imprimir" '
            'para mandar tudo direto para a impressora, sem salvar.'
        )

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
    def in_background(self, function, *args):
        """Roda function numa thread e mantém a janela viva enquanto espera (converter um documento do Office leva
        segundos). O teclado e o mouse ficam de fora, como no resto do app: nada é clicado no meio."""
        outcome = {}

        def target():
            try:
                outcome['value'] = function(*args)
            except BaseException as exc:  # devolvido para quem chamou, na thread da janela
                outcome['error'] = exc

        worker = threading.Thread(target=target, name='rdf-imprimir', daemon=True)
        worker.start()
        responsive = Responsive()
        while worker.is_alive():
            responsive.pulse()
            time.sleep(0.02)
        if 'error' in outcome:
            raise outcome['error']
        return outcome.get('value')

    def printable_pdf(self, files=None):
        """Um PDF só com todos os arquivos da lista, na ordem (o próprio arquivo, se for um só)."""
        files = list(self.files if files is None else files)
        pdfs = []
        for position, path in enumerate(files, start=1):
            self.set_message(f'Preparando {position} de {len(files)}: {Path(path).name}', 'info')
            pdfs.append(self.in_background(self.cache.resolve, path))
        with FITZ_LOCK:
            if len(pdfs) == 1:
                ops.open_pdf(pdfs[0]).close()  # protegido por senha ou vazio: erro com mensagem pronta
                return pdfs[0]
            folder = self.print_folder
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
        # Enquanto prepara e imprime, a tela conta como ocupada: arquivos que chegarem do botão direito do Explorer não
        # entram na lista no meio (a janela avisa), e a lista usada é a de quando o botão foi clicado.
        self.running = True
        self.update_print_button()
        try:
            return self._print(list(self.files))
        finally:
            self.discard_print_copy()
            self.running = False
            self.update_print_button()

    @property
    def print_folder(self):
        return self.cache.folder / 'impressao'

    def discard_print_copy(self):
        """Apaga o PDF juntado para a impressão: imprimir não salva nada (as páginas já estão na fila da impressora)."""
        shutil.rmtree(self.print_folder, ignore_errors=True)

    def _print(self, files):
        try:
            pdf = self.printable_pdf(files)
            with FITZ_LOCK, ops.open_pdf(pdf) as document:
                total = document.page_count
            printer = self.make_printer()
            names = [Path(path).name for path in files]
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
