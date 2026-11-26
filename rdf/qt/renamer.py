"""Renomear folhas de ponto (Qt): lê matrícula, nome e mês, e renomeia folhas, atestados e declarações.

Esta tela só apresenta e coleta ações do usuário. Os dados e as regras estão em rdf.core (lote, entrada de
arquivos, análise em paralelo e exportação), que não dependem de nenhuma interface.
"""

import logging
import threading
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

import fitz
from PySide6.QtCore import QObject, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rdf.core import analysis_runner, exporter, inputs
from rdf.core.batch import FILTERS, Batch, read_session_file, row_from_result, status_tone
from rdf.core.config import OUTPUT_FORMATS
from rdf.core.io_files import INPUT_EXTENSIONS
from rdf.qt import dialogs
from rdf.qt.busy import Responsive
from rdf.qt.preview import PageLoader, PreviewView
from rdf.qt.widgets import BackButton

LOGGER = logging.getLogger('rdf')

COLUMNS = ('Arquivo original', 'Novo nome', 'Leitura', 'Confiança', 'Status')
TONES = {  # (cor do texto, fundo) de cada status na tabela
    'ok': ('#176b3a', None),
    'approved': ('#075985', None),
    'review': ('#7a4300', '#fff1cc'),
    'error': ('#8f1713', '#ffd9d6'),
}
NARROW_BELOW = 1100  # abaixo desta largura: sem as colunas Leitura/Confiança, botões e prévia mais enxutos
SHORT_BELOW = 580
SAVE_DELAY_MS = 400
SELECT_DELAY_MS = 140
CHECKPOINT_EVERY = 10
PREVIEW_CACHE = 3
FILE_PATTERN = 'Documentos e imagens (*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;Todos os arquivos (*.*)'


class _AnalysisWorker(QObject):
    """Roda a análise fora da thread da janela; só se comunica por sinais."""

    row = Signal(object)
    error = Signal(object)
    progress = Signal(int, int, str)
    fatal = Signal(object)
    finished = Signal()

    def __init__(self, files, pages, build_row, cancel_event, discard_event, analyze):
        super().__init__()
        self.files, self.pages, self.build_row = files, pages, build_row
        self.cancel_event, self.discard_event, self.analyze = cancel_event, discard_event, analyze

    def run(self):
        def emit(kind, data):
            if kind == 'result':
                self.row.emit(data)
            elif kind == 'error':
                self.error.emit(data)
            elif kind == 'progress':
                self.progress.emit(*data)
            elif kind == 'fatal':
                self.fatal.emit(data)

        analysis_runner.run_analysis(
            self.files, self.pages, self.build_row, emit, self.cancel_event, self.discard_event, analyze=self.analyze
        )
        self.finished.emit()


def make_card(padding=18):
    card = QFrame()
    card.setObjectName('card')
    layout = QVBoxLayout(card)
    layout.setContentsMargins(padding, padding, padding, padding)
    return card, layout


def small_button(text, tooltip=None):
    button = QPushButton(text)
    button.setProperty('size', 'small')
    if tooltip:
        button.setToolTip(tooltip)
    return button


def vertical_line():
    line = QFrame()
    line.setFixedWidth(1)
    line.setStyleSheet('QFrame { background: #e0e6eb; border: none; }')
    return line


