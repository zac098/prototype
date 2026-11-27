"""Tela de impressão do RDF: prévia de cada folha e as opções de sempre, imprimindo direto na impressora escolhida.

A janela moderna de impressão do Windows 11 não mostra prévia para programas como o RDF ("este aplicativo não dá
suporte à visualização de impressão"). Aqui a prévia é desenhada pelo próprio RDF, com a mesma função que desenha na
impressora (rdf.pdftools.printing.paint_sheet): o que aparece é o que sai. Para os ajustes avançados do driver
(bandeja, qualidade...), o botão "Janela do Windows…" continua abrindo a janela do sistema.
"""

import fitz
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from rdf.core.fitz_lock import FITZ_LOCK
from rdf.pdftools import printing
from rdf.pdftools.pages import PageRangeError, parse_page_ranges

PREVIEW_WIDTH = 460
PREVIEW_HEIGHT = 600
ORIENTATIONS = (('auto', 'Automática'), ('portrait', 'Retrato'), ('landscape', 'Paisagem'))
PER_SHEET = (
    (1, '1 página por folha'),
    (2, '2 páginas por folha'),
    (4, '4 páginas por folha'),
    (6, '6 páginas por folha'),
    (9, '9 páginas por folha'),
)
SCALES = (('fit', 'Ajustar à folha'), ('actual', 'Tamanho real (100%)'), ('custom', 'Personalizada (%)'))
QUALITY = ((150, 'Rascunho (150 dpi)'), (300, 'Normal (300 dpi)'), (600, 'Alta (600 dpi)'))
MARGINS = (('normal', 'Normal (1 cm)'), ('minimum', 'Mínima'))
COLORS = ((False, 'Colorido'), (True, 'Preto e branco'))
DUPLEX = (
    ('none', 'Só frente'),
    ('long', 'Frente e verso (virar na borda longa)'),
    ('short', 'Frente e verso (virar na borda curta)'),
)


def available_printers():
    """(nomes das impressoras instaladas, a padrão)."""
    from PySide6.QtPrintSupport import QPrinterInfo

    names = [info.printerName() for info in QPrinterInfo.availablePrinters()]
    return names, QPrinterInfo.defaultPrinterName()


def edge_path():
    """O msedge.exe instalado (vem com o Windows 10 e 11), ou None se não houver."""
    import os
    import shutil
    import sys

    if sys.platform != 'win32':
        return None
    try:
        import winreg

        key = r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe'
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(root, key) as handle:
                    value = winreg.QueryValue(handle, None)
                if value and os.path.isfile(value):
                    return value
            except OSError:
                continue
    except ImportError:
        pass
    for base in (os.environ.get('ProgramFiles(x86)'), os.environ.get('ProgramFiles')):
        candidate = os.path.join(base or '', 'Microsoft', 'Edge', 'Application', 'msedge.exe')
        if base and os.path.isfile(candidate):
            return candidate
    return shutil.which('msedge')


def _combo(entries):
    combo = QComboBox()
    for value, text in entries:
        combo.addItem(text, value)
    return combo


