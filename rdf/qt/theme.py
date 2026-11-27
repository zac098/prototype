"""Tema do visual: paletas clara e escura, folha de estilo (QSS) e troca em tempo real.

Uma única cor de destaque (o verde-azulado da marca); o resto é neutro. Os botões escolhem a variante pela
propriedade "variant" (primary, success, quiet); sem ela, são secundários.

COLORS é sempre a paleta em uso: a troca de tema muda o mesmo dicionário, então quem desenha com QPainter lê a cor
certa no próximo paintEvent. Quem guarda cores (a tabela do renomeador, por exemplo) ouve manager().changed.
Nenhuma tela define cores próprias: tudo passa por aqui, inclusive os tons de status (OK, revisar, erro).
"""

import tempfile
from pathlib import Path

LIGHT = {
    'bg': '#f4f6f8',
    'surface': '#ffffff',
    'raised': '#f9fbfc',  # faixas e cabeçalhos levemente destacados do cartão
    'ink': '#18232e',
    'muted': '#526170',
    'faint': '#5f6e7c',
    'line': '#e0e6eb',
    'line_strong': '#c9d3db',
    'brand': '#0f766e',
    'brand_hover': '#0b5f58',
    'brand_pressed': '#d3ebe6',
    'brand_soft': '#e3f4f1',
    'brand_line': '#b9ddd7',
    'on_brand': '#ffffff',
    'brand_disabled': '#9ebfbb',
    'on_brand_disabled': '#eef6f5',
    'success': '#16845b',
    'success_hover': '#116a49',
    'success_disabled': '#a7cbbd',
    'danger': '#b42318',
    'danger_soft': '#fde8e6',
    'button': '#f7f9fa',
    'disabled_ink': '#8d99a3',
    'selection': '#cfe9e4',
    'selection_ink': '#12383a',
    'track': '#d8e6e3',
    'scroll': '#cfd8df',
    'scroll_hover': '#b5c2cc',
    'row_line': '#eef2f5',
    'row_hover': '#f1f6f5',
    'header': '#e9eff3',
    'header_ink': '#2a4250',
    'tile': '#e6ecef',
    'icon': '#3b4b58',
    'canvas': '#e8efef',
    'canvas_line': '#c7d7d6',
    'star': '#c47f00',
    'tone_ok': '#176b3a',
    'tone_ok_bg': '#e3f5ea',
    'tone_approved': '#075985',
    'tone_approved_bg': '#e0f0fa',
    'tone_review': '#7a4300',
    'tone_review_bg': '#fff1cc',
    'tone_error': '#8f1713',
    'tone_error_bg': '#ffd9d6',
    'tone_pending': '#4f5d69',
    'tone_pending_bg': '#eceff2',
    'shadow': '#1a2b3a',
}

DARK = {
    'bg': '#0f1418',
    'surface': '#171e24',
    'raised': '#1b232a',
    'ink': '#e6edf3',
    'muted': '#a4b1bd',
    'faint': '#93a1ae',
    'line': '#26313a',
    'line_strong': '#36444f',
    'brand': '#2bb3a3',
    'brand_hover': '#45c7b7',
    'brand_pressed': '#1b3d39',
    'brand_soft': '#15302d',
    'brand_line': '#2a5a54',
    'on_brand': '#04211e',
    'brand_disabled': '#2c4f4b',
    'on_brand_disabled': '#7f9c98',
    'success': '#35b27a',
    'success_hover': '#4cc78f',
    'success_disabled': '#2b4c3e',
    'danger': '#ff8a7a',
    'danger_soft': '#3d1a17',
    'button': '#1d262d',
    'disabled_ink': '#5d6b77',
    'selection': '#1f4743',
    'selection_ink': '#e6f4f2',
    'track': '#24343a',
    'scroll': '#34424d',
    'scroll_hover': '#475763',
    'row_line': '#1f282f',
    'row_hover': '#1c252c',
    'header': '#1f2830',
    'header_ink': '#c8d4de',
    'tile': '#222d35',
    'icon': '#bccad5',
    'canvas': '#0b1014',
    'canvas_line': '#26313a',
    'star': '#f2b84b',
    'tone_ok': '#5fd39b',
    'tone_ok_bg': '#14291f',
    'tone_approved': '#6cc2f0',
    'tone_approved_bg': '#112634',
    'tone_review': '#f3bd5c',
    'tone_review_bg': '#33270f',
    'tone_error': '#ff9384',
    'tone_error_bg': '#3a1916',
    'tone_pending': '#b3c0cb',
    'tone_pending_bg': '#222b33',
    'shadow': '#000000',
}

