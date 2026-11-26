"""Tema do novo visual: paleta e folha de estilo (QSS).

Uma única cor de destaque (o verde da marca); o resto é neutro. Os botões escolhem a variante pela propriedade
"variant" (primary, success, quiet); sem ela, são secundários.
"""

import tempfile
from pathlib import Path

COLORS = {
    'bg': '#f4f6f8',
    'surface': '#ffffff',
    'ink': '#18232e',
    'muted': '#5d6c7a',
    'faint': '#64748b',
    'line': '#e0e6eb',
    'line_strong': '#c9d3db',
    'brand': '#0f766e',
    'brand_hover': '#0b5f58',
    'brand_soft': '#e3f4f1',
    'brand_line': '#b9ddd7',
    'success': '#16845b',
    'success_hover': '#116a49',
    'danger': '#c0392b',
    'tile': '#e6ecef',
    'icon': '#3b4b58',
}
FONT_FAMILY = 'Segoe UI'
ICON_FONT = 'Segoe MDL2 Assets'

_TEMPLATE = """
* { font-family: "Segoe UI"; font-size: 10pt; color: @ink; }
QMainWindow, QWidget#root { background: @bg; }
QDialog, QMessageBox { background: @surface; }
QToolTip { background: @surface; color: @ink; border: 1px solid @line_strong; padding: 4px 6px; }
QLabel { background: transparent; }
QLabel#cardTitle { font-size: 12pt; font-weight: 600; }
QLabel#pageTitle { font-size: 15pt; font-weight: 700; }
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
QLabel[tone="error"] { color: @danger; font-weight: 600; }
QLabel[tone="ok"] { color: @success; font-weight: 600; }
QLabel[tone="info"] { color: @muted; }

QFrame#card { background: @surface; border: 1px solid @line; border-radius: 12px; }
QFrame#dropzone { background: transparent; border: 2px dashed @brand_line; border-radius: 12px; }
QFrame#dropzone[dragging="true"] { background: @brand_soft; border: 2px dashed @brand; }
QWidget#homeContent, QWidget#optionsContent { background: transparent; }

QPushButton {
    background: #f7f9fa; border: 1px solid @line_strong; border-radius: 8px; padding: 8px 14px;
}
QPushButton:hover { background: @brand_soft; border-color: @brand; }
QPushButton:pressed { background: #d3ebe6; }
QPushButton:disabled { color: #97a3ad; background: #f7f9fa; border-color: @line; }
QPushButton:focus { border: 2px solid @brand; background: @brand_soft; padding: 7px 13px; }
QPushButton[size="small"]:focus { padding: 4px 9px; }
QPushButton[variant="primary"] {
    background: @brand; color: #ffffff; border: 1px solid @brand; font-weight: 600; padding: 11px 18px;
}
QPushButton[variant="primary"]:hover { background: @brand_hover; border-color: @brand_hover; }
QPushButton[variant="primary"]:focus { background: @brand; border: 2px solid @ink; padding: 10px 17px; }
QPushButton[variant="primary"]:disabled { background: #9ebfbb; border-color: #9ebfbb; color: #eef6f5; }
QPushButton[variant="success"] {
    background: @success; color: #ffffff; border: 1px solid @success; font-weight: 600;
}
QPushButton[variant="success"]:hover { background: @success_hover; border-color: @success_hover; }
QPushButton[variant="success"]:focus { background: @success; border: 2px solid @ink; padding: 7px 13px; }
QPushButton[variant="quiet"]:focus { background: @brand_soft; border: 2px solid @brand; padding: 7px 13px; }
QPushButton[variant="success"]:disabled { background: #a7cbbd; border-color: #a7cbbd; color: #eef6f5; }
QPushButton[variant="quiet"] { background: transparent; border: 1px solid transparent; color: @brand; font-weight: 600; }
QPushButton[variant="quiet"]:hover { background: @brand_soft; border-color: transparent; }
QPushButton[size="small"] { padding: 5px 10px; font-size: 9pt; }

QLineEdit, QSpinBox, QComboBox {
    background: @surface; border: 1px solid @line_strong; border-radius: 8px; padding: 7px 10px;
    selection-background-color: #cfe9e4; selection-color: #12383a;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QComboBox:on { border: 1px solid @brand; }
QSpinBox::up-button, QSpinBox::down-button { width: 18px; border: none; background: transparent; }
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

QProgressBar { background: #d8e6e3; border: none; border-radius: 4px; max-height: 8px; min-height: 8px; text-align: center; }
QProgressBar::chunk { background: @brand; border-radius: 4px; }

QScrollArea { background: transparent; border: none; }
QSplitter::handle { background: transparent; }
QMenu { background: @surface; border: 1px solid @line_strong; border-radius: 8px; padding: 6px; }
QMenu::item { padding: 7px 22px; border-radius: 6px; }
QMenu::item:selected { background: @brand_soft; color: @ink; }
QMenu::item:disabled { color: #97a3ad; }
QMenu::separator { height: 1px; background: @line; margin: 5px 8px; }
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px 2px 2px 0; }
QScrollBar::handle:vertical { background: #cfd8df; border-radius: 4px; min-height: 36px; margin: 0 2px; }
QScrollBar::handle:vertical:hover { background: #b5c2cc; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 0 2px 2px 2px; }
QScrollBar::handle:horizontal { background: #cfd8df; border-radius: 4px; min-width: 36px; margin: 2px 0; }
QScrollBar::handle:horizontal:hover { background: #b5c2cc; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }

QTreeWidget {
    background: @surface; border: 1px solid @line; border-radius: 8px; outline: 0; show-decoration-selected: 1;
}
QTreeWidget:focus { border: 2px solid @brand; }
QTreeWidget::item { padding: 7px 4px; border-bottom: 1px solid #eef2f5; }
QTreeWidget::item:selected { background: #cfe9e4; color: #12383a; }
QTreeWidget::item:hover:!selected { background: #f1f6f5; }
QHeaderView::section {
    background: #e6edf1; color: #2a4250; border: none; padding: 8px 6px; font-weight: 600;
}
"""


def _write_icons():
    """Setas e tique do QSS são imagens: o Qt não desenha isso só com estilo. Geradas uma vez em uma pasta temporária."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

    folder = Path(tempfile.gettempdir()) / 'rdf_qt_assets'
    folder.mkdir(exist_ok=True)

    def render(name, points, color, width):
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
        path = folder / name
        pixmap.save(str(path))
        return path.as_posix()

    return {
        'check_icon': render('check.png', [(4.5, 9.5), (7.8, 12.8), (13.5, 5.5)], '#ffffff', 2.2),
        'arrow_icon': render('arrow.png', [(4, 6.5), (9, 11.5), (14, 6.5)], COLORS['muted'], 1.8),
    }


def build_stylesheet():
    """Folha de estilo completa. Precisa de um QApplication já criado (gera as imagens do tema)."""
    css = _TEMPLATE
    tokens = dict(COLORS)
    tokens.update(_write_icons())
    for key in sorted(tokens, key=len, reverse=True):  # os nomes mais longos primeiro: @line_strong antes de @line
        css = css.replace(f'@{key}', tokens[key])
    return css