class PrintDialog(QDialog):
    """exec() devolve 1 (imprimir com estas opções), 0 (cancelou), WINDOWS (usar a janela do Windows) ou EDGE (abrir o
    PDF juntado no Microsoft Edge, para imprimir por ele)."""

    WINDOWS = 2
    EDGE = 3

    def __init__(self, pdf, title='', parent=None, printers=None):
        super().__init__(parent)
        self.setWindowTitle('Imprimir')
        self.setModal(True)
        self.pdf, self.title = str(pdf), title
        self.document = None
        with FITZ_LOCK:
            self.document = fitz.open(self.pdf)
            self.total = self.document.page_count
        self.sheet_index = 0
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(120)
        self._preview_timer.timeout.connect(self.refresh_preview)
        names, default = printers if printers is not None else available_printers()

        root = QHBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(22)
        root.addWidget(self._build_preview(), 1)
        root.addWidget(self._build_options(names, default), 0)
        for kind, signal in (
            (QComboBox, 'currentIndexChanged'),
            (QSpinBox, 'valueChanged'),
            (QCheckBox, 'toggled'),
            (QLineEdit, 'textChanged'),
        ):
            for widget in self.findChildren(kind):
                getattr(widget, signal).connect(self.schedule_preview)
        self.update_controls()
        self.refresh_preview()

    # ---- montagem ------------------------------------------------------------------------
    def _build_preview(self):
        side = QWidget()
        layout = QVBoxLayout(side)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.preview = QLabel()
        self.preview.setObjectName('previewBox')
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(PREVIEW_WIDTH + 20, PREVIEW_HEIGHT + 20)
        self.preview.setAccessibleName('Prévia da folha')
        layout.addWidget(self.preview, 1)
        nav = QHBoxLayout()
        self.prev_button = QPushButton('‹ Anterior')
        self.prev_button.setProperty('size', 'small')
        self.prev_button.clicked.connect(lambda: self.go_to(self.sheet_index - 1))
        self.next_button = QPushButton('Próxima ›')
        self.next_button.setProperty('size', 'small')
        self.next_button.clicked.connect(lambda: self.go_to(self.sheet_index + 1))
        self.sheet_label = QLabel('')
        self.sheet_label.setAlignment(Qt.AlignCenter)
        self.sheet_label.setObjectName('hint')
        nav.addWidget(self.prev_button)
        nav.addWidget(self.sheet_label, 1)
        nav.addWidget(self.next_button)
        layout.addLayout(nav)
        return side

    def _build_options(self, names, default):
        panel = QWidget()
        panel.setFixedWidth(360)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        title = QLabel('Imprimir')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        self.summary = QLabel('')
        self.summary.setObjectName('summary')
        layout.addWidget(self.summary)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(9)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.printer_combo = QComboBox()
        self.printer_combo.addItems(names)
        if default in names:
            self.printer_combo.setCurrentText(default)
        self.printer_combo.currentTextChanged.connect(self.adopt_printer_defaults)
        form.addRow('Impressora', self.printer_combo)

        copies_row = QHBoxLayout()
        self.copies_spin = QSpinBox()
        self.copies_spin.setRange(1, 99)
        self.collate_check = QCheckBox('Agrupar')
        self.collate_check.setChecked(True)
        self.collate_check.setToolTip('Agrupar: 1, 2, 3, 1, 2, 3. Sem agrupar: 1, 1, 2, 2, 3, 3.')
        copies_row.addWidget(self.copies_spin)
        copies_row.addWidget(self.collate_check)
        copies_row.addStretch(1)
        form.addRow('Cópias', copies_row)

        self.pages_combo = _combo((('all', 'Todas as páginas'), ('custom', 'Escolher páginas')))
        form.addRow('Páginas', self.pages_combo)
        self.pages_edit = QLineEdit()
        self.pages_edit.setPlaceholderText('Ex.: 1-3, 5, 8-')
        self.pages_edit.setAccessibleName('Páginas a imprimir')
        form.addRow('', self.pages_edit)

        self.orientation_combo = _combo(ORIENTATIONS)
        form.addRow('Orientação', self.orientation_combo)
        self.paper_combo = _combo((name, name) for name in printing.PAPER_POINTS)
        form.addRow('Papel', self.paper_combo)
        self.per_sheet_combo = _combo(PER_SHEET)
        form.addRow('Por folha', self.per_sheet_combo)
        self.scale_combo = _combo(SCALES)
        form.addRow('Escala', self.scale_combo)
        self.percent_spin = QSpinBox()
        self.percent_spin.setRange(10, 400)
        self.percent_spin.setValue(100)
        self.percent_spin.setSuffix(' %')
        self.percent_spin.setAccessibleName('Escala personalizada em porcentagem')
        form.addRow('', self.percent_spin)
        self.margins_combo = _combo(MARGINS)
        form.addRow('Margens', self.margins_combo)
        self.color_combo = _combo(COLORS)
        form.addRow('Cor', self.color_combo)
        self.duplex_combo = _combo(DUPLEX)
        form.addRow('Lados', self.duplex_combo)
        self.quality_combo = _combo(QUALITY)
        self.quality_combo.setCurrentIndex(self.quality_combo.findData(300))
        form.addRow('Qualidade', self.quality_combo)
        layout.addLayout(form)

        self.error = QLabel('')
        self.error.setProperty('tone', 'error')
        self.error.setWordWrap(True)
        self.error.hide()
        layout.addWidget(self.error)
        layout.addStretch(1)

        self.no_printer = QLabel('Nenhuma impressora instalada neste computador.')
        self.no_printer.setProperty('tone', 'error')
        self.no_printer.setVisible(not names)
        layout.addWidget(self.no_printer)
        buttons = QHBoxLayout()
        self.print_button = QPushButton('Imprimir')
        self.print_button.setProperty('variant', 'primary')
        self.print_button.setDefault(True)
        self.print_button.clicked.connect(self.confirm)
        cancel = QPushButton('Cancelar')
        cancel.clicked.connect(self.reject)
        buttons.addWidget(self.print_button, 1)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        self.windows_button = QPushButton('Janela do Windows (ajustes do driver)…')
        self.windows_button.setProperty('variant', 'quiet')
        self.windows_button.setToolTip('Abre a janela de impressão do Windows, sem prévia, com os ajustes do driver.')
        self.windows_button.clicked.connect(lambda: self.done(self.WINDOWS))
        layout.addWidget(self.windows_button)
        self.edge_button = QPushButton('Abrir no Microsoft Edge…')
        self.edge_button.setProperty('variant', 'quiet')
        self.edge_button.setToolTip(
            'Abre o PDF juntado no Edge, para imprimir pela tela de impressão dele (Ctrl+P). '
            'O arquivo temporário é apagado quando você sai do Unir PDF.'
        )
        self.edge_button.clicked.connect(lambda: self.done(self.EDGE))
        self.edge_button.setVisible(edge_path() is not None)
        layout.addWidget(self.edge_button)
        self.adopt_printer_defaults(self.printer_combo.currentText())
        return panel

    # ---- opções --------------------------------------------------------------------------
    def adopt_printer_defaults(self, name):
        """Ao escolher a impressora, vem o papel e o frente e verso que ela usa por padrão (se forem conhecidos)."""
        if not name:
            return
        try:
            from PySide6.QtGui import QPageSize
            from PySide6.QtPrintSupport import QPrinter, QPrinterInfo

            info = QPrinterInfo.printerInfo(name)
            sizes = {
                QPageSize.PageSizeId.A4: 'A4',
                QPageSize.PageSizeId.Letter: 'Carta',
                QPageSize.PageSizeId.Legal: 'Ofício',
                QPageSize.PageSizeId.A3: 'A3',
            }
            paper = sizes.get(info.defaultPageSize().id())
            if paper:
                self.paper_combo.setCurrentIndex(self.paper_combo.findData(paper))
            duplex = {QPrinter.DuplexLongSide: 'long', QPrinter.DuplexShortSide: 'short'}.get(info.defaultDuplexMode())
            self.duplex_combo.setCurrentIndex(self.duplex_combo.findData(duplex or 'none'))
        except (AttributeError, TypeError):
            pass

    def chosen_pages(self):
        """As páginas pedidas (base 0). Levanta PageRangeError com a mensagem pronta se o texto não serve."""
        if self.pages_combo.currentData() != 'custom':
            return tuple(range(self.total))
        return tuple(parse_page_ranges(self.pages_edit.text(), self.total, allow_duplicates=True))

    def settings(self):
        try:
            pages = self.chosen_pages()
        except PageRangeError:
            pages = tuple(range(self.total))
        return printing.PrintSettings(
            pages=pages,
            per_sheet=self.per_sheet_combo.currentData(),
            orientation=self.orientation_combo.currentData(),
            paper=self.paper_combo.currentData(),
            scale=self.scale_combo.currentData(),
            percent=self.percent_spin.value(),
            dpi=self.quality_combo.currentData(),
            margins=self.margins_combo.currentData(),
            grayscale=bool(self.color_combo.currentData()),
            copies=self.copies_spin.value(),
            collate=self.collate_check.isChecked(),
            duplex=self.duplex_combo.currentData(),
        )

    def sheets(self):
        settings = self.settings()
        return printing.sheets_for(settings.pages, settings.per_sheet)

    def update_controls(self):
        self.pages_edit.setVisible(self.pages_combo.currentData() == 'custom')
        many = (self.per_sheet_combo.currentData() or 1) > 1
        self.scale_combo.setEnabled(not many)
        self.percent_spin.setVisible(self.scale_combo.currentData() == 'custom' and not many)
        self.scale_combo.setToolTip(
            'Com várias páginas por folha, cada página é ajustada ao seu espaço.' if many else ''
        )
        self.collate_check.setEnabled(self.copies_spin.value() > 1)
        try:
            self.chosen_pages()
            self.error.hide()
            valid = True
        except PageRangeError as exc:
            self.error.setText(str(exc))
            self.error.show()
            valid = False
        self.print_button.setEnabled(valid and self.printer_combo.count() > 0)

    def schedule_preview(self, *_args):
        self.update_controls()
        self._preview_timer.start()

    # ---- prévia --------------------------------------------------------------------------
    def go_to(self, index):
        self.sheet_index = index
        self.refresh_preview()

    def refresh_preview(self):
        sheets = self.sheets()
        self.sheet_index = max(0, min(self.sheet_index, len(sheets) - 1))
        settings = self.settings()
        with FITZ_LOCK:
            image = printing.preview_image(self.document, sheets[self.sheet_index], settings, PREVIEW_WIDTH * 2)
        pixmap = QPixmap.fromImage(image).scaled(
            PREVIEW_WIDTH, PREVIEW_HEIGHT, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.preview.setPixmap(pixmap)
        self.sheet_label.setText(f'Folha {self.sheet_index + 1} de {len(sheets)}')
        self.prev_button.setEnabled(self.sheet_index > 0)
        self.next_button.setEnabled(self.sheet_index < len(sheets) - 1)
        pages = len(settings.pages)
        copies = f' · {settings.copies} cópias' if settings.copies > 1 else ''
        self.summary.setText(
            f'{pages} página{"s" if pages != 1 else ""} em {len(sheets)} folha{"s" if len(sheets) != 1 else ""}{copies}'
        )

    # ---- saída ---------------------------------------------------------------------------
    def confirm(self):
        self.update_controls()
        if self.print_button.isEnabled():
            self.accept()

    def make_printer(self):
        """O QPrinter da impressora escolhida (as opções são aplicadas na hora de imprimir)."""
        from PySide6.QtPrintSupport import QPrinter, QPrinterInfo

        printer = QPrinter(QPrinterInfo.printerInfo(self.printer_combo.currentText()), QPrinter.HighResolution)
        if self.title:
            printer.setDocName(self.title)
        return printer

    def done(self, result):
        self._preview_timer.stop()
        if self.document is not None:
            with FITZ_LOCK:
                self.document.close()  # solta o arquivo: o PDF temporário da impressão pode ser apagado depois
            self.document = None
        super().done(result)
