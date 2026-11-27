"""Tela padrão de uma ferramenta de PDF: arquivos à esquerda, opções e botão de ação à direita.

Tudo é montado a partir do catálogo (rdf.pdftools.registry): cada Tool descreve suas opções, e esta tela cria os
campos, valida, pergunta onde salvar e executa a operação em uma thread separada (a janela não trava).
"""

import re
import shutil
import threading
import uuid
import weakref
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rdf.core import config, settings
from rdf.core.fitz_lock import FITZ_LOCK
from rdf.pdftools import jobs, ops, sources
from rdf.qt.busy import Responsive
from rdf.qt.page_picker import PagePicker
from rdf.qt.thumbnails import ThumbnailLoader
from rdf.qt.widgets import BackButton, SmoothScrollArea, ToolTile

PREVIEW_SIZE = (230, 300)
OPTIONS_WIDTH = 380
OPTIONS_NARROW = 300
NARROW_BELOW = 960  # abaixo desta largura a prévia some e as opções ficam mais estreitas
PICKER_HINTS = {
    'remove': 'Clique nas páginas que serão removidas (Ctrl+A marca todas).',
    'extract': 'Clique nas páginas que vão para o novo PDF (Ctrl+A marca todas).',
}


def natural_key(path):
    """Ordem "humana" de nomes: "folha 2" vem antes de "folha 10"."""
    name = Path(path).name.casefold()
    return [int(part) if part.isdigit() else part for part in re.split(r'(\d+)', name)]


def last_folder():
    """A última pasta usada nas janelas de escolher arquivos (lembrada entre uma vez e outra que o app abre)."""
    folder = settings.current().get('last_folder')
    return folder if folder and Path(folder).is_dir() else ''


def remember_folder(path):
    settings.current().set('last_folder', str(Path(path).parent))


def make_card():
    card = QFrame()
    card.setObjectName('card')
    return card


def small_button(text):
    button = QPushButton(text)
    button.setProperty('size', 'small')
    return button


class _Worker(QObject):
    """Executa os trabalhos fora da thread da janela; só se comunica por sinais."""

    progress = Signal(float, str)
    finished = Signal(object)

    def __init__(self, tool, job_list, values, cancel_event, cache=None):
        super().__init__()
        self.tool, self.job_list, self.values, self.cancel_event = tool, job_list, values, cancel_event
        self.cache = cache

    def _tool_with_conversion(self):
        """A ferramenta, mas abrindo o PDF convertido de cada arquivo (convertendo agora o que ficou para depois).

        A operação roda sob a trava do PyMuPDF: ele não aceita duas threads ao mesmo tempo, e a prévia, as miniaturas
        e o renomeador também o usam em segundo plano."""

        def run(source, dest, values, progress):
            if self.cancel_event.is_set():
                raise jobs.Cancelled
            resolved = source if self.cache is None else self.cache.resolve(source, progress)
            with FITZ_LOCK:
                return self.tool.run(resolved, dest, values, progress)

        return SimpleNamespace(id=self.tool.id, run=run)

    def run(self):
        result = jobs.run_jobs(
            self._tool_with_conversion(),
            self.job_list,
            self.values,
            lambda f, t='': self.progress.emit(f, t),
            cancelled=self.cancel_event.is_set,
        )
        self.finished.emit(result)


class _OrderedTree(QTreeWidget):
    """Lista de arquivos que se reordena arrastando (Unir, Imagem para PDF). Arquivos vindos de fora (Explorer)
    continuam indo para a tela, que os adiciona."""

    reordered = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDropIndicatorShown(True)

    def dragEnterEvent(self, event):
        if event.source() is self:
            super().dragEnterEvent(event)
        else:
            event.ignore()  # arquivos do Explorer: quem trata é a tela

    def dragMoveEvent(self, event):
        if event.source() is self:
            super().dragMoveEvent(event)
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.source() is not self:
            event.ignore()
            return
        super().dropEvent(event)
        self.reordered.emit()


