"""Tela inicial: barra com a marca, a busca e os atalhos (tema, configurações, ajuda), e as ferramentas.

As ferramentas aparecem agrupadas por categoria; antes delas, as favoritas (estrela) e as usadas recentemente.
Filtros por categoria logo acima da lista. Pelo teclado: Ctrl+F vai para a busca, Enter abre o primeiro resultado,
a seta para baixo entra na lista e as setas andam entre as ferramentas.
"""

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from rdf import APP_VERSION
from rdf.core import settings
from rdf.pdftools.registry import CATEGORIES, NEW_TOOLS, TOOLS_BY_ID, search_tools
from rdf.qt import theme
from rdf.qt.updater import UpdateBanner
from rdf.qt.widgets import BrandMark, SearchBar, SmoothScrollArea, ToolRow, icon_button

COLUMN_MIN_WIDTH = 330
COLUMN_GAP = 18
MAX_COLUMNS = 3
SIDE_MARGIN = 36
CHIPS_BELOW = 900  # abaixo desta largura os filtros por categoria somem (a busca continua)
ALL = 'Todas'
FAVORITES = 'Favoritas'
RECENT = 'Usadas recentemente'
THEME_LABELS = {'sistema': 'Igual ao Windows', 'claro': 'Claro', 'escuro': 'Escuro'}


