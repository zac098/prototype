"""Escolha de páginas por miniaturas, ligada ao campo de texto da ferramenta ("1-3, 5, 8-").

Dois jeitos de usar:
- "select" (Remover e Extrair páginas): clicar numa miniatura marca ou desmarca a página; o campo de páginas é
  preenchido sozinho. Digitar no campo também marca as miniaturas.
- "order" (Organizar páginas): arrastar as miniaturas (ou usar os botões ← →) muda a ordem; Delete tira a página.
  O campo recebe a nova ordem ("3, 1-2, 4-6").

As miniaturas são desenhadas em segundo plano (rdf.qt.thumbnails), com o número da página por cima.
"""

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rdf.pdftools.pages import PageRangeError, format_page_ranges, parse_page_ranges
from rdf.qt.theme import COLORS, FONT_FAMILY
from rdf.qt.thumbnails import ThumbnailLoader

THUMB = QSize(104, 140)  # cabe uma página A4 em pé; deitada fica mais baixa, centrada
CELL = QSize(124, 164)
MAX_PAGES = 2000  # acima disso a grade fica pesada demais: o campo de texto continua valendo
PAGE_ROLE = Qt.UserRole


def _badge(image, number, removed=False):
    """A miniatura num quadro do tamanho certo, com o número da página num selo embaixo."""
    canvas = QPixmap(THUMB.width(), THUMB.height())
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    if image is not None and not image.isNull():
        scaled = image.scaled(THUMB.width() - 4, THUMB.height() - 4, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x = (THUMB.width() - scaled.width()) / 2
        y = (THUMB.height() - scaled.height()) / 2
        painter.setPen(QPen(QColor(COLORS['line_strong']), 1))
        painter.drawRect(QRectF(x - 0.5, y - 0.5, scaled.width() + 1, scaled.height() + 1))
        painter.drawImage(int(x), int(y), scaled)
    else:  # ainda desenhando
        painter.setPen(QPen(QColor(COLORS['line_strong']), 1, Qt.DashLine))
        painter.setBrush(QColor(COLORS['surface']))
        painter.drawRoundedRect(QRectF(8, 4, THUMB.width() - 16, THUMB.height() - 8), 4, 4)
    label = str(number)
    font = QFont(FONT_FAMILY)
    font.setBold(True)
    font.setPixelSize(12)
    painter.setFont(font)
    width = painter.fontMetrics().horizontalAdvance(label) + 14
    pill = QRectF((THUMB.width() - width) / 2, THUMB.height() - 24, width, 20)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(COLORS['danger'] if removed else COLORS['ink']))
    painter.drawRoundedRect(pill, 10, 10)
    painter.setPen(QColor(COLORS['surface']))
    painter.drawText(pill, Qt.AlignCenter, label)
    painter.end()
    return canvas


class _Grid(QListWidget):
    """Grade de miniaturas que se reordena arrastando (em modo lista, com quebra: arrastar troca a ordem)."""

    reordered = Signal()

    def dropEvent(self, event):
        super().dropEvent(event)
        self.reordered.emit()