class RenamerPage(QWidget):
    backRequested = Signal()
    save_label = 'Exportar agora'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.batch = Batch()
        self.items = {}  # caminho -> linha da tabela
        self.analyze_function = None  # None: o leitor de verdade (rdf.core.ocr); os testes colocam um falso
        self.analysis_running = False
        self.analysis_cancelled = False
        self.analysis_discard = False
        self.analysis_completed = 0
        self.analysis_files = []
        self.analysis_snapshot = None
        self.last_checkpoint = 0
        self.cancel_event = threading.Event()
        self.discard_event = threading.Event()
        self._thread = None
        self._worker = None
        self.close_warning_shown = False
        self.density = (None, None)
        self.preview_path = None
        self.preview_page = 0
        self.preview_total = 0
        self.preview_request = 0
        self.preview_cache = OrderedDict()
        self.setAcceptDrops(True)

        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(SAVE_DELAY_MS)
        self.save_timer.timeout.connect(self.save_now)
        self.select_timer = QTimer(self)
        self.select_timer.setSingleShot(True)
        self.select_timer.setInterval(SELECT_DELAY_MS)
        self.select_timer.timeout.connect(self.show_selected)
        self.loader = PageLoader(self)
        self.loader.loaded.connect(self.on_preview_loaded)
        self.loader.failed.connect(self.on_preview_failed)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 22, 36, 16)
        outer.setSpacing(14)
        self.shell_layout = outer
        outer.setSizeConstraint(QLayout.SetNoConstraint)  # quem manda no tamanho é a janela, não os textos
        outer.addWidget(self._build_toolbar())
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(14)
        self.splitter.addWidget(self._build_list_card())
        self.splitter.addWidget(self._build_preview_card())
        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([760, 400])
        outer.addWidget(self.splitter, 1)
        outer.addLayout(self._build_footer())
        self.set_status('Comece selecionando documentos, imagens ou uma pasta.')
        self.update_summary()
        self.update_buttons()
        self.update_page_controls()
        self.preview.set_message('Selecione um arquivo para ver a página.')

    # ---- montagem ------------------------------------------------------------------------
    def _build_toolbar(self):
        card, layout = make_card(14)
        row = QHBoxLayout()
        row.setSpacing(0)
        layout.addLayout(row)

        # Voltar fica dentro do cartão, à esquerda das etapas (sem coluna vazia na janela).
        self.back_button = BackButton()
        self.back_button.clicked.connect(self.backRequested)
        lead = QVBoxLayout()
        lead.addSpacing(22)  # alinha com o primeiro botão das etapas (abaixo do título de cada uma)
        lead.addWidget(self.back_button, 0, Qt.AlignTop)
        lead.addStretch(1)
        row.addLayout(lead)
        row.addSpacing(16)
        row.addWidget(vertical_line())
        row.addSpacing(16)

        step1 = QVBoxLayout()
        step1.setSpacing(6)
        step1.addWidget(self._caption('1 · Adicionar'))
        self.select_files_btn = QPushButton('Adicionar arquivos')
        self.select_files_btn.clicked.connect(self.select_files)
        self.select_folder_btn = QPushButton('Selecionar pasta')
        self.select_folder_btn.clicked.connect(self.select_folder)
        step1.addWidget(self.select_files_btn)
        step1.addWidget(self.select_folder_btn)

        step2 = QVBoxLayout()
        step2.setSpacing(6)
        step2.addWidget(self._caption('2 · Analisar'))
        self.analyze_btn = QPushButton('Iniciar análise')
        self.analyze_btn.setProperty('variant', 'primary')
        self.analyze_btn.clicked.connect(lambda: self.start_analysis())
        self.verify_btn = QPushButton('Verificar selecionados')
        self.verify_btn.clicked.connect(lambda: self.start_analysis(selected_only=True))
        step2.addWidget(self.analyze_btn)
        step2.addWidget(self.verify_btn)

        step3 = QVBoxLayout()
        step3.setSpacing(6)
        step3.addWidget(self._caption('3 · Aprovar e exportar'))
        approve_row = QHBoxLayout()
        approve_row.setSpacing(6)
        self.approve_btn = QPushButton('Folha')
        self.approve_btn.setToolTip('Aprovar os selecionados como folha de ponto')
        self.approve_btn.clicked.connect(self.approve_selected)
        self.approve_atestado_btn = QPushButton('Atestado')
        self.approve_atestado_btn.setToolTip('Aprovar os selecionados como atestado')
        self.approve_atestado_btn.clicked.connect(lambda: self.approve_as_category('Atestados'))
        self.approve_declaracao_btn = QPushButton('Declaração')
        self.approve_declaracao_btn.setToolTip('Aprovar os selecionados como declaração')
        self.approve_declaracao_btn.clicked.connect(lambda: self.approve_as_category('Declarações'))
        for button in (self.approve_btn, self.approve_atestado_btn, self.approve_declaracao_btn):
            approve_row.addWidget(button, 1)
        export_row = QHBoxLayout()
        export_row.setSpacing(6)
        self.export_btn = QPushButton('Exportar arquivos')
        self.export_btn.setProperty('variant', 'success')
        self.export_btn.clicked.connect(self.export)
        self.format_combo = QComboBox()
        self.format_combo.addItems(list(OUTPUT_FORMATS))
        self.format_combo.setToolTip('Formato dos arquivos exportados')
        self.format_combo.setAccessibleName('Formato dos arquivos exportados')
        self.format_combo.textActivated.connect(self.on_format_changed)
        export_row.addWidget(self.export_btn, 1)
        export_row.addWidget(self.format_combo)
        step3.addLayout(approve_row)
        step3.addLayout(export_row)

        # Todos os botões da barra com a mesma altura: as três etapas ficam alinhadas.
        for widget in (
            self.select_files_btn,
            self.select_folder_btn,
            self.analyze_btn,
            self.verify_btn,
            self.approve_btn,
            self.approve_atestado_btn,
            self.approve_declaracao_btn,
            self.export_btn,
            self.format_combo,
        ):
            widget.setFixedHeight(40)
        for step in (step1, step2):
            step.addStretch(1)
        self.steps = (step1, step2, step3)
        for position, step in enumerate(self.steps):
            if position:
                row.addSpacing(16)
                row.addWidget(vertical_line())
                row.addSpacing(16)
            row.addLayout(step, 3 if position == 2 else 2)
        return card

    @staticmethod
    def _caption(text):
        label = QLabel(text)
        label.setObjectName('caption')
        return label

    def _build_list_card(self):
        card, layout = make_card(16)
        layout.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel('Arquivos do lote')
        title.setObjectName('cardTitle')
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(list(FILTERS))
        self.filter_combo.setToolTip('Mostrar só os arquivos neste estado')
        self.filter_combo.setAccessibleName('Filtrar por estado')
        self.filter_combo.textActivated.connect(self.on_filter_changed)
        self.edit_btn = small_button('Editar dados', 'Corrigir matrícula, nome e mês do arquivo selecionado')
        self.edit_btn.clicked.connect(self.edit_selected)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.filter_combo)
        head.addWidget(self.edit_btn)
        layout.addLayout(head)
        self.summary_label = QLabel('')
        self.summary_label.setObjectName('summary')
        self.summary_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(self.summary_label)

        naming = QHBoxLayout()
        naming.setSpacing(12)
        label = QLabel('Nome final:')
        label.setObjectName('fieldLabel')
        naming.addWidget(label)
        self.chapa_check = QCheckBox('Matrícula/Chapa')
        self.nome_check = QCheckBox('Nome')
        self.mes_check = QCheckBox('Mês da folha')
        for check in (self.chapa_check, self.nome_check, self.mes_check):
            check.setChecked(True)
            check.clicked.connect(self.on_naming_changed)
            naming.addWidget(check)
        naming.addStretch(1)
        self.order_hint = QLabel('Ordem: Matrícula - Nome - Mês')
        self.order_hint.setObjectName('hint')
        self.order_hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        naming.addWidget(self.order_hint)
        layout.addLayout(naming)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(COLUMNS))
        self.tree.setHeaderLabels(list(COLUMNS))
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for column in (2, 3, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.tree.setColumnWidth(0, 220)
        self.tree.setAccessibleName('Arquivos do lote')
        self.tree.itemSelectionChanged.connect(self.on_selection_changed)
        self.tree.itemDoubleClicked.connect(lambda *_: self.edit_selected())
        self.tree.customContextMenuRequested.connect(self.show_context_menu)
        for keys, handler in (
            ((Qt.Key_Delete,), self.remove_selected),
            ((Qt.Key_Return, Qt.Key_Enter, Qt.Key_F2), self.edit_selected),
        ):
            for key in keys:
                QShortcut(QKeySequence(key), self.tree, activated=handler, context=Qt.WidgetShortcut)
        layout.addWidget(self.tree, 1)
        self.tip_label = QLabel(
            'Dica: selecione vários arquivos com Shift ou Ctrl. Clique com o botão direito para mais ações.'
        )
        self.tip_label.setObjectName('hint')
        self.tip_label.setWordWrap(True)
        layout.addWidget(self.tip_label)
        return card

    def _build_preview_card(self):
        card, layout = make_card(16)
        layout.setSpacing(8)
        title = QLabel('Prévia da página inteira')
        title.setObjectName('cardTitle')
        layout.addWidget(title)
        zoom_row = QHBoxLayout()
        zoom_row.setSpacing(6)
        self.zoom_label = QLabel('100%')
        self.zoom_label.setObjectName('hint')
        self.zoom_out_btn = small_button('−', 'Diminuir (Ctrl -)')
        self.zoom_in_btn = small_button('+', 'Aumentar (Ctrl +)')
        self.fit_btn = small_button('Ajustar', 'Ajustar a página à largura')
        self.zoom_out_btn.setAccessibleName('Diminuir o zoom')
        self.zoom_in_btn.setAccessibleName('Aumentar o zoom')
        self.zoom_out_btn.clicked.connect(lambda: self.preview.zoom_by(1 / 1.2))
        self.zoom_in_btn.clicked.connect(lambda: self.preview.zoom_by(1.2))
        self.fit_btn.clicked.connect(lambda: self.preview.fit())
        zoom_row.addStretch(1)
        zoom_row.addWidget(self.zoom_label)
        zoom_row.addWidget(self.zoom_out_btn)
        zoom_row.addWidget(self.zoom_in_btn)
        zoom_row.addWidget(self.fit_btn)
        layout.addLayout(zoom_row)
        nav = QHBoxLayout()
        nav.setSpacing(6)
        self.prev_page_btn = small_button('Página anterior')
        self.prev_page_btn.clicked.connect(lambda: self.change_page(-1))
        self.page_label = QLabel('Página 0 de 0')
        self.page_label.setObjectName('hint')
        self.page_label.setAlignment(Qt.AlignCenter)
        self.next_page_btn = small_button('Próxima página')
        self.next_page_btn.clicked.connect(lambda: self.change_page(1))
        nav.addWidget(self.prev_page_btn)
        nav.addWidget(self.page_label, 1)
        nav.addWidget(self.next_page_btn)
        layout.addLayout(nav)
        self.preview = PreviewView()
        self.preview.zoomChanged.connect(lambda zoom: self.zoom_label.setText(f'{zoom:.0%}'))
        layout.addWidget(self.preview, 1)
        for sequence, factor in (('Ctrl++', 1.2), ('Ctrl+=', 1.2), ('Ctrl+-', 1 / 1.2)):
            QShortcut(QKeySequence(sequence), self, activated=lambda f=factor: self.preview.zoom_by(f))
        return card

    def _build_footer(self):
        footer = QHBoxLayout()
        footer.setContentsMargins(2, 0, 2, 0)
        footer.setSpacing(12)
        self.status_label = QLabel('')
        self.status_label.setObjectName('status')
        self.status_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)  # texto longo não alarga a janela
        self.cancel_btn = QPushButton('Cancelar análise')
        self.cancel_btn.clicked.connect(self.request_cancel_analysis)
        self.cancel_btn.setEnabled(False)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(210)
        footer.addWidget(self.status_label, 1)
        footer.addWidget(self.cancel_btn)
        footer.addWidget(self.progress)
        return footer

    # ---- mensagens (pontos de troca nos testes) ------------------------------------------
    def warn(self, title, text):
        QMessageBox.warning(self, title, text)

    def error(self, title, text):
        QMessageBox.critical(self, title, text)

    def info(self, title, text):
        QMessageBox.information(self, title, text)

    def ask(self, title, text):
        return (
            QMessageBox.question(self, title, text, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes
        )

    def ask_multipage(self, path, total):
        return dialogs.multipage_dialog(self, path, total)

    def ask_edit(self, row):
        return dialogs.edit_dialog(self, row)

    def ask_cancel_analysis(self):
        return dialogs.cancel_analysis_dialog(self)

    def ask_review_export(self, review):
        return dialogs.review_export_dialog(self, review)

    def ask_blocking_export(self, problems):
        return dialogs.blocking_export_dialog(self, problems)

    def choose_files(self):
        paths, _filter = QFileDialog.getOpenFileNames(self, 'Escolha os documentos', '', FILE_PATTERN)
        return paths

    def choose_folder(self, title='Escolha a pasta'):
        return QFileDialog.getExistingDirectory(self, title)

    def set_status(self, text):
        self.status_label.setText(text)
        self.status_label.setToolTip(text)

    # ---- tabela --------------------------------------------------------------------------
    def selected_paths(self):
        chosen = {item.data(0, Qt.UserRole) for item in self.tree.selectedItems()}
        return [path for path in self.batch.files if path in chosen]

    def rebuild_tree(self):
        self.tree.clear()
        self.items = {}
        for path in self.batch.files:
            item = QTreeWidgetItem([''] * len(COLUMNS))
            item.setData(0, Qt.UserRole, path)
            self.tree.addTopLevelItem(item)
            self.items[path] = item
            self.refresh_item(path)
        self.apply_filter()
        self.update_summary()
        self.update_buttons()

    def refresh_item(self, path):
        item = self.items.get(path)
        if item is None:
            return
        values = self.batch.row_values(path)
        foreground, background = TONES[status_tone(values[4])]
        for column, value in enumerate(values):
            item.setText(column, value)
            item.setForeground(column, QBrush(QColor(foreground)))
            item.setBackground(column, QBrush(QColor(background)) if background else QBrush())
        item.setToolTip(0, str(self.batch.source(path)))
        item.setToolTip(1, values[1])

    def refresh_all(self):
        for path in self.items:
            self.refresh_item(path)
        self.update_summary()
        self.apply_filter()

    def apply_filter(self, announce=False):
        visible = set(self.batch.visible_paths())
        for path, item in self.items.items():
            hidden = path not in visible
            item.setHidden(hidden)
            if hidden and item.isSelected():
                item.setSelected(False)
        if self.preview_path and self.preview_path not in visible:
            self.clear_preview()
        self.update_buttons()
        if announce:
            self.set_status(
                f'Filtro {self.batch.filter_status}: {len(visible)} de {len(self.batch.files)} arquivo(s) exibido(s).'
            )

    def update_summary(self):
        self.summary_label.setText(self.batch.summary_text())

    def update_buttons(self):
        selected = bool(self.tree.selectedItems())
        self.verify_btn.setEnabled(selected and not self.analysis_running)
        self.edit_btn.setEnabled(len(self.tree.selectedItems()) == 1 and not self.analysis_running)

    def sync_controls(self):
        """Põe nos campos da tela o que está no lote (depois de recuperar uma sessão, por exemplo)."""
        self.chapa_check.setChecked(self.batch.include_chapa)
        self.nome_check.setChecked(self.batch.include_nome)
        self.mes_check.setChecked(self.batch.include_mes)
        self.format_combo.setCurrentText(self.batch.output_format)
        self.filter_combo.setCurrentText(self.batch.filter_status)

    def on_selection_changed(self):
        self.update_buttons()
        self.select_timer.start()

    def on_filter_changed(self, text):
        self.batch.filter_status = text
        self.apply_filter(announce=True)
        self.schedule_save()

    def on_naming_changed(self):
        self.batch.set_options(self.chapa_check.isChecked(), self.nome_check.isChecked(), self.mes_check.isChecked())
        self.batch.refresh_names()
        self.refresh_all()
        self.schedule_save()

    def on_format_changed(self, text):
        fmt = self.batch.set_output_format(text)
        self.format_combo.setCurrentText(fmt)
        self.batch.refresh_names()
        self.refresh_all()
        self.schedule_save()
        self.set_status(f'Formato de exportação: {fmt}.')  # depois do refresh, para não ser trocado

    # ---- entrada de arquivos -------------------------------------------------------------
    def select_files(self):
        paths = self.choose_files()
        if paths:
            self.add_candidates(paths)

    def select_folder(self):
        folder = self.choose_folder('Escolha a pasta com os documentos')
        if folder:
            self.add_candidates(inputs.candidates_from([folder]))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self.analysis_running:
            event.acceptProposedAction()

    def dropEvent(self, event):
        if self.analysis_running:
            return
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        found = inputs.candidates_from(paths)
        event.acceptProposedAction()
        if found:
            self.add_candidates(found)
        else:
            self.warn('Arrastar e soltar', 'Nenhum arquivo compatível foi encontrado.')

    def add_candidates(self, paths):
        self.add_files(self.prepare_input_paths(paths))

    def current_sources(self):
        return [self.batch.source(path) for path in self.batch.files]

    def prepare_input_paths(self, paths):
        """Confere os limites, converte imagens em PDF e pergunta o que fazer com PDFs de várias páginas."""
        check = inputs.check_batch_limits(self.current_sources(), paths)
        if check.error:
            self.error(*check.error)
            return []
        if check.large and not self.ask('Arquivos grandes', inputs.large_files_message(check.large)):
            return []
        prepared = []
        responsive = Responsive()
        for position, raw in enumerate(check.incoming, start=1):
            self.set_status(f'Preparando {position} de {len(check.incoming)}: {Path(raw).name}')
            responsive.pulse()
            original = str(Path(raw))
            if Path(original).suffix.lower() not in INPUT_EXTENSIONS or not Path(original).is_file():
                continue
            name = Path(original).name
            try:
                path, source, generated = inputs.normalize_input_file(original)
            except Exception as exc:
                self.error('Arquivo inválido', f'{name} foi rejeitado:\n{exc}')
                continue
            if generated:
                self.batch.generated_files.add(path)
            self.batch.original_sources[path] = source
            try:
                total = inputs.pdf_page_total(path)
            except Exception as exc:
                LOGGER.warning('Arquivo inválido %s: %s', path, exc)
                self.error(
                    'Arquivo inválido',
                    f'Não foi possível abrir {name}:\nO conteúdo do arquivo não corresponde a um documento suportado.',
                )
                continue
            if total <= 1:
                prepared.append(path)
                self.batch.analysis_pages[path] = 0
                continue
            choice, page = self.ask_multipage(path, total)
            if choice == 'split':
                try:
                    pages = inputs.split_pdf_pages(path)
                except Exception as exc:
                    self.error('Separar PDF', f'Não foi possível separar {Path(path).name}:\n{exc}')
                    continue
                self.batch.generated_files.update(pages)
                for item in pages:
                    self.batch.analysis_pages[item] = 0
                    self.batch.original_sources[item] = source
                prepared.extend(pages)
            elif choice == 'keep':
                prepared.append(path)
                self.batch.analysis_pages[path] = page
        return prepared

    def add_files(self, paths):
        added = self.batch.add(paths)
        if not added:
            self.set_status('Os arquivos arrastados já estão no lote.')
            return
        self.rebuild_tree()
        self.sync_controls()
        self.set_status(f'{added} arquivo(s) adicionado(s). Total: {len(self.batch.files)}.')
        self.schedule_save()

    # ---- análise -------------------------------------------------------------------------
    @property
    def running(self):
        return self.analysis_running

    def set_busy(self, busy):
        self.analysis_running = busy
        for widget in (
            self.select_files_btn,
            self.select_folder_btn,
            self.analyze_btn,
            self.approve_btn,
            self.approve_atestado_btn,
            self.approve_declaracao_btn,
            self.export_btn,
            self.filter_combo,
            self.format_combo,
            self.chapa_check,
            self.nome_check,
            self.mes_check,
        ):
            widget.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)
        self.update_buttons()

    def start_analysis(self, selected_only=False):
        if self.analysis_running:
            return
        if not self.batch.files:
            self.warn('Aviso', 'Selecione os arquivos primeiro.')
            return
        if selected_only:
            paths = self.selected_paths()
            if not paths:
                self.warn('Verificar selecionados', 'Selecione um ou mais arquivos para verificar.')
                return
        else:
            paths = list(self.batch.files)
        options, fmt = self.batch.options, self.batch.output_format
        sources, pages = dict(self.batch.original_sources), dict(self.batch.analysis_pages)
        self.analysis_files = list(paths)
        self.analysis_cancelled = self.analysis_discard = False
        self.analysis_completed = self.last_checkpoint = 0
        self.cancel_event, self.discard_event = threading.Event(), threading.Event()
        self.analysis_snapshot = self.batch.begin_analysis(paths, selected_only)
        self.preview_cache.clear()
        for path in paths:
            self.refresh_item(path)
        self.progress.setRange(0, len(paths))
        self.progress.setValue(0)
        if selected_only:
            self.set_status(f'Verificando {len(paths)} arquivo(s) selecionado(s).')
        self.set_busy(True)
        self.update_summary()

        def build_row(path, result):
            return row_from_result(path, result, options, fmt, sources, pages.get(path, 0))

        self._thread = QThread(self)
        self._worker = _AnalysisWorker(
            self.analysis_files, pages, build_row, self.cancel_event, self.discard_event, self.analyze_function
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.row.connect(self.on_analysis_row)
        self._worker.error.connect(self.on_analysis_error)
        self._worker.progress.connect(self.on_analysis_progress)
        self._worker.fatal.connect(self.on_analysis_fatal)
        self._worker.finished.connect(self.finish_analysis)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def request_cancel_analysis(self):
        if not self.analysis_running:
            return
        choice = self.ask_cancel_analysis()
        if choice == 'continue' or not self.analysis_running:
            return
        self.analysis_cancelled = True
        self.analysis_discard = choice == 'discard'
        if self.analysis_discard:
            self.discard_event.set()
        self.cancel_event.set()
        self.cancel_btn.setEnabled(False)
        self.set_status('Cancelamento solicitado. Finalizando os arquivos que já estão em leitura...')

    def on_analysis_row(self, row):
        self.batch.accept_row(row)
        self.refresh_item(row['path'])
        self.update_summary()
        self.apply_filter()
        if self.analysis_completed - self.last_checkpoint >= CHECKPOINT_EVERY:
            self.last_checkpoint = self.analysis_completed
            self.schedule_save()

    def on_analysis_error(self, payload):
        path, error = payload
        self.batch.set_error(path, error)
        self.refresh_item(path)
        self.set_status(f'Erro em {Path(path).name}: {str(error)[:100]}')
        self.update_summary()
        self.schedule_save()

    def on_analysis_progress(self, done, total, path):
        self.analysis_completed = done
        self.progress.setValue(done)
        action = 'Finalizando' if self.cancel_event.is_set() else 'Processando'
        self.set_status(f'{action} {done} de {total}: {self.batch.display_name(path)}')

    def on_analysis_fatal(self, error):
        self.error('Análise interrompida', f'A análise foi interrompida:\n{error}')

    def finish_analysis(self):
        cancelled, discard = self.analysis_cancelled, self.analysis_discard
        self.set_busy(False)
        self.format_combo.setCurrentText(self.batch.set_output_format(self.format_combo.currentText()))
        if discard:
            self.batch.restore_snapshot(self.analysis_snapshot or {})
            self.refresh_all()
            self.progress.setValue(0)
            self.set_status('Análise cancelada. O estado anterior foi restaurado.')
        elif cancelled:
            pending = len(self.batch.pending(self.analysis_files))
            self.set_status(f'Análise cancelada. {self.analysis_completed} processado(s); {pending} pendente(s).')
            self.info(
                'Análise cancelada',
                f'{self.analysis_completed} arquivo(s) foram processados.\n{pending} arquivo(s) continuam pendentes.',
            )
        else:
            self.set_status('Análise concluída. Revise os itens antes de exportar.')
        self.update_summary()
        self.apply_filter()
        self.schedule_save()

    # ---- ações sobre os selecionados -----------------------------------------------------
    def _need_idle(self, text='Aguarde a análise terminar.'):
        if self.analysis_running:
            self.warn('Análise em andamento', text)
            return False
        return True

    def approve_selected(self):
        if not self._need_idle():
            return
        paths = self.selected_paths()
        if not paths:
            self.warn('Aviso', 'Selecione um ou mais arquivos para aprovar.')
            return
        changed = self.batch.approve(paths)
        for path in paths:
            self.refresh_item(path)
        self.update_summary()
        self.apply_filter()
        self.schedule_save()
        self.set_status(f'{changed} arquivo(s) aprovado(s).')

    def approve_as_category(self, category):
        if not self._need_idle():
            return
        paths = self.selected_paths()
        if not paths:
            self.warn('Aviso', 'Selecione um ou mais arquivos.')
            return
        changed = self.batch.approve_as_category(paths, category)
        for path in paths:
            self.refresh_item(path)
        self.update_summary()
        self.apply_filter()
        self.schedule_save()
        label = 'atestado' if category == 'Atestados' else 'declaração'
        self.set_status(f'{changed} arquivo(s) aprovado(s) como {label}.')

    def mark_for_review(self):
        if not self._need_idle():
            return
        paths = self.selected_paths()
        if not paths:
            self.warn('Seleção', 'Selecione um ou mais arquivos.')
            return
        changed = self.batch.mark_review(paths)
        for path in paths:
            self.refresh_item(path)
        self.update_summary()
        self.apply_filter()
        self.schedule_save()
        self.set_status(f'{changed} arquivo(s) marcado(s) para revisão.')

    def single_path(self):
        selected = self.selected_paths()
        if len(selected) != 1:
            self.warn('Seleção', 'Selecione exatamente um arquivo.')
            return None
        return selected[0]

    def edit_selected(self):
        if not self._need_idle('Aguarde a análise terminar para editar os arquivos.'):
            return
        path = self.single_path()
        if not path:
            return
        data = self.ask_edit(self.batch.rows.get(path, {}))
        if data is None:
            return
        self.batch.correct(path, data)
        self.refresh_item(path)
        self.update_summary()
        self.apply_filter()
        self.schedule_save()

    def remove_selected(self):
        if self.analysis_running:
            self.warn('Análise em andamento', 'Não é possível remover arquivos durante a análise.')
            return
        paths = self.selected_paths()
        if not paths:
            return
        if not self.ask(
            'Remover do lote',
            f'Remover {len(paths)} arquivo(s) do lote?\n\nOs arquivos originais não serão excluídos.',
        ):
            return
        inputs.cleanup_generated_files(paths)
        for path in self.batch.remove(paths):
            self.batch.generated_files.discard(path)
            for key in list(self.preview_cache):
                if key[0] == path:
                    self.preview_cache.pop(key, None)
        if self.preview_path in set(paths):
            self.clear_preview()
        self.rebuild_tree()
        self.schedule_save()
        self.set_status(f'{len(paths)} arquivo(s) removido(s) do lote.')

    def open_selected_file(self):
        path = self.single_path()
        if not path:
            return
        original = self.batch.source(path)
        if not Path(original).is_file():
            self.error('Abrir arquivo', f'Não foi possível abrir o arquivo:\n{original}')
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(original))

    def open_selected_folder(self):
        path = self.single_path()
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.batch.source(path)).parent)))

    def copy_text(self, text, description):
        QApplication.clipboard().setText(text)
        self.set_status(f'{description} copiado para a área de transferência.')

    def copy_selected_path(self):
        path = self.single_path()
        if path:
            self.copy_text(self.batch.source(path), 'Caminho original')

    def copy_selected_new_name(self):
        path = self.single_path()
        if not path:
            return
        name = self.batch.new_name(path).strip()
        if not name:
            self.warn('Copiar novo nome', 'O arquivo ainda não possui um novo nome.')
            return
        self.copy_text(name, 'Novo nome')

    def show_properties(self):
        path = self.single_path()
        if not path:
            return
        original = Path(self.batch.source(path))
        try:
            stat = original.stat()
            details = [
                f'Nome: {original.name}',
                f'Local: {original.parent}',
                f'Tipo: {original.suffix[1:].upper() or "Desconhecido"}',
                f'Tamanho: {stat.st_size / 1024:.1f} KB',
                f'Modificado: {datetime.fromtimestamp(stat.st_mtime).astimezone().strftime("%d/%m/%Y %H:%M:%S")}',
            ]
            if original.suffix.lower() == '.pdf':
                with fitz.open(original) as document:
                    details.append(f'Páginas: {len(document)}')
            self.info('Propriedades do arquivo', '\n'.join(details))
        except (OSError, RuntimeError) as exc:
            self.error('Propriedades do arquivo', f'Não foi possível ler as propriedades:\n{exc}')

    def show_context_menu(self, position):
        item = self.tree.itemAt(position)
        if item is None:
            return
        if not item.isSelected():
            self.tree.clearSelection()
            item.setSelected(True)
        count = len(self.tree.selectedItems())
        locked = self.analysis_running
        single = count == 1 and not locked
        menu = QMenu(self)
        entries = (
            ('Abrir arquivo original', self.open_selected_file, single),
            ('Abrir pasta do arquivo', self.open_selected_folder, single),
            ('Copiar como caminho', self.copy_selected_path, single),
            ('Propriedades', self.show_properties, single),
            None,
            ('Verificar arquivo selecionado', lambda: self.start_analysis(selected_only=True), single),
            ('Editar nome e dados', self.edit_selected, single),
            None,
            ('Aprovar como folha de ponto', self.approve_selected, not locked),
            ('Aprovar como atestado', lambda: self.approve_as_category('Atestados'), not locked),
            ('Aprovar como declaração', lambda: self.approve_as_category('Declarações'), not locked),
            ('Marcar para revisar', self.mark_for_review, not locked),
            None,
            ('Copiar novo nome', self.copy_selected_new_name, single),
            ('Remover do lote', self.remove_selected, not locked),
            None,
            ('Limpar dados da sessão', self.clear_session_data, not locked),
        )
        for entry in entries:
            if entry is None:
                menu.addSeparator()
                continue
            text, handler, enabled = entry
            action = menu.addAction(text)
            action.setEnabled(enabled)
            action.triggered.connect(lambda _checked=False, h=handler: h())
        menu.exec(self.tree.viewport().mapToGlobal(position))

    # ---- exportação ----------------------------------------------------------------------
    def show_files(self, paths, filter_name):
        """Mostra só o grupo pedido (revisar ou bloqueados), seleciona o primeiro e abre a prévia dele."""
        self.batch.filter_status = filter_name
        self.filter_combo.setCurrentText(filter_name)
        self.apply_filter()
        visible = [path for path in paths if path in self.items and not self.items[path].isHidden()]
        self.tree.clearSelection()
        if visible:
            self.items[visible[0]].setSelected(True)
            self.tree.scrollToItem(self.items[visible[0]])
            self.show_selected()
        return visible

    def export(self):
        if not self.batch.files:
            self.warn('Aviso', 'Selecione e analise os arquivos primeiro.')
            return
        problems = exporter.export_problems(self.batch)
        review = [path for path in self.batch.files if self.batch.status(path) == 'REVISAR']
        if problems:
            if self.ask_blocking_export(problems) == 'show':
                shown = self.show_files([path for path, _reason in problems], 'Bloqueados')
                self.set_status(f'{len(shown)} arquivo(s) bloqueado(s) destacados em vermelho.')
            else:
                self.set_status(f'Exportação bloqueada: {len(problems)} arquivo(s) precisam de correção.')
            return
        if review:
            choice = self.ask_review_export(review)
            if choice == 'review':
                shown = self.show_files(review, 'Revisar')
                self.set_status(f'{len(shown)} arquivo(s) para revisar destacados em amarelo.')
                return
            if choice != 'proceed':
                self.set_status('Exportação cancelada pelo usuário.')
                return
        if not exporter.exportable_items(self.batch):
            self.warn('Aviso', 'Não há arquivos válidos para exportar.')
            return
        chosen = self.choose_folder('Escolha onde salvar os arquivos renomeados')
        if not chosen:
            self.set_status('Exportação cancelada.')
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        responsive = Responsive()

        def progress(done, total):
            self.set_status(f'Exportando {done + 1} de {total}...')
            responsive.pulse()

        self.export_btn.setEnabled(False)
        try:
            result = exporter.export_batch(self.batch, chosen, progress=progress)
        finally:
            self.export_btn.setEnabled(True)
            QApplication.restoreOverrideCursor()
        if result.failures:
            names = '\n'.join(f'- {self.batch.display_name(path)}' for path, _why in result.failures[:8])
            self.set_status(f'Exportação parcial: {result.count} copiado(s), {len(result.failures)} falha(s).')
            self.error(
                'Exportação parcial',
                f'{result.count} arquivo(s) foram exportados, mas {len(result.failures)} entrada(s) falharam:\n\n'
                f'{names}\n\nA sessão foi mantida para nova tentativa.',
            )
            self.schedule_save()
            return
        self.set_status(f'{result.count} arquivo(s) exportado(s) para {chosen}')
        self.save_timer.stop()
        Batch.discard_session_file()
        self.batch.persistence_disabled = True
        warning = f'\n\nIncluídos com aviso: {len(review)} arquivo(s) em revisão.' if review else ''
        self.info(
            'Concluído',
            f'{result.count} arquivo(s) exportado(s) para:\n{chosen}\n\nSeparados automaticamente:'
            f'\n- Atestados: {result.separated["Atestados"]}'
            f'\n- Declarações: {result.separated["Declarações"]}{warning}',
        )

    # ---- sessão --------------------------------------------------------------------------
    def schedule_save(self):
        if not self.batch.persistence_disabled:
            self.save_timer.start()

    def save_now(self):
        self.batch.save_session()

    def offer_restore_session(self):
        """Ao abrir a tela: oferece continuar o lote da última vez, se houver um salvo."""
        if self.batch.files:
            return
        try:
            data = read_session_file()
        except Exception:
            LOGGER.exception('Falha ao recuperar sessão')
            Batch.discard_session_file()
            self.warn('Sessão descartada', 'A sessão anterior estava danificada e foi descartada.')
            return
        if not data:
            return
        existing = [path for path in data.get('files', []) if Path(path).is_file()]
        if not existing:
            return
        if not self.ask(
            'Recuperar sessão', f'Foi encontrada uma sessão com {len(existing)} arquivo(s). Deseja continuar?'
        ):
            Batch.discard_session_file()
            return
        try:
            self.batch.restore_session(data, existing)
        except Exception:
            LOGGER.exception('Falha ao restaurar sessão')
            Batch.discard_session_file()
            self.warn('Sessão descartada', 'A sessão anterior estava danificada e foi descartada.')
            return
        self.rebuild_tree()
        self.sync_controls()
        self.apply_filter()
        self.set_status(f'Sessão recuperada: {len(existing)} arquivo(s).')

    def clear_session_data(self):
        if not self.ask(
            'Limpar sessão',
            'Apagar os dados locais da sessão e remover o lote atual da tela? Os arquivos originais não serão alterados.',
        ):
            return
        self.save_timer.stop()
        Batch.discard_session_file()
        inputs.cleanup_generated_files(self.batch.generated_files)
        self.batch.clear()
        self.batch.persistence_disabled = True
        self.preview_cache.clear()
        self.clear_preview()
        self.rebuild_tree()
        self.sync_controls()
        self.set_status('Dados locais da sessão e lote atual foram limpos. Os arquivos originais não foram alterados.')

    def prepare_close(self):
        """Chamado ao fechar o app. False se não pode fechar agora (análise em andamento)."""
        if self.analysis_running:
            if not self.close_warning_shown:
                self.close_warning_shown = True
                self.warn(
                    'Análise em andamento',
                    'Use Cancelar análise e aguarde a finalização segura antes de fechar o aplicativo.',
                )
                QTimer.singleShot(1500, lambda: setattr(self, 'close_warning_shown', False))
            return False
        self.select_timer.stop()
        if self.batch.files and not self.batch.persistence_disabled:
            self.save_timer.stop()
            self.save_now()
        if self.batch.persistence_disabled:
            inputs.cleanup_generated_files(self.batch.generated_files)
        self.preview_cache.clear()
        self.loader.wait(1500)
        return True

    # ---- saída da tela (usado pela janela principal) -------------------------------------
    def has_unsaved_work(self):
        """Há arquivos no lote que ainda não foram exportados (a exportação completa desliga a sessão)."""
        return bool(self.batch.files) and not self.batch.persistence_disabled

    def unsaved_text(self):
        total, ready, review, blocked = self.batch.counts()
        return (
            f'Há {total} arquivo(s) neste lote que ainda não foram exportados ({ready} pronto(s), {review} para '
            'revisar). Se sair agora sem exportar, a leitura e as correções feitas serão descartadas; os arquivos '
            'originais não são alterados.'
        )

    def save_work(self):
        """Exporta o lote (com as mesmas conferências e perguntas do botão Exportar)."""
        self.export()

    def cancel_for_exit(self):
        """Cancela a análise descartando o que ela leu desde que começou (o usuário está saindo da tela)."""
        if not self.analysis_running:
            return
        self.analysis_cancelled = self.analysis_discard = True
        self.discard_event.set()
        self.cancel_event.set()
        self.cancel_btn.setEnabled(False)

    def is_finished(self):
        try:
            return self._thread is None or not self._thread.isRunning()
        except RuntimeError:  # a thread já terminou e foi apagada
            return True

    def discard_work(self):
        """Zera a tela: apaga a sessão salva e os arquivos temporários (separados/convertidos)."""
        self.save_timer.stop()
        self.batch.persistence_disabled = True
        Batch.discard_session_file()
        self.prepare_close()

    # ---- prévia --------------------------------------------------------------------------
    def clear_preview(self):
        self.preview_request += 1
        self.preview_path = None
        self.preview_page = 0
        self.preview_total = 0
        self.preview.set_message('Selecione um arquivo para ver a página.')
        self.update_page_controls()

    def show_selected(self):
        selected = self.selected_paths()
        if not selected:
            return
        path = selected[0]
        if path != self.preview_path:
            self.preview_path = path
            self.preview_page = int(self.batch.analysis_pages.get(path, 0))
            self.preview_total = 0
        self.load_preview_page()

    def load_preview_page(self):
        path = self.preview_path
        if not path:
            return
        key = (path, int(self.preview_page))
        if key in self.preview_cache:
            image, total = self.preview_cache.pop(key)
            self.preview_cache[key] = (image, total)
            self.preview_total = total
            self.update_page_controls()
            self.preview.set_image(image)
            return
        self.preview_request += 1
        self.preview.set_message(f'Carregando página {self.preview_page + 1}...')
        self.loader.request(path, self.preview_page, self.preview_request)

    def on_preview_loaded(self, path, page_index, image, total, request):
        if request != self.preview_request or path != self.preview_path or page_index != self.preview_page:
            return
        self.preview_cache[(path, page_index)] = (image, total)
        while len(self.preview_cache) > PREVIEW_CACHE:
            self.preview_cache.popitem(last=False)
        self.preview_total = total
        self.update_page_controls()
        self.preview.set_image(image)

    def on_preview_failed(self, error, request):
        if request != self.preview_request:
            return
        self.preview.set_message(f'Prévia indisponível: {str(error)[:80]}', error=True)
        self.preview_total = 0
        self.update_page_controls()

    def change_page(self, step):
        if not self.preview_path or self.preview_total < 1:
            return
        target = max(0, min(self.preview_page + step, self.preview_total - 1))
        if target != self.preview_page:
            self.preview_page = target
            self.load_preview_page()

    def update_page_controls(self):
        total = self.preview_total
        self.page_label.setText(f'Página {self.preview_page + 1 if total else 0} de {total}')
        self.prev_page_btn.setEnabled(bool(total) and self.preview_page > 0)
        self.next_page_btn.setEnabled(bool(total) and self.preview_page < total - 1)

    # ---- densidade -----------------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        narrow, short = self.width() < NARROW_BELOW, self.height() < SHORT_BELOW
        if (narrow, short) == self.density:
            return
        self.density = (narrow, short)
        self.back_button.set_compact(narrow)
        self.tree.setColumnHidden(2, narrow)
        self.tree.setColumnHidden(3, narrow)
        self.order_hint.setVisible(not narrow)
        self.edit_btn.setText('Editar' if narrow else 'Editar dados')
        self.tree.setColumnWidth(0, 130 if narrow else 220)
        self.tip_label.setVisible(not short)
        self.select_files_btn.setText('Adicionar' if narrow else 'Adicionar arquivos')
        self.select_folder_btn.setText('Pasta' if narrow else 'Selecionar pasta')
        self.chapa_check.setText('Matrícula' if narrow else 'Matrícula/Chapa')
        self.mes_check.setText('Mês' if narrow else 'Mês da folha')
        self.prev_page_btn.setText('Anterior' if narrow else 'Página anterior')
        self.next_page_btn.setText('Próxima' if narrow else 'Próxima página')
        margins = self.shell_layout.contentsMargins()
        self.shell_layout.setContentsMargins(margins.left(), 10 if short else 22, margins.right(), margins.bottom())
        if narrow:
            total = max(self.splitter.width(), 1)
            self.splitter.setSizes([max(300, total - 330), 300])