class ToolPage(QWidget):
    backRequested = Signal()
    save_label = None  # o trabalho já é salvo ao processar; só o renomeador oferece "Exportar agora"

    def __init__(self, tool, parent=None):
        super().__init__(parent)
        self.tool = tool
        self.files = []
        self.info = {}
        self.getters = {}
        self.widgets = {}
        self.option_frames = {}
        self.running = False
        self.dirty = False  # há arquivos escolhidos que ainda não foram processados
        self.cancel_event = threading.Event()
        self.narrow = False
        self.output_file = None
        self.output_folder = None
        self.kind_label = 'imagens' if tool.inputs == 'image' else ('arquivos' if tool.any_format else 'PDFs')
        folder = config.CONVERT_DIR / 'ferramentas' / uuid.uuid4().hex[:8]
        self.cache = sources.SourceCache(folder)  # conversões para PDF dos arquivos que não são PDF
        weakref.finalize(self, shutil.rmtree, str(folder), True)  # some junto com a tela, ou ao fechar o app
        self.reject_reasons = {}
        self._thread = None
        self._worker = None
        self._picker_source = None
        self._syncing_pages = False
        self.picker = None
        self.preview_path = None
        self.preview_loader = ThumbnailLoader(self)
        self.preview_loader.ready.connect(self._on_preview_image)
        self.preview_loader.failed.connect(lambda *_args: self.preview.setText('Sem prévia'))
        self.setAcceptDrops(True)
        for sequence, handler in (
            ('Ctrl+O', self.add_dialog),
            ('Ctrl+Return', self.run),
            ('Delete', self.remove_selected),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self, activated=handler)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(36, 22, 36, 26)
        layout.setSpacing(18)
        self.files_card = self._build_files_card()
        self.options_card = self._build_options_card()
        layout.addWidget(self.files_card, 1)
        layout.addWidget(self.options_card, 0)
        self._connect_picker()
        self.refresh_files()

    # ---- montagem ------------------------------------------------------------------------
    def _build_files_card(self):
        card = make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        self.back_button = BackButton()
        self.back_button.clicked.connect(self.backRequested)
        layout.addWidget(self.back_button, 0, Qt.AlignLeft)
        self.files_stack = QStackedWidget()
        layout.addWidget(self.files_stack)
        self.files_stack.addWidget(self._build_empty())
        self.files_stack.addWidget(self._build_listing())
        return card

    def _build_empty(self):
        tool = self.tool
        self.dropzone = QFrame()
        self.dropzone.setObjectName('dropzone')
        layout = QVBoxLayout(self.dropzone)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(6)
        layout.addStretch(1)
        layout.addWidget(ToolTile(tool, 72), 0, Qt.AlignHCenter)
        layout.addSpacing(8)
        title = QLabel(tool.title)
        title.setObjectName('pageTitle')
        lead = QLabel(tool.description)
        lead.setObjectName('pageLead')
        lead.setWordWrap(True)
        lead.setAlignment(Qt.AlignCenter)
        lead.setMaximumWidth(420)
        layout.addWidget(title, 0, Qt.AlignHCenter)
        layout.addWidget(lead, 0, Qt.AlignHCenter)
        layout.addSpacing(18)
        drop = QLabel(f'Arraste {self.kind_label} aqui')
        drop.setObjectName('cardTitle')
        layout.addWidget(drop, 0, Qt.AlignHCenter)
        or_label = QLabel('ou')
        or_label.setObjectName('hint')
        layout.addWidget(or_label, 0, Qt.AlignHCenter)
        singular = self.kind_label if tool.multiple else self.kind_label[:-1]
        self.pick_button = QPushButton(f'Selecionar {singular}')
        self.pick_button.setProperty('variant', 'primary')
        self.pick_button.setMinimumWidth(190)
        self.pick_button.setToolTip('Atalho: Ctrl+O')
        self.pick_button.clicked.connect(self.add_dialog)
        layout.addWidget(self.pick_button, 0, Qt.AlignHCenter)
        hint = QLabel(
            'Você pode escolher vários arquivos de uma vez.'
            if tool.multiple
            else 'Esta ferramenta trabalha com um arquivo por vez.'
        )
        if tool.any_format and tool.inputs == 'pdf':
            hint.setText(hint.text() + '\nAceita PDF, imagens, textos, HTML e documentos do Word, Excel e PowerPoint.')
            hint.setWordWrap(True)
            hint.setAlignment(Qt.AlignCenter)
            hint.setMaximumWidth(420)
        hint.setObjectName('hint')
        layout.addWidget(hint, 0, Qt.AlignHCenter)
        layout.addStretch(1)
        return self.dropzone

    def _build_listing(self):
        tool = self.tool
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.counter = QLabel('')
        self.counter.setObjectName('cardTitle')
        self.bar_buttons = QWidget()
        buttons = QHBoxLayout(self.bar_buttons)
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(8)
        self.add_button = small_button('')
        self.add_button.setToolTip('Atalho: Ctrl+O')
        self.add_button.clicked.connect(self.add_dialog)
        buttons.addWidget(self.add_button)
        if tool.mode == 'combine' or tool.ordered:
            self.up_button, self.down_button = small_button('↑'), small_button('↓')
            self.up_button.setAccessibleName('Mover para cima')
            self.down_button.setAccessibleName('Mover para baixo')
            self.up_button.setToolTip('Mover para cima')
            self.down_button.setToolTip('Mover para baixo')
            self.up_button.clicked.connect(lambda: self.move(-1))
            self.down_button.clicked.connect(lambda: self.move(1))
            buttons.addWidget(self.up_button)
            buttons.addWidget(self.down_button)
            self.sort_button = small_button('A→Z')
            self.sort_button.setToolTip('Ordenar por nome ("folha 2" antes de "folha 10")')
            self.sort_button.setAccessibleName('Ordenar por nome')
            self.sort_button.clicked.connect(self.sort_by_name)
            buttons.addWidget(self.sort_button)
        self.remove_button = small_button('Remover')
        self.remove_button.setToolTip('Atalho: Delete')
        self.remove_button.clicked.connect(self.remove_selected)
        self.clear_button = small_button('')
        self.clear_button.clicked.connect(self.clear_files)
        buttons.addWidget(self.remove_button)
        buttons.addWidget(self.clear_button)
        self.bar = QGridLayout()
        self.bar.setHorizontalSpacing(8)
        self.bar.setVerticalSpacing(8)
        self.bar.setColumnStretch(0, 1)
        layout.addLayout(self.bar)
        self.arrange_bar(narrow=False)

        body = QHBoxLayout()
        body.setSpacing(14)
        self.reorderable = tool.mode == 'combine' or tool.ordered
        self.tree = _OrderedTree() if self.reorderable else QTreeWidget()
        if self.reorderable:
            self.tree.reordered.connect(self.sync_order_from_tree)
            self.tree.setToolTip('Arraste os arquivos para mudar a ordem')
        self.show_kind = tool.any_format and tool.inputs == 'pdf'  # a lista mostra o tipo: PDF, Imagem, Word...
        labels = ['Arquivo'] + (['Tipo'] if self.show_kind else [])
        labels += ['Dimensões' if tool.inputs == 'image' else 'Páginas', 'Tamanho']
        self.tree.setColumnCount(len(labels))
        self.tree.setHeaderLabels(labels)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.tree.setSortingEnabled(False)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, header.ResizeMode.Stretch)
        for column in range(1, len(labels)):
            header.setSectionResizeMode(column, header.ResizeMode.ResizeToContents)
        self.tree.setAccessibleName('Arquivos escolhidos')
        self.tree.itemSelectionChanged.connect(self.on_select)
        if tool.page_picker:
            # Uma página por miniatura ocupa o lugar da prévia: a lista do arquivo fica baixa, as páginas embaixo.
            column = QVBoxLayout()
            column.setSpacing(10)
            self.tree.setMaximumHeight(84)
            column.addWidget(self.tree)
            self.picker = PagePicker(
                tool.page_picker[0], PICKER_HINTS.get(tool.id, ''), marks_removal=tool.id == 'remove'
            )
            column.addWidget(self.picker, 1)
            body.addLayout(column, 1)
        else:
            body.addWidget(self.tree, 1)

        self.preview_side = QWidget()
        side = QVBoxLayout(self.preview_side)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(8)
        self.preview = QLabel()
        self.preview.setFixedSize(*PREVIEW_SIZE)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setObjectName('previewBox')
        self.preview_caption = QLabel('')
        self.preview_caption.setObjectName('hint')
        self.preview_caption.setAlignment(Qt.AlignCenter)
        self.preview_caption.setWordWrap(True)
        self.preview_caption.setMaximumWidth(PREVIEW_SIZE[0])
        side.addWidget(self.preview)
        side.addWidget(self.preview_caption)
        side.addStretch(1)
        body.addWidget(self.preview_side, 0, Qt.AlignTop)
        if self.picker is not None:
            self.preview_side.hide()  # as miniaturas já mostram as páginas
        layout.addLayout(body, 1)
        return page

    def arrange_bar(self, narrow):
        """Largo: contador à esquerda e botões à direita, na mesma linha. Estreito: contador em cima e botões
        embaixo, com textos curtos (senão os botões ficam cortados)."""
        self.bar.removeWidget(self.counter)
        self.bar.removeWidget(self.bar_buttons)
        if narrow:
            self.bar.addWidget(self.counter, 0, 0, 1, 2)
            self.bar.addWidget(self.bar_buttons, 1, 0, 1, 2, Qt.AlignRight)
        else:
            self.bar.addWidget(self.counter, 0, 0)
            self.bar.addWidget(self.bar_buttons, 0, 1, Qt.AlignRight)
        multiple = self.tool.multiple
        self.add_button.setText(
            ('Adicionar' if narrow else 'Adicionar mais') if multiple else ('Trocar' if narrow else 'Trocar arquivo')
        )
        self.clear_button.setText('Limpar' if narrow else 'Limpar tudo')
        for button in self.bar_buttons.findChildren(QPushButton):
            button.setMinimumWidth(button.sizeHint().width())  # nunca menor que o próprio texto

    def _build_options_card(self):
        tool = self.tool
        card = make_card()
        card.setFixedWidth(OPTIONS_WIDTH)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        title = QLabel('Opções')
        title.setObjectName('cardTitle')
        layout.addWidget(title)

        scroll = SmoothScrollArea()
        content = QWidget()
        content.setObjectName('optionsContent')
        form = QVBoxLayout(content)
        form.setContentsMargins(0, 0, 8, 0)
        form.setSpacing(14)
        for widget in self.build_extra_options():
            form.addWidget(widget)
        if not tool.options:
            note = QLabel(f'Nenhum ajuste necessário. Adicione {self.kind_label} e clique em "{tool.action}".')
            note.setObjectName('pageLead')
            note.setWordWrap(True)
            form.addWidget(note)
        for option in tool.options:
            frame, getter, signal = self._build_option(option)
            form.addWidget(frame)
            self.getters[option.key] = getter
            self.option_frames[option.key] = (frame, option)
            signal.connect(lambda *_: self.update_visibility())
        form.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.update_visibility()

        self.run_button = QPushButton(tool.action)
        self.run_button.setProperty('variant', 'primary')
        self.run_button.setMinimumHeight(46)
        self.run_button.setToolTip('Atalho: Ctrl+Enter')
        self.run_button.clicked.connect(self.on_run_clicked)
        layout.addWidget(self.run_button)
        for extra in self.build_action_extras():
            layout.addWidget(extra)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.message = QLabel('')
        self.message.setWordWrap(True)
        self.message.setProperty('tone', 'info')
        layout.addWidget(self.message)
        self.open_folder_button = QPushButton('Abrir pasta')
        self.open_folder_button.clicked.connect(lambda: self.open_path(self.output_folder))
        self.open_file_button = QPushButton('Abrir arquivo')
        self.open_file_button.setProperty('variant', 'success')
        self.open_file_button.clicked.connect(lambda: self.open_path(self.output_file))
        self.again_button = QPushButton('Começar de novo')
        self.again_button.setProperty('variant', 'quiet')
        self.again_button.setToolTip('Limpa a lista para processar outros arquivos')
        self.again_button.clicked.connect(self.start_over)
        result_row = QHBoxLayout()
        result_row.setSpacing(8)
        for button in (self.open_file_button, self.open_folder_button):
            button.hide()
            result_row.addWidget(button, 1)
        layout.addLayout(result_row)
        self.again_button.hide()
        layout.addWidget(self.again_button)
        return card

    def build_action_extras(self):
        """Botões que uma tela própria põe logo abaixo do botão de ação (a padrão não tem nenhum)."""
        return []

    def build_extra_options(self):
        """Campos que só uma tela própria precisa, no topo das opções (a padrão não tem nenhum)."""
        return []

    def _build_option(self, option):
        frame = QWidget()
        column = QVBoxLayout(frame)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(5)
        if option.kind == 'bool':
            widget = QCheckBox(option.label)
            widget.setChecked(bool(option.default))
            getter, signal = widget.isChecked, widget.toggled
            column.addWidget(widget)
        else:
            label = QLabel(option.label)
            label.setObjectName('fieldLabel')
            column.addWidget(label)
            default = '' if option.default is None else option.default
            if option.kind == 'choice':
                widget = QComboBox()
                widget.addItems(list(option.choices))
                widget.setCurrentText(str(default))
                getter, signal = widget.currentText, widget.currentTextChanged
            elif option.kind == 'int':
                widget = QSpinBox()
                widget.setRange(0, 100000)
                widget.setValue(int(default or 0))
                getter, signal = widget.value, widget.valueChanged
            else:
                widget = QLineEdit(str(default))
                if option.kind == 'password':
                    widget.setEchoMode(QLineEdit.Password)
                getter, signal = widget.text, widget.textChanged
            column.addWidget(widget)
        if option.kind != 'bool':
            label.setBuddy(widget)  # o leitor de tela lê o rótulo ao entrar no campo; Alt+letra não é usado
            widget.setAccessibleName(option.label)
        self.widgets[option.key] = widget  # telas próprias podem precisar mudar os campos por código
        if option.help:
            hint = QLabel(option.help)
            hint.setObjectName('hint')
            hint.setWordWrap(True)
            column.addWidget(hint)
        return frame, getter, signal

    def update_visibility(self):
        current = {key: getter() for key, getter in self.getters.items()}
        for frame, option in self.option_frames.values():
            frame.setVisible(jobs.option_visible(option, current))
        if self.picker is not None and self.tool.page_picker[1] in self.option_frames:
            _frame, option = self.option_frames[self.tool.page_picker[1]]
            self.picker.setVisible(jobs.option_visible(option, current))

    # ---- miniaturas das páginas ----------------------------------------------------------
    def _connect_picker(self):
        """Liga as miniaturas ao campo de páginas: um muda o outro, sem um ficar devolvendo para o outro."""
        if self.picker is None:
            return
        field = self.widgets.get(self.tool.page_picker[1])
        if field is None:
            return
        self.picker.changed.connect(self._on_picker_changed)
        field.textChanged.connect(self._on_page_field_changed)

    def _on_picker_changed(self, text):
        field = self.widgets[self.tool.page_picker[1]]
        self._syncing_pages = True
        try:
            field.setText(text)
        finally:
            self._syncing_pages = False

    def _on_page_field_changed(self, text):
        if not self._syncing_pages:
            self.picker.set_from_text(text)

    def refresh_picker(self):
        if self.picker is None:
            return
        if not self.files:
            self._picker_source = None
            self.picker.clear()
            return
        path = self.files[0]
        pdf = self.cache.pdf_for(path)
        details = self.info.get(path, {})
        if (path, pdf) == self._picker_source:
            return
        self._picker_source = (path, pdf)
        if details.get('locked'):
            self.picker.clear('PDF protegido por senha: use "Desbloquear PDF" antes.')
        elif pdf is None or not details.get('pages'):
            self.picker.clear('As miniaturas aparecem depois de processar (documento do Office).')
        else:
            self.picker.load(pdf, details['pages'])
            self.picker.set_from_text(self.widgets[self.tool.page_picker[1]].text())

    # ---- arquivos ------------------------------------------------------------------------
    @property
    def allowed_extensions(self):
        if self.tool.inputs == 'image':
            return ops.IMAGE_EXTENSIONS
        return sources.ALL_EXTENSIONS if self.tool.any_format else {'.pdf'}

    @property
    def accepted_text(self):
        if self.tool.any_format and self.tool.inputs == 'pdf':
            return 'PDF, imagens, textos, HTML e documentos do Word, Excel e PowerPoint'
        return self.kind_label

    def add_dialog(self):
        if self.running:
            return
        if self.tool.inputs == 'image':
            pattern = 'Imagens (*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp *.gif);;Todos os arquivos (*.*)'
        elif self.tool.any_format:
            pattern = sources.file_dialog_filters()
        else:
            pattern = 'Arquivos PDF (*.pdf);;Todos os arquivos (*.*)'
        title = 'Escolha os arquivos' if self.tool.multiple else 'Escolha o arquivo'
        chosen, _filter = QFileDialog.getOpenFileNames(self, title, last_folder(), pattern)
        if chosen:
            remember_folder(chosen[0])
            self.add_paths(chosen)

    def add_paths(self, paths):
        candidates = []
        for raw in paths:
            path = Path(raw)
            if path.is_dir():
                candidates.extend(sorted(p for p in path.iterdir() if p.is_file()))
            else:
                candidates.append(path)
        candidates = [p for p in candidates if p.suffix.lower() in self.allowed_extensions]
        if not candidates:
            self.set_message(f'Nenhum arquivo compatível. Esta ferramenta aceita {self.accepted_text}.', 'error')
            return
        notes = []
        replaced = []
        if not self.tool.multiple:
            if len(candidates) > 1:
                notes.append('Esta ferramenta trabalha com um arquivo por vez; usei o primeiro.')
            candidates = candidates[:1]
            replaced = list(self.files)
        rejected, added = [], []
        known = {str(Path(f).resolve()) for f in self.files}
        responsive = Responsive()
        for position, path in enumerate(candidates, start=1):
            if len(candidates) > 1:
                self.set_message(f'Adicionando {position} de {len(candidates)}: {path.name}', 'info')
                responsive.pulse()
            key = str(path.resolve())
            if key in known and not replaced:
                continue
            try:
                details = self.inspect_source(path)
            except ops.PdfToolError as exc:
                rejected.append((path.name, str(exc)))
                continue
            known.add(key)
            self.info[str(path)] = details
            added.append(str(path))
        if added and replaced:
            self.files = []
            for old in replaced:
                self.info.pop(old, None)
            self.cache.forget(replaced)
        self.files.extend(added)
        if added:
            self.dirty = True
        self.refresh_files()
        notes.extend(self.rejection_notes(rejected))
        if notes:
            self.set_message(' '.join(notes), 'error' if rejected else 'info')
        elif added:
            self.set_message('', 'info')

    INVALID_FILE = 'arquivo inválido ou corrompido'

    def inspect_source(self, path):
        """Detalhes do arquivo para a lista. Converte já o que é rápido (imagem, texto, HTML); documentos do Office
        ficam para a hora de executar. Levanta ops.PdfToolError, com a mensagem pronta, se não dá para usar."""
        too_big = sources.size_error(path)
        if too_big:
            raise ops.PdfToolError(too_big)
        if self.tool.inputs == 'image' or not self.cache.is_other_format(path):
            details = jobs.inspect_file(self.tool, path)
            if details is None:
                raise ops.PdfToolError(self.INVALID_FILE)
            return {**details, 'kind': 'Imagem' if self.tool.inputs == 'image' else 'PDF'}
        try:
            size = Path(path).stat().st_size
        except OSError as exc:
            raise ops.PdfToolError(f'Não foi possível ler "{Path(path).name}": o arquivo não existe mais.') from exc
        kind = sources.kind_label(path)
        if sources.is_slow(path):
            if not sources.office_available(path):
                raise sources.office_error(path)
            return {'detail': 'ao processar', 'size': size, 'pages': 0, 'locked': False, 'kind': kind}
        details = jobs.inspect_file(self.tool, self.cache.prepare(path))
        if details is None:
            raise ops.PdfToolError(self.INVALID_FILE)
        return {**details, 'size': size, 'kind': kind}

    def rejection_notes(self, rejected):
        """Avisos sobre os arquivos ignorados: os inválidos juntos, e cada motivo específico à parte."""
        invalid = [name for name, reason in rejected if reason == self.INVALID_FILE]
        notes = []
        if invalid:
            notes.append(
                f'Ignorado ({self.INVALID_FILE}): {", ".join(invalid[:3])}' + ('…' if len(invalid) > 3 else '')
            )
        notes.extend(reason for _name, reason in rejected if reason != self.INVALID_FILE)
        return notes[:3]

    def refresh_files(self):
        self.tree.clear()
        for path in self.files:
            details = self.info[path]
            columns = [Path(path).name]
            if self.show_kind:
                columns.append(details.get('kind', ''))
            columns += [details['detail'], ops.human_size(details['size'])]
            item = QTreeWidgetItem(columns)
            item.setData(0, Qt.UserRole, path)
            if self.reorderable:  # arrasta, mas não solta "dentro" de outro arquivo
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
            pages_column = 2 if self.show_kind else 1
            item.setTextAlignment(pages_column, Qt.AlignCenter)
            item.setTextAlignment(pages_column + 1, Qt.AlignRight | Qt.AlignVCenter)
            self.tree.addTopLevelItem(item)
        if self.files:
            total_pages = sum(self.info[p]['pages'] for p in self.files)
            noun = 'arquivo' if len(self.files) == 1 else 'arquivos'
            extra = ''
            if self.tool.inputs == 'pdf' and total_pages:
                extra = f'  ·  {total_pages} {"página" if total_pages == 1 else "páginas"}'
            self.counter.setText(f'{len(self.files)} {noun}{extra}')
            self.files_stack.setCurrentIndex(1)
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        else:
            self.files_stack.setCurrentIndex(0)
            self.clear_preview()
        self.refresh_picker()

    def selected_paths(self):
        return [item.data(0, Qt.UserRole) for item in self.tree.selectedItems()]

    def on_select(self):
        selected = self.selected_paths()
        if selected and self.picker is None:
            self.show_preview(selected[0])

    def clear_preview(self):
        self.preview_loader.cancel()
        self.preview_path = None
        self.preview.clear()
        self.preview_caption.setText('')

    def show_preview(self, path):
        """A primeira página do arquivo, desenhada em segundo plano (a janela não espera o PDF abrir)."""
        self.preview_loader.cancel()
        self.preview.clear()
        self.preview_path = None
        details = self.info.get(path)
        if details is None:
            return
        self.preview_caption.setText(Path(path).name)
        if details['locked']:
            self.preview.setText('PDF protegido\npor senha')
            return
        if self.tool.inputs == 'image':
            pixmap = QPixmap(path)
            if pixmap.isNull():
                self.preview.setText('Sem prévia')
            else:
                self.preview.setPixmap(pixmap.scaled(*PREVIEW_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            return
        pdf = self.cache.pdf_for(path)
        if pdf is None:
            self.preview.setText('Prévia disponível\ndepois de processar')  # documento do Office
            return
        self.preview.setText('Carregando…')
        self.preview_path = str(pdf)
        self.preview_loader.request(pdf, [0], PREVIEW_SIZE[0] * 2, PREVIEW_SIZE[1] * 2)

    def _on_preview_image(self, path, _index, image):
        if path != self.preview_path:
            return
        pixmap = QPixmap.fromImage(image)
        self.preview.setPixmap(pixmap.scaled(*PREVIEW_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def remove_selected(self):
        if self.running:
            return
        selected = set(self.selected_paths())
        if not selected:
            return
        self.files = [p for p in self.files if p not in selected]
        for path in selected:
            self.info.pop(path, None)
        self.cache.forget(selected)
        self.dirty = bool(self.files)
        self.refresh_files()

    def clear_files(self):
        if self.running:
            return
        self.files, self.info = [], {}
        self.cache.clear()
        self.dirty = False
        self.refresh_files()
        self.set_message('', 'info')

    def move(self, step):
        selected = self.selected_paths()
        if not selected or self.running:
            return
        order = list(self.files)
        indexes = sorted(order.index(p) for p in selected)
        if (step < 0 and indexes[0] == 0) or (step > 0 and indexes[-1] == len(order) - 1):
            return
        for index in indexes if step < 0 else reversed(indexes):
            order[index], order[index + step] = order[index + step], order[index]
        self.files = order
        self.refresh_files()
        self.reselect(selected)

    def reselect(self, paths):
        chosen = set(paths)
        for position, path in enumerate(self.files):
            self.tree.topLevelItem(position).setSelected(path in chosen)

    def sort_by_name(self):
        """Põe a lista em ordem de nome, do jeito que uma pessoa ordenaria (números pelo valor)."""
        if self.running or len(self.files) < 2:
            return
        selected = self.selected_paths()
        self.files = sorted(self.files, key=natural_key)
        self.refresh_files()
        self.reselect(selected)

    def sync_order_from_tree(self):
        """Depois de arrastar: a ordem da lista na tela passa a ser a ordem dos arquivos."""
        order = [self.tree.topLevelItem(row).data(0, Qt.UserRole) for row in range(self.tree.topLevelItemCount())]
        if sorted(order) != sorted(self.files) or self.running:
            self.refresh_files()  # algo inesperado (item aninhado, tarefa rodando): volta ao estado conhecido
            return
        selected = self.selected_paths()
        self.files = order
        self.refresh_files()
        self.reselect(selected)

    # ---- arrastar e soltar ---------------------------------------------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self.running:
            event.acceptProposedAction()
            self._set_dragging(True)

    def dragLeaveEvent(self, event):
        self._set_dragging(False)

    def dropEvent(self, event):
        self._set_dragging(False)
        if not self.running:
            self.add_paths([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])
            event.acceptProposedAction()

    def _set_dragging(self, value):
        self.dropzone.setProperty('dragging', value)
        self.dropzone.style().unpolish(self.dropzone)
        self.dropzone.style().polish(self.dropzone)

    # ---- mensagens -----------------------------------------------------------------------
    def set_message(self, text, tone='info'):
        self.message.setText(text)
        self.message.setProperty('tone', tone)
        self.message.style().unpolish(self.message)
        self.message.style().polish(self.message)

    # ---- execução ------------------------------------------------------------------------
    def ask_destination(self):
        """Pergunta onde salvar. Devolve a lista de trabalhos [(origem, destino)] ou None se o usuário desistiu."""
        first = Path(self.files[0])
        if jobs.destination_kind(self.tool, self.files) == 'save-as':
            suggestion = str(first.parent / jobs.suggested_name(self.tool, first))
            ext = self.tool.output_ext
            kind = 'Arquivo de texto' if ext == 'txt' else f'Arquivo {ext.upper()}'
            target, _filter = QFileDialog.getSaveFileName(self, 'Salvar como', suggestion, f'{kind} (*.{ext})')
            if not target:
                return None
            if not target.lower().endswith(f'.{ext}'):
                target += f'.{ext}'
            return jobs.jobs_for_save_as(self.tool, self.files, target)
        folder = QFileDialog.getExistingDirectory(self, 'Escolha a pasta onde salvar', str(first.parent))
        if not folder:
            return None
        return jobs.jobs_for_folder(self.tool, self.files, folder)

    def run(self):
        if self.running:
            return
        need = max(1, self.tool.min_files)
        if len(self.files) < need:
            self.set_message(f'Adicione pelo menos {need} arquivo{"s" if need > 1 else ""} para continuar.', 'error')
            return
        try:
            values = jobs.collect_values(self.tool.options, {key: get() for key, get in self.getters.items()})
        except ops.PdfToolError as exc:
            self.set_message(str(exc), 'error')
            return
        values = self.extra_values(values)
        job_list = self.ask_destination()
        if not job_list:
            return
        self.start_worker(job_list, values)

    def extra_values(self, values):
        """Valores que uma tela própria acrescenta aos das opções antes de executar (a padrão não muda nada)."""
        return values

    def on_run_clicked(self):
        if self.running:
            self.request_cancel(ask=True)
        else:
            self.run()

    def request_cancel(self, ask=False):
        """Pede para parar a tarefa em andamento. Com ask, confirma antes. True se o cancelamento foi pedido."""
        if not self.running:
            return False
        if ask and not self.confirm_cancel():
            return False
        self.cancel_event.set()
        self.run_button.setEnabled(False)
        self.run_button.setText('Cancelando…')
        self.set_message('Cancelando a tarefa…', 'info')
        return True

    def confirm_cancel(self):
        answer = QMessageBox.question(
            self,
            'Cancelar a tarefa',
            'A tarefa está em andamento. Deseja cancelá-la? Nenhum arquivo incompleto será mantido.',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    def start_worker(self, job_list, values):
        self.running = True
        self.cancel_event.clear()
        for button in (self.open_folder_button, self.open_file_button, self.again_button):
            button.hide()
        self.run_button.setText('Cancelar tarefa')
        self.progress.setValue(0)
        self.progress.show()
        self.set_message('Processando…', 'info')
        self._thread = QThread(self)
        self._worker = _Worker(self.tool, job_list, values, self.cancel_event, self.cache)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.on_progress)
        self._worker.finished.connect(self.on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def on_progress(self, fraction, text):
        self.progress.setValue(int(fraction * 100))
        if text:
            self.set_message(text, 'info')

    def on_finished(self, result):
        self.running = False
        self.run_button.setEnabled(True)
        self.run_button.setText(self.tool.action)
        self.progress.hide()
        if self.cancel_event.is_set():
            self.finish_cancelled(result)
            return
        self.show_result(result)

    def show_result(self, result):
        summary = jobs.summarize(*result)
        if not summary.ok:
            self.set_message(summary.text, 'error')
            return
        self.dirty = False
        self.output_file, self.output_folder = summary.output_file, summary.output_folder
        self.set_message('✓  ' + summary.text, 'ok')
        self.open_folder_button.show()
        self.open_file_button.setVisible(self.output_file is not None)
        self.again_button.show()
        if settings.current().get('open_folder_after'):
            self.open_path(self.output_folder)

    def start_over(self):
        """Depois de terminar: limpa a lista para processar outros arquivos (as opções ficam como estão)."""
        self.clear_files()
        for button in (self.open_folder_button, self.open_file_button, self.again_button):
            button.hide()

    def finish_cancelled(self, result):
        kept = len(result[0])
        text = 'Tarefa cancelada. Nenhum arquivo incompleto foi deixado.'
        if kept:
            text += f'\n{kept} arquivo(s) já concluído(s) foram mantidos.'
        self.set_message(text, 'info')

    # ---- saída da tela (usado pela janela principal) -------------------------------------
    def has_unsaved_work(self):
        return bool(self.files) and self.dirty

    def unsaved_text(self):
        return (
            f'Você escolheu arquivos, mas ainda não usou "{self.tool.action}". '
            'Se sair agora, a seleção será descartada.'
        )

    def is_finished(self):
        try:
            return self._thread is None or not self._thread.isRunning()
        except RuntimeError:  # a thread já terminou e foi apagada
            return True

    def cancel_for_exit(self):
        self.request_cancel()

    def discard_work(self):
        """Descarta a seleção em tela e as conversões temporárias; o que foi gerado já está onde o usuário pediu."""
        self.preview_loader.cancel()
        if self.picker is not None:
            self.picker.loader.cancel()
        self.cache.clear()

    @staticmethod
    def open_path(path):
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ---- densidade -----------------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        narrow = self.width() < NARROW_BELOW
        if narrow != self.narrow:
            self.narrow = narrow
            self.back_button.set_compact(narrow)
            self.preview_side.setVisible(not narrow)
            self.arrange_bar(narrow)
            self.options_card.setFixedWidth(OPTIONS_NARROW if narrow else OPTIONS_WIDTH)
