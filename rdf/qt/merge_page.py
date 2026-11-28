"""Tela "Unir PDF": a tela padrão das ferramentas, com o botão Imprimir ao lado do Unir.

"Imprimir..." junta a lista (na ordem) em um documento só e abre esse PDF no Microsoft Edge, que tem a tela de
impressão mais completa (prévia, páginas por folha, escala, margens): lá, é só apertar Ctrl+P. Sem o Edge, abre a tela
de impressão do próprio RDF (rdf.qt.print_dialog), com prévia e a janela do Windows a um botão de distância. Com um
único arquivo na lista, ele vai sozinho. Nada é salvo: o PDF juntado fica numa pasta temporária do RDF e é apagado ao
sair da ferramenta ou fechar o app. Para guardar o PDF, o botão é o "Unir PDF".
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
            'Junta os arquivos da lista, na ordem, e abre no Microsoft Edge para imprimir pela tela dele (Ctrl+P). '
            'Não salva nenhum arquivo.'
        )
        self.print_button.clicked.connect(self.print_files)
        self.print_button.setEnabled(False)
        shortcut = QShortcut(QKeySequence('Ctrl+P'), self, activated=self.print_files)
        shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self.print_hint = QLabel(
            '"Unir PDF" salva o PDF juntado onde você escolher. "Imprimir" junta e abre no Edge para imprimir '
            '(Ctrl+P): nada fica salvo.'
        )
        self.print_hint.setObjectName('hint')
        self.print_hint.setWordWrap(True)
        return [self.print_button, self.print_hint]

    def empty_options_text(self):
        return (
            'Adicione os arquivos e ponha na ordem certa: a ordem da lista é a ordem das páginas. Arraste os '
            'arquivos na lista, use as setas ou o botão A→Z.'
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

    def make_preview_dialog(self, pdf, title):
        from rdf.qt.print_dialog import PrintDialog

        return PrintDialog(pdf, title, self)

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
        from rdf.qt.print_dialog import PrintDialog, edge_path

        try:
            pdf = self.printable_pdf(files)
            with FITZ_LOCK, ops.open_pdf(pdf) as document:
                total = document.page_count
            if edge_path() is not None:
                # O caminho preferido: o Edge abre o PDF juntado e a impressão é pela tela dele (Ctrl+P), com prévia
                # e todas as opções. Sem o Edge, vale a tela de impressão do próprio RDF.
                return self.open_in_edge(pdf)
            names = [Path(path).name for path in files]
            title = names[0] if len(names) == 1 else f'RDF - {len(names)} arquivos'
            preview = self.make_preview_dialog(pdf, title)
            try:
                choice = preview.exec()
            finally:
                release = getattr(preview, 'release', None)
                if callable(release):
                    release()  # garante o PDF fechado antes de a cópia temporária ser apagada
            if choice == PrintDialog.WINDOWS:
                return self._print_with_windows(pdf, total, title)
            if choice == PrintDialog.EDGE:
                return self.open_in_edge(pdf)
            if not choice:
                self.set_message('Impressão cancelada.', 'info')
                return
            printer = preview.make_printer()
            responsive = Responsive()

            def progress(fraction, text=''):
                if text:
                    self.set_message(text, 'info')
                responsive.pulse()

            pages, sheets = printing.print_with_settings(pdf, printer, preview.settings(), progress)
        except ops.PdfToolError as exc:
            self.set_message(str(exc), 'error')
            return
        except Exception as exc:
            self.set_message(f'Não foi possível imprimir: {exc}', 'error')
            return
        where = printer.printerName() or 'a impressora'
        detail = f'{pages} página(s)' if pages == sheets else f'{pages} página(s) em {sheets} folha(s)'
        self.set_message(f'{detail} enviada(s) para "{where}". Acompanhe na fila da impressora.', 'ok')

    def open_in_edge(self, pdf, launcher=None):
        """Abre o PDF juntado no Edge, para imprimir pela tela dele. A cópia fica na pasta temporária desta tela (o Edge
        precisa dela aberta) e é apagada quando o usuário sai do Unir PDF ou fecha o RDF."""
        import subprocess
        import uuid

        from rdf.qt.print_dialog import edge_path

        edge = edge_path()
        if edge is None and launcher is None:
            self.set_message('O Microsoft Edge não foi encontrado neste computador.', 'error')
            return
        folder = self.cache.folder / 'edge'
        folder.mkdir(parents=True, exist_ok=True)
        copy = folder / f'imprimir-{uuid.uuid4().hex[:6]}.pdf'
        shutil.copyfile(pdf, copy)
        try:
            (launcher or subprocess.Popen)([edge or 'msedge', copy.as_uri()])
        except OSError as exc:
            self.set_message(f'Não foi possível abrir o Edge: {exc}', 'error')
            return
        self.set_message('Aberto no Edge: aperte Ctrl+P lá para imprimir. Nada fica salvo no computador.', 'ok')
        return copy

    def _print_with_windows(self, pdf, total, title):
        """A janela de impressão do Windows (sem prévia), para quem precisa dos ajustes do driver."""
        try:
            printer = self.make_printer()
            printer.setDocName(title)
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