PALETTES = {'claro': LIGHT, 'escuro': DARK}
COLORS = dict(LIGHT)
FONT_FAMILY = 'Segoe UI'
ICON_FONT = 'Segoe MDL2 Assets'

_state = {'mode': 'sistema', 'resolved': 'claro', 'applying': False}

_TEMPLATE = """
* { font-family: "Segoe UI"; font-size: 10pt; color: @ink; }
QMainWindow, QWidget#root { background: @bg; }
QDialog, QMessageBox { background: @surface; }
QToolTip { background: @surface; color: @ink; border: 1px solid @line_strong; padding: 4px 6px; }
QLabel { background: transparent; }
QLabel#cardTitle { font-size: 12pt; font-weight: 600; }
QLabel#pageTitle { font-size: 15pt; font-weight: 700; }
QLabel#heroTitle { font-size: 19pt; font-weight: 700; }
QLabel#pageLead { color: @muted; }
QLabel#fieldLabel { font-weight: 600; font-size: 9pt; }
QLabel#hint { color: @faint; font-size: 9pt; }
QLabel#groupTitle { font-size: 11pt; font-weight: 700; }
QLabel#groupCount { color: @faint; font-size: 9pt; }
QLabel#rowTitle { font-weight: 700; }
QLabel#caption { color: @muted; font-weight: 600; font-size: 9pt; }
QLabel#summary { color: @brand; font-weight: 600; font-size: 9pt; }
QLabel#status { color: @muted; font-size: 9pt; }
QLabel#rowDescription { color: @muted; font-size: 9pt; }
QLabel#version { color: @brand; background: @brand_soft; border-radius: 9px; padding: 2px 9px; font-size: 8pt; font-weight: 600; }
QLabel#kbd { color: @muted; background: @raised; border: 1px solid @line_strong; border-radius: 5px; padding: 1px 6px; font-size: 9pt; }
QLabel#previewBox { background: @canvas; border: 1px solid @line; border-radius: 8px; color: @faint; }
QLabel[tone="error"] { color: @danger; font-weight: 600; }
QLabel[tone="ok"] { color: @success; font-weight: 600; }
QLabel[tone="info"] { color: @muted; }
QLabel[tone="review"] { color: @tone_review; }
QLabel[tone="blocked"] { color: @tone_error; }
QLabel#dialogTitle { font-size: 15pt; font-weight: 700; }
QLabel#dialogTitle[tone="error"] { color: @tone_error; }

QFrame#card { background: @surface; border: 1px solid @line; border-radius: 12px; }
QFrame#resultCard { background: @tone_ok_bg; border: 1px solid @line; border-radius: 10px; }
QFrame#resultCard[tone="error"] { background: @danger_soft; }
QFrame#vline { background: @line; border: none; }
QFrame#dropzone { background: transparent; border: 2px dashed @brand_line; border-radius: 12px; }
QFrame#dropzone[dragging="true"] { background: @brand_soft; border: 2px dashed @brand; }
QWidget#homeContent, QWidget#optionsContent { background: transparent; }

QPushButton {
    background: @button; border: 1px solid @line_strong; border-radius: 8px; padding: 8px 14px;
}
QPushButton:hover { background: @brand_soft; border-color: @brand; }
QPushButton:pressed { background: @brand_pressed; }
QPushButton:disabled { color: @disabled_ink; background: @button; border-color: @line; }
QPushButton:focus { border: 2px solid @brand; background: @brand_soft; padding: 7px 13px; }
QPushButton[size="small"]:focus { padding: 4px 9px; }
QPushButton[variant="primary"] {
    background: @brand; color: @on_brand; border: 1px solid @brand; font-weight: 600; padding: 11px 18px;
}
QPushButton[variant="primary"]:hover { background: @brand_hover; border-color: @brand_hover; }
QPushButton[variant="primary"]:focus { background: @brand; border: 2px solid @ink; padding: 10px 17px; }
QPushButton[variant="primary"]:disabled { background: @brand_disabled; border-color: @brand_disabled; color: @on_brand_disabled; }
QPushButton[variant="success"] {
    background: @success; color: @on_brand; border: 1px solid @success; font-weight: 600;
}
QPushButton[variant="success"]:hover { background: @success_hover; border-color: @success_hover; }
QPushButton[variant="success"]:focus { background: @success; border: 2px solid @ink; padding: 7px 13px; }
QPushButton[variant="quiet"]:focus { background: @brand_soft; border: 2px solid @brand; padding: 7px 13px; }
QPushButton[variant="success"]:disabled { background: @success_disabled; border-color: @success_disabled; color: @on_brand_disabled; }
QPushButton[variant="quiet"] { background: transparent; border: 1px solid transparent; color: @brand; font-weight: 600; }
QPushButton[variant="quiet"]:hover { background: @brand_soft; border-color: transparent; }
QPushButton[variant="danger"] { color: @danger; }
QPushButton[size="small"] { padding: 5px 10px; font-size: 9pt; }
QPushButton[chip="true"] { border-radius: 12px; padding: 4px 13px; font-size: 9pt; min-height: 16px; }
QPushButton[chip="true"]:checked { background: @brand; color: @on_brand; border-color: @brand; font-weight: 600; }
QPushButton[chip="true"]:checked:focus { border: 2px solid @ink; padding: 3px 12px; }
QPushButton[chip="true"]:focus { padding: 3px 12px; }

QToolButton#iconButton {
    background: transparent; border: 1px solid transparent; border-radius: 10px; padding: 6px; color: @icon;
}
QToolButton#iconButton:hover { background: @brand_soft; color: @brand; }
QToolButton#iconButton:focus { border: 2px solid @brand; padding: 5px; }
QToolButton#searchClear { border: none; background: transparent; color: @faint; padding: 4px 6px; }
QToolButton#searchClear:hover { color: @ink; }

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit {
    background: @surface; border: 1px solid @line_strong; border-radius: 8px; padding: 7px 10px;
    selection-background-color: @selection; selection-color: @selection_ink;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QComboBox:on, QPlainTextEdit:focus { border: 1px solid @brand; }
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled { color: @disabled_ink; background: @raised; }
QLineEdit#searchEdit, QLineEdit#searchEdit:focus { background: transparent; border: none; padding: 0px; font-size: 11pt; }
QLineEdit#filterEdit { padding: 5px 10px; border-radius: 14px; }
QSpinBox::up-button, QSpinBox::down-button { width: 20px; border: none; background: transparent; }
QSpinBox::up-arrow { image: url("@up_icon"); width: 10px; height: 10px; }
QSpinBox::down-arrow { image: url("@arrow_icon"); width: 10px; height: 10px; }
QComboBox::drop-down { border: none; width: 28px; }
QComboBox::down-arrow { image: url("@arrow_icon"); width: 12px; height: 12px; }
QComboBox QAbstractItemView {
    background: @surface; border: 1px solid @line_strong; border-radius: 6px; padding: 4px; outline: 0;
    selection-background-color: @brand_soft; selection-color: @ink;
}

QCheckBox { spacing: 9px; }
QCheckBox::indicator { width: 18px; height: 18px; border: 1px solid @line_strong; border-radius: 5px; background: @surface; }
QCheckBox::indicator:hover { border-color: @brand; }
QCheckBox::indicator:focus { border: 2px solid @brand; }
QCheckBox::indicator:checked { background: @brand; border-color: @brand; image: url("@check_icon"); }
QCheckBox:disabled { color: @disabled_ink; }
QRadioButton { spacing: 9px; }

QProgressBar { background: @track; border: none; border-radius: 4px; max-height: 8px; min-height: 8px; text-align: center; }
QProgressBar::chunk { background: @brand; border-radius: 4px; }

QScrollArea { background: transparent; border: none; }
QSplitter::handle { background: transparent; }
QMenu { background: @surface; border: 1px solid @line_strong; border-radius: 8px; padding: 6px; }
QMenu::item { padding: 7px 22px; border-radius: 6px; }
QMenu::item:selected { background: @brand_soft; color: @ink; }
QMenu::item:disabled { color: @disabled_ink; }
QMenu::separator { height: 1px; background: @line; margin: 5px 8px; }
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px 2px 2px 0; }
QScrollBar::handle:vertical { background: @scroll; border-radius: 4px; min-height: 36px; margin: 0 2px; }
QScrollBar::handle:vertical:hover { background: @scroll_hover; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 0 2px 2px 2px; }
QScrollBar::handle:horizontal { background: @scroll; border-radius: 4px; min-width: 36px; margin: 2px 0; }
QScrollBar::handle:horizontal:hover { background: @scroll_hover; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }

QTreeWidget, QListWidget {
    background: @surface; border: 1px solid @line; border-radius: 8px; outline: 0; show-decoration-selected: 1;
}
QTreeWidget:focus { border: 2px solid @brand; }
QListWidget:focus { border: 2px solid @brand; }
QTreeWidget::item { padding: 7px 4px; border-bottom: 1px solid @row_line; }
QTreeWidget::item:selected { background: @selection; color: @selection_ink; }
QTreeWidget::item:hover:!selected { background: @row_hover; }
QListWidget#thumbs { background: @canvas; border: 1px solid @line; }
QListWidget#thumbs::item { border-radius: 8px; padding: 6px; color: @ink; }
QListWidget#thumbs::item:selected { background: @selection; color: @selection_ink; }
QListWidget#thumbs::item:hover:!selected { background: @row_hover; }
QHeaderView::section {
    background: @header; color: @header_ink; border: none; padding: 8px 6px; font-weight: 600;
}
QGraphicsView#pageView { background: @canvas; border: 1px solid @canvas_line; border-radius: 8px; }
QTabWidget::pane { border: none; }
"""