class HomePage(QWidget):
    toolRequested = Signal(str)
    themeRequested = Signal(str)
    settingsRequested = Signal()
    aboutRequested = Signal()
    shortcutsRequested = Signal()
    updatesRequested = Signal()  # "Procurar atualizações" no menu de ajuda
    updateRequested = Signal()  # "Atualizar…" no aviso de versão nova

    def __init__(self, parent=None):
        super().__init__(parent)
        self.query = ''
        self.category = ALL
        self.cards = []  # as linhas, na ordem em que aparecem
        self.sections = []  # (grade, linhas) de cada seção
        self.section_titles = []
        self.columns = 0
        self._rendered = None  # (favoritas, recentes) da última montagem: muda -> monta de novo ao voltar

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())
        banner_row = QHBoxLayout()
        banner_row.setContentsMargins(SIDE_MARGIN, 4, SIDE_MARGIN, 2)
        self.update_banner = UpdateBanner()
        self.update_banner.updateRequested.connect(self.updateRequested)
        banner_row.addWidget(self.update_banner)
        outer.addLayout(banner_row)

        self.scroll = SmoothScrollArea()
        outer.addWidget(self.scroll, 1)
        self.scroll.viewport().installEventFilter(self)  # as colunas dependem da largura real da área
        content = QWidget()
        content.setObjectName('homeContent')
        body = QVBoxLayout(content)
        body.setContentsMargins(SIDE_MARGIN, 14, SIDE_MARGIN, 24)
        body.setSpacing(0)
        body.addWidget(self._build_chips())
        body.addSpacing(16)
        self.sections_box = QVBoxLayout()
        self.sections_box.setSpacing(0)
        body.addLayout(self.sections_box)
        self.empty_label = QLabel('Nenhuma ferramenta encontrada para esta busca.')
        self.empty_label.setObjectName('pageLead')
        self.empty_label.setWordWrap(True)
        self.empty_label.hide()
        body.addWidget(self.empty_label)
        body.addSpacing(12)
        note = QLabel('🔒  Os arquivos são processados neste computador e não saem dele.')
        note.setObjectName('hint')
        body.addWidget(note)
        body.addStretch(1)
        self.scroll.setWidget(content)

        self.search.textChanged.connect(self.set_query)
        self.search.submitted.connect(self.open_first)
        self.search.moveDown.connect(self.focus_first)
        theme.manager().changed.connect(self.update_theme_button)
        self.refresh()

    # ---- montagem ------------------------------------------------------------------------
    def _build_header(self):
        header = QWidget()
        row = QHBoxLayout(header)
        row.setContentsMargins(28, 14, 22, 8)
        row.setSpacing(12)
        brand = QHBoxLayout()
        brand.setSpacing(12)
        brand.addWidget(BrandMark(40))
        names = QVBoxLayout()
        names.setSpacing(0)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title = QLabel('RDF')
        title.setObjectName('cardTitle')
        version = QLabel(f'v{APP_VERSION}')
        version.setObjectName('version')
        title_row.addWidget(title)
        title_row.addWidget(version)
        title_row.addStretch(1)
        subtitle = QLabel('Ferramentas de PDF')
        subtitle.setObjectName('hint')
        names.addLayout(title_row)
        names.addWidget(subtitle)
        brand.addLayout(names)
        self.brand_box = QWidget()
        self.brand_box.setLayout(brand)
        self.brand_box.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        row.addWidget(self.brand_box)
        row.addStretch(1)
        self.search = SearchBar()
        row.addWidget(self.search, 100)
        row.addStretch(1)

        self.theme_button = icon_button('theme', 'Tema')
        self.theme_button.clicked.connect(self.show_theme_menu)
        self.settings_button = icon_button('settings', 'Configurações (Ctrl+,)')
        self.settings_button.clicked.connect(self.settingsRequested)
        self.help_button = icon_button('help', 'Ajuda (F1)')
        self.help_button.clicked.connect(self.show_help_menu)
        for button in (self.theme_button, self.settings_button, self.help_button):
            row.addWidget(button)
        self.update_theme_button()
        return header

    def _build_chips(self):
        self.chips_box = QWidget()
        row = QHBoxLayout(self.chips_box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.chip_group = QButtonGroup(self)
        self.chip_group.setExclusive(True)
        self.chips = {}
        for name in (ALL, *CATEGORIES):
            chip = QPushButton(name)
            chip.setProperty('chip', True)
            chip.setCheckable(True)
            chip.setCursor(Qt.PointingHandCursor)
            chip.setAccessibleName(f'Mostrar {name.lower()}' if name != ALL else 'Mostrar todas as ferramentas')
            chip.clicked.connect(lambda _checked=False, value=name: self.set_category(value))
            self.chip_group.addButton(chip)
            self.chips[name] = chip
            row.addWidget(chip)
        row.addStretch(1)
        self.chips[ALL].setChecked(True)
        return self.chips_box

    # ---- tema e ajuda --------------------------------------------------------------------
    def update_theme_button(self, *_args):
        mode = theme.current_mode()
        self.theme_button.setToolTip(f'Tema: {THEME_LABELS.get(mode, mode)}')

    def theme_menu(self):
        menu = QMenu(self)
        current = theme.current_mode()
        for mode, label in THEME_LABELS.items():
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(mode == current)
            action.triggered.connect(lambda _checked=False, value=mode: self.themeRequested.emit(value))
        return menu

    def show_theme_menu(self):
        self.theme_menu().exec(self.theme_button.mapToGlobal(QPoint(0, self.theme_button.height())))

    def help_menu(self):
        menu = QMenu(self)
        menu.addAction('Atalhos do teclado\tF1', self.shortcutsRequested.emit)
        menu.addAction('Procurar atualizações', self.updatesRequested.emit)
        menu.addAction('Sobre o RDF', self.aboutRequested.emit)
        return menu

    def show_update(self, release):
        """Mostra o aviso de versão nova no topo da tela inicial."""
        self.update_banner.show_release(release)

    def show_help_menu(self):
        self.help_menu().exec(self.help_button.mapToGlobal(QPoint(0, self.help_button.height())))

    # ---- busca e filtros -----------------------------------------------------------------
    def set_query(self, text):
        text = text.strip()
        if text != self.query:
            self.query = text
            self.refresh()

    def set_category(self, category):
        self.category = category if category in (ALL, *CATEGORIES) else ALL
        self.chips[self.category].setChecked(True)
        self.refresh()

    def visible_tools(self):
        tools = search_tools(self.query)
        if self.category != ALL:
            tools = [tool for tool in tools if tool.category == self.category]
        return tools

    def shortcut_sections(self):
        """(título, ferramentas) das favoritas e recentes: só sem busca e sem filtro de categoria."""
        if self.query or self.category != ALL:
            return []
        prefs = settings.current()
        found = []
        favorites = [TOOLS_BY_ID[item] for item in prefs.get('favorites') if item in TOOLS_BY_ID]
        if favorites:
            found.append((FAVORITES, favorites))
        recent = [TOOLS_BY_ID[item] for item in prefs.get('recent') if item in TOOLS_BY_ID]
        recent = [tool for tool in recent if tool not in favorites][:3]
        if recent:
            found.append((RECENT, recent))
        return found

    def sync(self):
        """Monta de novo se as favoritas ou recentes mudaram desde a última vez (ao voltar para o início)."""
        prefs = settings.current()
        if self._rendered != (tuple(prefs.get('favorites')), tuple(prefs.get('recent'))):
            self.refresh()

    def refresh(self):
        while self.sections_box.count():
            widget = self.sections_box.takeAt(0).widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self.cards, self.sections, self.section_titles = [], [], []
        self.columns = 0
        prefs = settings.current()
        self._rendered = (tuple(prefs.get('favorites')), tuple(prefs.get('recent')))
        tools = self.visible_tools()
        groups = list(self.shortcut_sections())
        categories = list(CATEGORIES)
        if self.query:  # com busca, a categoria do resultado mais relevante vem primeiro
            order = {}
            for tool in tools:
                order.setdefault(tool.category, len(order))
            categories.sort(key=lambda name: order.get(name, len(order)))
        for category in categories:
            group = [tool for tool in tools if tool.category == category]
            if group:
                groups.append((category, group))
        for title, group in groups:
            self._add_section(title, group)
        self.empty_label.setText(
            f'Nenhuma ferramenta encontrada para “{self.query}”. Tente outras palavras, como "juntar", "senha" ou '
            '"girar".'
            if self.query
            else 'Nenhuma ferramenta nesta categoria.'
        )
        self.empty_label.setVisible(not tools)
        self.layout_columns(force=True)

    def _add_section(self, title_text, group):
        section = QWidget()
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0, 0, 0, 20)
        section_layout.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title = QLabel(('★  ' if title_text == FAVORITES else '') + title_text)
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
        prefs = settings.current()
        rows = []
        for tool in group:
            row = ToolRow(tool, favorite=prefs.is_favorite(tool.id), badge='Novo' if tool.id in NEW_TOOLS else '')
            row.clicked.connect(self.toolRequested)
            row.favoriteToggled.connect(self.toggle_favorite)
            row.navigate.connect(self.move_focus)
            row.installEventFilter(self)
            rows.append(row)
        self.cards.extend(rows)
        self.sections.append((grid, rows))
        self.section_titles.append(title_text)
        self.sections_box.addWidget(section)

    # ---- favoritas -----------------------------------------------------------------------
    def toggle_favorite(self, tool_id):
        favorite = settings.current().toggle_favorite(tool_id)
        focused = self.focusWidget()
        focused_id = focused.tool.id if isinstance(focused, ToolRow) else None
        self.refresh()
        if focused_id:  # o foco volta para a mesma ferramenta (na seção da categoria, não na das favoritas)
            match = [card for card in self.cards if card.tool.id == focused_id]
            if match:
                match[-1].setFocus(Qt.TabFocusReason)  # pelo teclado: mostra o destaque de foco
        return favorite

    # ---- teclado -------------------------------------------------------------------------
    def open_first(self):
        """Enter na busca: abre o resultado mais relevante (sem nada digitado, não abre nada)."""
        if self.query and self.cards:
            self.toolRequested.emit(self.cards[0].tool.id)

    def focus_first(self):
        if self.cards:
            self.cards[0].setFocus(Qt.TabFocusReason)

    def move_focus(self, card, dx, dy):
        """Leva o foco para a ferramenta vizinha na direção das setas (subindo da primeira, volta à busca)."""
        content = self.scroll.widget()
        here = card.mapTo(content, card.rect().center())
        best, best_score = None, None
        for other in self.cards:
            if other is card or not other.isVisible():
                continue
            there = other.mapTo(content, other.rect().center())
            ddx, ddy = there.x() - here.x(), there.y() - here.y()
            if dx and (ddx * dx <= 4 or abs(ddy) > card.height() / 2):
                continue  # para os lados: só na mesma linha
            if dy and ddy * dy <= 4:
                continue
            score = (abs(ddy) * 3 + abs(ddx)) if dy else abs(ddx)
            if best_score is None or score < best_score:
                best, best_score = other, score
        if best is not None:
            best.setFocus(Qt.TabFocusReason)
        elif dy < 0:
            self.search.focus_edit()

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
        elif isinstance(watched, ToolRow) and event.type() == QEvent.FocusIn:
            self.scroll.ensureWidgetVisible(watched, 0, 24)  # a ferramenta com foco nunca fica fora da tela
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.layout_columns()
        width = self.width()
        self.chips_box.setVisible(width >= CHIPS_BELOW)
        self.brand_box.setVisible(width >= 720)