class PagePicker(QWidget):
    """Miniaturas das páginas de um PDF. changed(texto) leva a escolha para o campo da ferramenta."""

    changed = Signal(str)

    def __init__(self, mode='select', hint='', parent=None, marks_removal=False):
        super().__init__(parent)
        self.mode = mode
        self.marks_removal = marks_removal  # Remover páginas: as escolhidas ganham o selo vermelho
        self._marked = set()
        self.path = None
        self.total = 0
        self.images = {}  # página -> QImage já desenhada
        self._syncing = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(6)
        self.caption = QLabel(hint or self._default_hint())
        self.caption.setObjectName('hint')
        self.caption.setWordWrap(True)
        head.addWidget(self.caption, 1)
        self.buttons = {}
        if mode == 'select':
            entries = (('all', 'Todas'), ('none', 'Nenhuma'), ('odd', 'Ímpares'), ('even', 'Pares'))
        else:
            entries = (('left', '←'), ('right', '→'), ('reverse', 'Inverter'), ('reset', 'Restaurar'))
        for key, text in entries:
            button = QPushButton(text)
            button.setProperty('size', 'small')
            button.clicked.connect(lambda _checked=False, value=key: self.act(value))
            head.addWidget(button)
            self.buttons[key] = button
        if mode == 'order':
            self.buttons['left'].setAccessibleName('Mover as páginas escolhidas para trás')
            self.buttons['right'].setAccessibleName('Mover as páginas escolhidas para a frente')
            self.buttons['left'].setToolTip('Mover para trás')
            self.buttons['right'].setToolTip('Mover para a frente')
        layout.addLayout(head)

        self.grid = _Grid()
        self.grid.setObjectName('thumbs')
        self.grid.setAccessibleName('Miniaturas das páginas')
        self.grid.setViewMode(QListView.ListMode)
        self.grid.setFlow(QListView.LeftToRight)
        self.grid.setWrapping(True)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setIconSize(THUMB)
        self.grid.setGridSize(CELL)
        self.grid.setUniformItemSizes(True)
        self.grid.setSpacing(4)
        if mode == 'select':
            self.grid.setSelectionMode(QAbstractItemView.MultiSelection)
            self.grid.setMovement(QListView.Static)
        else:
            self.grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
            self.grid.setDragDropMode(QAbstractItemView.InternalMove)
            self.grid.setDefaultDropAction(Qt.MoveAction)
            self.grid.setMovement(QListView.Snap)
            self.grid.reordered.connect(self._emit)
            shortcut = QShortcut(QKeySequence(Qt.Key_Delete), self.grid, activated=self.remove_selected)
            shortcut.setContext(Qt.WidgetShortcut)
        select_all = QShortcut(QKeySequence.SelectAll, self.grid, activated=lambda: self.act('all'))
        select_all.setContext(Qt.WidgetShortcut)
        self.grid.itemSelectionChanged.connect(self._on_selection)
        layout.addWidget(self.grid, 1)
        self.message = QLabel('')
        self.message.setObjectName('hint')
        self.message.hide()
        layout.addWidget(self.message)

        self.loader = ThumbnailLoader(self)
        self.loader.ready.connect(self._on_image)
        self.loader.failed.connect(lambda _path, reason: self.show_message(f'Miniaturas indisponíveis: {reason}'))

    def _default_hint(self):
        if self.mode == 'order':
            return 'Arraste as páginas para mudar a ordem (Delete tira a página).'
        return 'Clique nas páginas para escolher (Ctrl+A marca todas).'

    # ---- conteúdo ------------------------------------------------------------------------
    def load(self, path, total):
        """Mostra as páginas de path (total de páginas já conhecido). Desenha as miniaturas em segundo plano."""
        self.path, self.total = str(path), int(total)
        self.images = {}
        self._marked = set()
        self.show_message('')
        self._syncing = True
        try:
            self.grid.clear()
            if self.total > MAX_PAGES:
                self.show_message(f'O PDF tem {self.total} páginas: use o campo de texto para escolher.')
                self.loader.cancel()
                return
            for index in range(self.total):
                self.grid.addItem(self._make_item(index))
        finally:
            self._syncing = False
        self.loader.request(self.path, range(self.total), THUMB.width() * 2, THUMB.height() * 2)

    def clear(self, message=''):
        self.loader.cancel()
        self.path, self.total, self.images = None, 0, {}
        self._marked = set()
        self._syncing = True
        try:
            self.grid.clear()
        finally:
            self._syncing = False
        self.show_message(message)

    def show_message(self, text):
        self.message.setText(text)
        self.message.setVisible(bool(text))

    def _make_item(self, index):
        item = QListWidgetItem()
        item.setData(PAGE_ROLE, index)
        item.setIcon(QIcon(_badge(self.images.get(index), index + 1, index in self._marked)))
        item.setToolTip(f'Página {index + 1}')
        item.setSizeHint(CELL)
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if self.mode == 'order':
            flags |= Qt.ItemIsDragEnabled  # sem ItemIsDropEnabled: soltar entre páginas, nunca "dentro" de uma
        item.setFlags(flags)
        return item

    def items(self):
        return [self.grid.item(row) for row in range(self.grid.count())]

    def _on_image(self, path, index, image):
        if path != self.path:
            return
        self.images[index] = QImage(image)
        icon = QIcon(_badge(self.images[index], index + 1, index in self._marked))
        for item in self.items():
            if item.data(PAGE_ROLE) == index:
                item.setIcon(icon)

    # ---- escolha -------------------------------------------------------------------------
    def selected_pages(self):
        return sorted(item.data(PAGE_ROLE) for item in self.grid.selectedItems())

    def order(self):
        return [item.data(PAGE_ROLE) for item in self.items()]

    def text(self):
        if self.mode == 'order':
            return format_page_ranges(self.order(), keep_order=True)
        return format_page_ranges(self.selected_pages())

    def _emit(self):
        if not self._syncing and self.total:
            self.changed.emit(self.text())

    def _on_selection(self):
        if self.mode != 'select':
            return
        if self.marks_removal:
            self._update_marks()
        self._emit()

    def _update_marks(self):
        """Pinta de vermelho o número das páginas escolhidas (só as que mudaram, para não redesenhar tudo)."""
        marked = set(self.selected_pages())
        for item in self.items():
            index = item.data(PAGE_ROLE)
            if (index in marked) != (index in self._marked):
                item.setIcon(QIcon(_badge(self.images.get(index), index + 1, index in marked)))
        self._marked = marked

    def set_from_text(self, text):
        """O usuário digitou no campo: marca (ou reordena) as miniaturas, se o texto for válido. True se aplicou."""
        if not self.total or self.total > MAX_PAGES:
            return False
        try:
            pages = parse_page_ranges(text, self.total, allow_duplicates=self.mode == 'order') if text.strip() else []
        except PageRangeError:
            return False
        self._syncing = True
        try:
            if self.mode == 'select':
                wanted = set(pages)
                for item in self.items():
                    item.setSelected(item.data(PAGE_ROLE) in wanted)
            elif pages and pages != self.order():
                self.grid.clear()
                for index in pages:
                    self.grid.addItem(self._make_item(index))
        finally:
            self._syncing = False
        if self.marks_removal:
            self._update_marks()
        return True

    def act(self, action):
        """Botões da barra: Todas, Nenhuma, Ímpares, Pares (escolha) ou ←, →, Inverter, Restaurar (ordem)."""
        if not self.total:
            return
        self._syncing = True
        try:
            if action in ('all', 'none', 'odd', 'even'):
                for item in self.items():
                    number = item.data(PAGE_ROLE) + 1
                    item.setSelected(
                        action == 'all'
                        or (action == 'odd' and number % 2 == 1)
                        or (action == 'even' and number % 2 == 0)
                    )
            elif action == 'reverse':
                self._rebuild(list(reversed(self.order())))
            elif action == 'reset':
                self._rebuild(list(range(self.total)))
            elif action in ('left', 'right'):
                self._move_selected(-1 if action == 'left' else 1)
        finally:
            self._syncing = False
        if self.marks_removal:
            self._update_marks()
        self._emit()

    def _rebuild(self, order, selected=()):
        self.grid.clear()
        for position, index in enumerate(order):
            item = self._make_item(index)
            self.grid.addItem(item)
            item.setSelected(position in selected)

    def _move_selected(self, step):
        rows = sorted(self.grid.row(item) for item in self.grid.selectedItems())
        if not rows or (step < 0 and rows[0] == 0) or (step > 0 and rows[-1] == self.grid.count() - 1):
            return
        order = self.order()
        for row in rows if step < 0 else reversed(rows):
            order[row], order[row + step] = order[row + step], order[row]
        self._rebuild(order, {row + step for row in rows})

    def remove_selected(self):
        """Tira as páginas escolhidas da nova ordem (Organizar: páginas fora da lista são descartadas)."""
        rows = {self.grid.row(item) for item in self.grid.selectedItems()}
        if not rows or len(rows) >= self.grid.count():
            return
        self._syncing = True
        try:
            self._rebuild([index for row, index in enumerate(self.order()) if row not in rows])
        finally:
            self._syncing = False
        self._emit()
