"""Peças visuais do novo visual (Qt): ícones, linha de ferramenta, botão Voltar, busca e rolagem suave.

Tudo é pintado com QPainter, que desenha com bordas suaves (anti-aliasing) por padrão. As transições (hover, foco,
rolagem) usam uma só linguagem: desaceleração suave, e desligam sozinhas quando o Windows pede menos animação.
"""

from PySide6.QtCore import QEasingCurve, QEvent, QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from rdf.qt.motion import animations_enabled
from rdf.qt.theme import COLORS, FONT_FAMILY, ICON_FONT

HOVER_MS = 140
SCROLL_MS = 260
SCROLL_STEP = 80  # pixels por clique da roda
_icon_font_found = None


def mix(color_a, color_b, amount):
    """Cor entre as duas (amount 0 = a primeira, 1 = a segunda). Aceita #rrggbb ou QColor."""
    a, b = QColor(color_a), QColor(color_b)
    amount = max(0.0, min(1.0, amount))
    return QColor(
        round(a.red() + (b.red() - a.red()) * amount),
        round(a.green() + (b.green() - a.green()) * amount),
        round(a.blue() + (b.blue() - a.blue()) * amount),
    )


def has_icon_font():
    global _icon_font_found
    if _icon_font_found is None:
        _icon_font_found = ICON_FONT in QFontDatabase.families()
    return _icon_font_found


def glyph_font(pixel_size):
    font = QFont(ICON_FONT)
    font.setPixelSize(max(6, int(pixel_size)))
    return font


def paint_tile(painter, rect, tool, fill, ink):
    """Quadrado arredondado com o ícone da ferramenta no centro. Um só visual no app todo; muda só a cor."""
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(fill))
    radius = rect.width() * 0.26
    painter.drawRoundedRect(rect, radius, radius)
    painter.setPen(QColor(ink))
    if tool.icon and has_icon_font():
        painter.setFont(glyph_font(rect.width() * 0.42))
        painter.drawText(rect, Qt.AlignCenter, chr(int(tool.icon, 16)))
    else:  # sem a fonte de ícones do Windows: o símbolo simples
        font = QFont(FONT_FAMILY)
        font.setBold(True)
        font.setPixelSize(max(6, int(rect.width() * 0.36)))
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, tool.glyph)


