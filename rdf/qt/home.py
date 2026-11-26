"""Tela inicial: busca centralizada no topo e todas as ferramentas agrupadas por categoria."""

from PySide6.QtCore import QEvent, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from rdf.pdftools.registry import CATEGORIES, search_tools
from rdf.qt.widgets import SearchBar, SmoothScrollArea, ToolRow

COLUMN_MIN_WIDTH = 330
COLUMN_GAP = 18
MAX_COLUMNS = 3
SIDE_MARGIN = 36


class HomePage(QWidget):
    toolRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.query = ''
        self.cards = []  # as linhas, na ordem em que aparecem
        self.sections = []  # (grade, linhas) de cada categoria
        self.section_titles = []
        self.columns = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(28, 16, 28, 4)
        self.search = SearchBar()
        header_layout.addStretch(1)
        header_layout.addWidget(self.search, 100)
        header_layout.addStretch(1)
        outer.addWidget(header)

        self.scroll = SmoothScrollArea()
        outer.addWidget(self.scroll, 1)
        self.scroll.viewport().installEventFilter(self)  # as colunas dependem da largura real da área
        content = QWidget()
        content.setObjectName('homeContent')
        body = QVBoxLayout(content)
        body.setContentsMargins(SIDE_MARGIN, 20, SIDE_MARGIN, 24)
        body.setSpacing(0)
        self.sections_box = QVBoxLayout()
        self.sections_box.setSpacing(0)
        body.addLayout(self.sections_box)
        self.empty_label = QLabel('Nenhuma ferramenta encontrada para esta busca.')
        self.empty_label.setObjectName('pageLead')
        self.empty_label.hide()
        body.addWidget(self.empty_label)
        body.addSpacing(12)
        note = QLabel('Os arquivos são processados neste computador e não saem dele.')
        note.setObjectName('hint')
        body.addWidget(note)
        body.addStretch(1)
        self.scroll.setWidget(content)

        self.search.textChanged.connect(self.set_query)
        self.refresh()

    # ---- busca ---------------------------------------------------------------------------
    def set_query(self, text):
        text = text.strip()
        if text != self.query:
            self.query = text
            self.refresh()

    def visible_tools(self):
        return search_tools(self.query)

    def refresh(self):
        while self.sections_box.count():
            widget = self.sections_box.takeAt(0).widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self.cards, self.sections, self.section_titles = [], [], []
        self.columns = 0
        tools = self.visible_tools()
        for category in CATEGORIES:
            group = [tool for tool in tools if tool.category == category]
            if not group:
                continue
            section = QWidget()
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(0, 0, 0, 20)
            section_layout.setSpacing(2)
            title_row = QHBoxLayout()
            title_row.setSpacing(8)
            title = QLabel(category)
            title.setObjectName('groupTitle')
            count = QLabel(str(len(group)))
            count.setObjectName('groupCount')
            title_row.addWidget(title)
            title_row.addWidget(count)
            title_row.addStretch(1)
            section_layout.addLayout(title_row)
            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(COLUMN_GAP)
            grid.setVerticalSpacing(0)
            section_layout.addLayout(grid)
            rows = []
            for tool in group:
                row = ToolRow(tool)
                row.clicked.connect(self.toolRequested)
                rows.append(row)
            self.cards.extend(rows)
            self.sections.append((grid, rows))
            self.section_titles.append(category)
            self.sections_box.addWidget(section)
        self.empty_label.setVisible(not tools)
        self.layout_columns(force=True)

    # ---- colunas -------------------------------------------------------------------------
    def layout_columns(self, force=False):
        width = self.scroll.viewport().width() - 2 * SIDE_MARGIN
        columns = max(1, min(MAX_COLUMNS, (width + COLUMN_GAP) // (COLUMN_MIN_WIDTH + COLUMN_GAP)))
        if columns == self.columns and not force:
            return
        self.columns = columns
        for grid, rows in self.sections:
            for row in rows:
                grid.removeWidget(row)
            for index in range(MAX_COLUMNS + 1):
                grid.setColumnStretch(index, 1 if index < columns else 0)
            for index, row in enumerate(rows):
                line, column = divmod(index, columns)
                grid.addWidget(row, line, column)

    def eventFilter(self, watched, event):
        if watched is self.scroll.viewport() and event.type() == QEvent.Resize:
            self.layout_columns()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.layout_columns()