def resolve(mode):
    """'claro' ou 'escuro'. Em 'sistema', segue o Windows (claro se não der para saber)."""
    if mode in PALETTES:
        return mode
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication

        app = QGuiApplication.instance()
        if app is not None and app.styleHints().colorScheme() == Qt.ColorScheme.Dark:
            return 'escuro'
    except (ImportError, AttributeError):
        pass
    return 'claro'


def _request_scheme(app, mode):
    """Pede ao Qt o esquema de cores (claro, escuro ou o do sistema). No Windows isso também escurece a barra de
    título da janela. Qt antigo, sem o recurso: não faz nada."""
    try:
        from PySide6.QtCore import Qt

        hints = app.styleHints()
        if hasattr(hints, 'setColorScheme'):
            target = {'claro': Qt.ColorScheme.Light, 'escuro': Qt.ColorScheme.Dark}.get(mode, Qt.ColorScheme.Unknown)
            hints.setColorScheme(target)
    except (ImportError, AttributeError, TypeError):
        pass


def current_mode():
    """O que o usuário escolheu: 'sistema', 'claro' ou 'escuro'."""
    return _state['mode']


def is_dark():
    return _state['resolved'] == 'escuro'


def _write_icons(colors, name):
    """Setas e tique do QSS são imagens: o Qt não desenha isso só com estilo. Geradas por tema numa pasta temporária."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

    folder = Path(tempfile.gettempdir()) / 'rdf_qt_assets'
    folder.mkdir(exist_ok=True)

    def render(file_name, points, color, width):
        pixmap = QPixmap(18, 18)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(color), width)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline([QPointF(x, y) for x, y in points])
        painter.end()
        path = folder / f'{file_name}-{name}.png'
        pixmap.save(str(path))
        return path.as_posix()

    return {
        'check_icon': render('check', [(4.5, 9.5), (7.8, 12.8), (13.5, 5.5)], colors['on_brand'], 2.2),
        'arrow_icon': render('arrow', [(4, 6.5), (9, 11.5), (14, 6.5)], colors['muted'], 1.8),
        'up_icon': render('up', [(4, 11.5), (9, 6.5), (14, 11.5)], colors['muted'], 1.8),
    }


def build_stylesheet(mode=None):
    """Folha de estilo completa do tema. Precisa de um QApplication já criado (gera as imagens do tema)."""
    name = resolve(mode) if mode is not None else _state['resolved']
    colors = PALETTES[name]
    css = _TEMPLATE
    tokens = dict(colors)
    tokens.update(_write_icons(colors, name))
    for key in sorted(tokens, key=len, reverse=True):  # os nomes mais longos primeiro: @line_strong antes de @line
        css = css.replace(f'@{key}', tokens[key])
    return css


def _palette(colors):
    """Paleta do Qt com as mesmas cores: vale para o que a folha de estilo não alcança (diálogos do sistema etc.)."""
    from PySide6.QtGui import QColor, QPalette

    palette = QPalette()
    roles = {
        QPalette.Window: 'bg',
        QPalette.WindowText: 'ink',
        QPalette.Base: 'surface',
        QPalette.AlternateBase: 'raised',
        QPalette.Text: 'ink',
        QPalette.Button: 'button',
        QPalette.ButtonText: 'ink',
        QPalette.ToolTipBase: 'surface',
        QPalette.ToolTipText: 'ink',
        QPalette.PlaceholderText: 'faint',
        QPalette.Highlight: 'selection',
        QPalette.HighlightedText: 'selection_ink',
        QPalette.Link: 'brand',
        QPalette.BrightText: 'on_brand',
    }
    for role, key in roles.items():
        palette.setColor(role, QColor(colors[key]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor(colors['disabled_ink']))
    return palette


class _Manager:
    """Avisa quem guarda cores que o tema mudou (criado na primeira chamada, depois do QApplication)."""

    def __init__(self):
        from PySide6.QtCore import QObject, Signal

        class Notifier(QObject):
            changed = Signal(str)

        self.notifier = Notifier()
        self.changed = self.notifier.changed
        self._watching = False

    def watch_system(self, app):
        """No modo 'sistema', troca sozinho quando o Windows muda entre claro e escuro."""
        if self._watching:
            return
        try:
            app.styleHints().colorSchemeChanged.connect(self._on_system_change)
            self._watching = True
        except AttributeError:  # Qt antigo: sem aviso de mudança
            pass

    def _on_system_change(self, *_args):
        if _state['mode'] == 'sistema' and not _state['applying']:
            apply(None, 'sistema')


_manager = None


def manager():
    global _manager
    if _manager is None:
        _manager = _Manager()
    return _manager


def apply(app=None, mode=None):
    """Aplica o tema ('sistema', 'claro' ou 'escuro') ao app inteiro, já aberto ou não. Devolve o tema resolvido."""
    from PySide6.QtWidgets import QApplication

    app = app or QApplication.instance()
    mode = mode if mode in (*PALETTES, 'sistema') else 'sistema'
    if app is not None:
        _state['applying'] = True
        try:
            _request_scheme(app, mode)  # antes de resolver: no modo sistema, volta a valer o esquema do Windows
        finally:
            _state['applying'] = False
    resolved = resolve(mode)
    changed = resolved != _state['resolved'] or mode != _state['mode']
    _state['mode'], _state['resolved'] = mode, resolved
    COLORS.clear()
    COLORS.update(PALETTES[resolved])
    if app is None:
        return resolved
    css = build_stylesheet()
    if css != app.styleSheet():  # trocar a folha repole todos os widgets: só quando algo mudou de verdade
        app.setPalette(_palette(COLORS))
        app.setStyleSheet(css)
    notifier = manager()
    notifier.watch_system(app)
    if changed:
        for widget in app.allWidgets():
            widget.update()  # os desenhados à mão leem COLORS de novo
        notifier.changed.emit(resolved)
    return resolved