class _Animated(QWidget):
    """Base com um "nível" de 0 a 1 que anda suavemente entre repouso e destaque."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._level = 0.0
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(HOVER_MS)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.valueChanged.connect(self._on_level)

    def level(self):
        return self._level

    def _on_level(self, value):
        self._level = float(value)
        self.update()

    def animate_to(self, goal):
        self._animation.stop()
        if not animations_enabled():
            self._level = float(goal)
            self.update()
            return
        self._animation.setStartValue(float(self._level))
        self._animation.setEndValue(float(goal))
        self._animation.start()


class ToolTile(QWidget):
    """O ícone da ferramenta como peça solta (tela vazia de cada ferramenta)."""

    def __init__(self, tool, size=72, solid=True, parent=None):
        super().__init__(parent)
        self.tool = tool
        self.solid = solid
        self.setFixedSize(size, size)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        fill, ink = (COLORS['brand'], COLORS['on_brand']) if self.solid else (COLORS['tile'], COLORS['icon'])
        paint_tile(painter, QRectF(self.rect()), self.tool, fill, ink)


class ToolRow(_Animated):
    """Uma ferramenta na lista: ícone neutro, nome e descrição. Sem cartão até o mouse chegar."""

    clicked = Signal(str)

    def __init__(self, tool, parent=None):
        super().__init__(parent)
        self.tool = tool
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumHeight(76)
        self.setAccessibleName(tool.title)
        self.setAccessibleDescription(tool.description)
        # Largura só da grade (Ignored): as colunas ficam iguais e alinhadas entre as categorias.
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(68, 14, 16, 12)
        layout.setSpacing(2)
        self.title = QLabel(tool.title)
        self.title.setObjectName('rowTitle')
        self.description = QLabel(tool.description)
        self.description.setObjectName('rowDescription')
        self.description.setWordWrap(True)
        for label in (self.title, self.description):
            label.setAttribute(Qt.WA_TransparentForMouseEvents)  # o clique e o hover são da linha inteira
            layout.addWidget(label)
        layout.addStretch(1)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width, height, level = self.width(), self.height(), self.level()
        if level > 0:
            painter.setBrush(mix(COLORS['bg'], COLORS['surface'], level))
            painter.setPen(QPen(mix(COLORS['bg'], COLORS['brand'], level), 1))
            painter.drawRoundedRect(QRectF(1.5, 3.5, width - 3, height - 7), 10, 10)
        painter.setPen(QPen(mix(COLORS['line'], COLORS['bg'], level), 1))
        painter.drawLine(0, height - 1, width, height - 1)
        tile = QRectF(14, (height - 40) / 2, 40, 40)
        paint_tile(
            painter,
            tile,
            self.tool,
            mix(COLORS['tile'], COLORS['brand_soft'], level),
            mix(COLORS['icon'], COLORS['brand'], level),
        )

    def enterEvent(self, event):
        self.animate_to(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self.hasFocus():
            self.animate_to(0.0)
        super().leaveEvent(event)

    def focusInEvent(self, event):
        self.animate_to(1.0)
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self.animate_to(0.0)
        super().focusOutEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.tool.id)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit(self.tool.id)
        else:
            super().keyPressEvent(event)


class BackButton(_Animated):
    """Botão de voltar em forma de pílula (seta + "Voltar"): contorno na cor da marca, que preenche sob o mouse.
    Fica dentro do primeiro cartão de cada tela; em janelas estreitas vira só a seta."""

    clicked = Signal()
    FULL_SIZE = (104, 40)
    COMPACT_SIZE = (44, 40)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.compact = False
        self.setFixedSize(*self.FULL_SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setToolTip('Voltar para todas as ferramentas (Esc)')
        self.setAccessibleName('Voltar')  # o texto é desenhado à mão: sem isto o leitor de tela não o encontra
        self.setAccessibleDescription('Voltar para todas as ferramentas')

    def set_compact(self, compact):
        if compact != self.compact:
            self.compact = compact
            self.setFixedSize(*(self.COMPACT_SIZE if compact else self.FULL_SIZE))
            self.update()

    def invoke(self):
        self.clicked.emit()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        level = self.level()
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        painter.setPen(QPen(QColor(COLORS['brand']), 2))
        painter.setBrush(mix(COLORS['surface'], COLORS['brand'], level))
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        ink = mix(COLORS['brand'], COLORS['on_brand'], level)
        pen = QPen(ink, 2.4)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        center_y = self.height() / 2
        tip_x = 16 if not self.compact else (self.width() / 2 - 6)
        tip = QPointF(tip_x, center_y)
        painter.drawLine(tip, QPointF(tip_x + 13, center_y))
        painter.drawLine(tip, QPointF(tip_x + 6, center_y - 6))
        painter.drawLine(tip, QPointF(tip_x + 6, center_y + 6))
        if not self.compact:
            font = QFont(FONT_FAMILY)
            font.setBold(True)
            font.setPointSizeF(10)
            painter.setFont(font)
            painter.setPen(ink)
            painter.drawText(QRectF(36, 0, self.width() - 44, self.height()), Qt.AlignVCenter | Qt.AlignLeft, 'Voltar')

    def enterEvent(self, event):
        self.animate_to(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self.hasFocus():
            self.animate_to(0.0)
        super().leaveEvent(event)

    def focusInEvent(self, event):
        self.animate_to(1.0)
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self.animate_to(0.0)
        super().focusOutEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
        else:
            super().keyPressEvent(event)


class SearchBar(_Animated):
    """Busca em pílula: lupa, dica de atalho, botão de limpar e um halo de foco que surge suavemente."""

    textChanged = Signal(str)
    MAX_WIDTH = 560

    def __init__(self, placeholder='Buscar ferramenta…', parent=None):
        super().__init__(parent)
        self.setFixedHeight(50)
        self.setMinimumWidth(200)
        self.setMaximumWidth(self.MAX_WIDTH)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._focused = False
        self._hovered = False

        self.edit = QLineEdit(self)
        self.edit.setObjectName('searchEdit')  # sem borda nem fundo: a pílula é desenhada pelo próprio SearchBar
        self.edit.setPlaceholderText(placeholder)
        self.edit.installEventFilter(self)
        self.edit.setAccessibleName('Buscar ferramenta')
        self.hint = QLabel('Ctrl+F')
        self.hint.setObjectName('hint')
        self.clear_button = QToolButton()
        self.clear_button.setObjectName('searchClear')
        self.clear_button.setCursor(Qt.PointingHandCursor)
        self.clear_button.setToolTip('Limpar a busca (Esc)')
        self.clear_button.setAccessibleName('Limpar a busca')  # o texto é só um ícone
        self.clear_button.setAutoRaise(True)
        if has_icon_font():
            self.clear_button.setText(chr(0xE711))
            self.clear_button.setFont(glyph_font(12))
        else:
            self.clear_button.setText('×')
        self.clear_button.hide()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(54, 4, 18, 4)
        layout.setSpacing(8)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.hint)
        layout.addWidget(self.clear_button)

        self.edit.textChanged.connect(self._on_text)
        self.clear_button.clicked.connect(self.clear)

    def text(self):
        return self.edit.text()

    def clear(self):
        self.edit.clear()
        self.edit.setFocus()

    def focus_edit(self):
        self.edit.setFocus()
        self.edit.selectAll()

    def _on_text(self, text):
        has_text = bool(text)
        self.clear_button.setVisible(has_text)
        self.hint.setVisible(not has_text and not self._focused)
        self.textChanged.emit(text)

    def _goal(self):
        return 1.0 if self._focused else (0.4 if self._hovered else 0.0)

    def eventFilter(self, watched, event):
        if watched is self.edit:
            if event.type() == QEvent.FocusIn:
                self._focused = True
                self.hint.hide()
                self.animate_to(self._goal())
            elif event.type() == QEvent.FocusOut:
                self._focused = False
                self.hint.setVisible(not self.edit.text())
                self.animate_to(self._goal())
        return super().eventFilter(watched, event)

    def enterEvent(self, event):
        self._hovered = True
        self.animate_to(self._goal())
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.animate_to(self._goal())
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self.edit.setFocus()
        super().mousePressEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width, height, level = self.width(), self.height(), self.level()
        if level > 0.02:  # halo de foco
            painter.setPen(Qt.NoPen)
            painter.setBrush(mix(COLORS['bg'], COLORS['brand_soft'], min(1.0, level * 1.2)))
            painter.drawRoundedRect(QRectF(1, 1, width - 2, height - 2), (height - 2) / 2, (height - 2) / 2)
        pill = QRectF(4.5, 4.5, width - 9, height - 9)
        painter.setPen(QPen(mix(COLORS['line_strong'], COLORS['brand'], level), 1))
        painter.setBrush(QColor(COLORS['surface']))
        painter.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
        painter.setPen(mix(COLORS['faint'], COLORS['brand'], level))
        if has_icon_font():
            painter.setFont(glyph_font(17))
            painter.drawText(QRectF(18, 0, 28, height), Qt.AlignCenter, chr(0xE721))
        else:
            painter.drawText(QRectF(18, 0, 28, height), Qt.AlignCenter, '⌕')


class SmoothScrollArea(QScrollArea):
    """Área rolável em que a roda do mouse desliza até o destino, desacelerando no fim."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._target = 0
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(SCROLL_MS)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.valueChanged.connect(lambda value: self.verticalScrollBar().setValue(int(value)))

    def gliding(self):
        return self._animation.state() == QVariantAnimation.State.Running

    def wheelEvent(self, event):
        bar = self.verticalScrollBar()
        if bar.maximum() <= 0:
            event.ignore()
            return
        step = -event.angleDelta().y() / 120.0 * SCROLL_STEP
        if not animations_enabled():
            bar.setValue(int(bar.value() + step))
            event.accept()
            return
        # Os cliques acumulam no destino; a tela desliza até ele.
        base = self._target if self.gliding() else bar.value()
        self._target = int(max(0, min(bar.maximum(), base + step)))
        self._animation.stop()
        self._animation.setStartValue(int(bar.value()))
        self._animation.setEndValue(self._target)
        self._animation.start()
        event.accept()

    def scroll_to_top(self):
        self._animation.stop()
        self.verticalScrollBar().setValue(0)

    def sizeHint(self):
        return QSize(400, 300)
