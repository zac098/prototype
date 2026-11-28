"""Ícones do RDF: desenhos vetoriais próprios (SVG), no mesmo traço fino e arredondado em todo o app.

Cada ícone é desenhado numa grade de 24 x 24 e pintado na cor pedida (a do tema), então fica nítido em qualquer escala
de tela e igual em qualquer Windows, sem depender de fontes de ícones do sistema. As imagens prontas ficam guardadas
por tamanho, cor e escala da tela: desenhar de novo a lista de ferramentas não refaz nenhum ícone.
"""

import weakref

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from rdf.qt import theme
from rdf.qt.theme import COLORS

STROKE = 1.75

# Desenho de uma página com o canto dobrado: base de vários ícones de ferramentas de PDF.
_PAGE = (
    '<path d="M14 3H7.5A2.5 2.5 0 0 0 5 5.5v13A2.5 2.5 0 0 0 7.5 21h9a2.5 2.5 0 0 0 2.5-2.5V8z"/><path d="M14 3v5h5"/>'
)

# Corpo de cada ícone (dentro do <svg>). "@" vira a cor: use fill="@" no que for preenchido.
SHAPES = {
    # ---- ferramentas -----------------------------------------------------------------------
    'renamer': (
        '<path d="M14 3H7.5A2.5 2.5 0 0 0 5 5.5v13A2.5 2.5 0 0 0 7.5 21H11"/><path d="M14 3v5h5v2.5"/>'
        '<path d="M8.5 12h4M8.5 15.5h2"/>'
        '<path d="M18.6 12.9a1.6 1.6 0 0 1 2.3 2.3L15.7 20.4l-3 .7.7-3z"/>'
    ),
    'merge': (
        '<path d="M9 6.5V5.5A2.5 2.5 0 0 1 11.5 3h5.6L20 5.9v9.6a2.5 2.5 0 0 1-2.5 2.5H16"/>'
        '<rect x="4" y="7" width="12" height="14" rx="2.5"/><path d="M10 11v6M7 14h6"/>'
    ),
    'split': (
        '<path d="M9.5 4H6.5A2.5 2.5 0 0 0 4 6.5v11A2.5 2.5 0 0 0 6.5 20h3"/>'
        '<path d="M14.5 4h3A2.5 2.5 0 0 1 20 6.5v11a2.5 2.5 0 0 1-2.5 2.5h-3"/>'
        '<path d="M12 3v2.5M12 8.5v2.5M12 13v2.5M12 18.5V21"/>'
    ),
    'remove': _PAGE + '<path d="M9 14.5h6"/>',
    'extract': (
        '<path d="M12 3H7.5A2.5 2.5 0 0 0 5 5.5v13A2.5 2.5 0 0 0 7.5 21h9a2.5 2.5 0 0 0 2.5-2.5V14"/>'
        '<path d="M15 3h6v6M21 3l-8.5 8.5"/>'
    ),
    'organize': (
        '<rect x="3.5" y="3.5" width="9" height="7.5" rx="2"/><rect x="3.5" y="13" width="9" height="7.5" rx="2"/>'
        '<path d="M17.5 5v14M15 7.5 17.5 5 20 7.5M15 16.5l2.5 2.5 2.5-2.5"/>'
    ),
    'compress': '<path d="M4 14h6v6M3.5 20.5 10 14M20 10h-6V4M20.5 3.5 14 10"/>',
    'repair': (
        '<path d="M14.8 3.6a5 5 0 0 0-5.6 6.8L3.8 15.8a1.9 1.9 0 0 0 2.7 2.7l5.4-5.4a5 5 0 0 0 6.8-5.6l-2.9 2.9'
        '-2.6-.4-.4-2.6z"/>'
    ),
    'ocr': (
        '<path d="M4 8V5.5A1.5 1.5 0 0 1 5.5 4H8M16 4h2.5A1.5 1.5 0 0 1 20 5.5V8M20 16v2.5a1.5 1.5 0 0 1-1.5 1.5H16'
        'M8 20H5.5A1.5 1.5 0 0 1 4 18.5V16"/><path d="M8.5 9h7M8.5 12h7M8.5 15h4.5"/>'
    ),
    'images-to-pdf': (
        '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><circle cx="9" cy="10" r="1.6"/>'
        '<path d="m20.5 15.5-4.4-4.4L7 19.5"/>'
    ),
    'pdf-to-images': _PAGE + '<circle cx="10" cy="12.5" r="1.3"/><path d="m16 18-2.6-2.6L9 19.5"/>',
    'pdf-to-text': _PAGE + '<path d="M8.5 13h7M8.5 16.5h5"/>',
    'rotate': '<path d="M20.5 12a8.5 8.5 0 1 1-2.5-6l2.5 2.5"/><path d="M20.5 3.5v5h-5"/>',
    'crop': '<path d="M6.5 2.5v13a2 2 0 0 0 2 2h13M17.5 21.5v-13a2 2 0 0 0-2-2h-13"/>',
    'page-numbers': '<path d="M5 9h14M5 15h14M10.5 4 9 20M15 4l-1.5 16"/>',
    'watermark': '<path d="M12 3.2s-6.3 6.6-6.3 11.1a6.3 6.3 0 0 0 12.6 0C18.3 9.8 12 3.2 12 3.2z"/><path d="M9 14.5a3 3 0 0 0 3 3"/>',
    'protect': '<rect x="4.5" y="10.5" width="15" height="10" rx="2.5"/><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3M12 14.5v2"/>',
    'unlock': '<rect x="4.5" y="10.5" width="15" height="10" rx="2.5"/><path d="M8 10.5V7.5a4 4 0 0 1 7.6-1.8M12 14.5v2"/>',
    'redact': _PAGE + '<path d="M8.5 13h7M8.5 17h4.5" stroke-width="3"/>',
    'metadata': (
        '<path d="M3.5 11.6V5A1.5 1.5 0 0 1 5 3.5h6.6a1.5 1.5 0 0 1 1.1.4l7.4 7.4a1.5 1.5 0 0 1 0 2.1l-6.6 6.6'
        'a1.5 1.5 0 0 1-2.1 0l-7.4-7.4a1.5 1.5 0 0 1-.5-1z"/><circle cx="8" cy="8" r="1.4"/>'
    ),
    'grayscale': '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5a8.5 8.5 0 0 1 0 17z" fill="@"/>',
    'fit-paper': (
        '<rect x="4" y="3" width="16" height="18" rx="2.5"/><path d="M8.5 15.5l7-7M11 8.5h4.5V13M13 15.5H8.5V11"/>'
    ),
    # ---- interface -----------------------------------------------------------------------
    'search': '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.4-4.4"/>',
    'theme': '<path d="M19.5 14.6A8 8 0 0 1 9.4 4.5a8 8 0 1 0 10.1 10.1z"/>',
    'settings': (
        '<path d="M4 7h9M17 7h3M4 12h3M11 12h9M4 17h11M19 17h1"/>'
        '<circle cx="15" cy="7" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="17" r="2"/>'
    ),
    'help': (
        '<circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.6a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1.1 1-1.1 1.7v.5"/>'
        '<path d="M12 16.8v.2"/>'
    ),
    'back': '<path d="M19 12H5M11 18l-6-6 6-6"/>',
    'close': '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    'add': '<path d="M12 5v14M5 12h14"/>',
    'up': '<path d="M12 19V5M6 11l6-6 6 6"/>',
    'down': '<path d="M12 5v14M6 13l6 6 6-6"/>',
    'trash': (
        '<path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l.8 12a2 2 0 0 0 2 1.9h5.4a2 2 0 0 0 2-1.9l.8-12M10 11v6M14 11v6"/>'
    ),
    'folder': '<path d="M3.5 7.5A2.5 2.5 0 0 1 6 5h3.5l2 2.2H18a2.5 2.5 0 0 1 2.5 2.5v7.8A2.5 2.5 0 0 1 18 20H6a2.5 2.5 0 0 1-2.5-2.5z"/>',
    'upload': '<path d="M12 15.5V4M7 9l5-5 5 5M5 15v2.5A2.5 2.5 0 0 0 7.5 20h9a2.5 2.5 0 0 0 2.5-2.5V15"/>',
    'download': '<path d="M12 4v11.5M7 10.5l5 5 5-5M5 15v2.5A2.5 2.5 0 0 0 7.5 20h9a2.5 2.5 0 0 0 2.5-2.5V15"/>',
    'printer': (
        '<path d="M7 9V3.5h10V9M7 17H5.5A2 2 0 0 1 3.5 15v-4A2 2 0 0 1 5.5 9h13a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2H17"/>'
        '<rect x="7" y="13.5" width="10" height="7" rx="1"/>'
    ),
    'sort': '<path d="M4 7h10M4 12h7M4 17h4M18 5v14M15 16l3 3 3-3"/>',
    'shield': '<path d="M12 3.5 5 6.2v5.3c0 4.3 3 7.6 7 9 4-1.4 7-4.7 7-9V6.2z"/><path d="m9.2 12.2 2 2 3.8-4"/>',
    'check': '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
}


def svg(name, color):
    """O SVG completo do ícone name na cor dada."""
    body = SHAPES[name].replace('"@"', f'"{color}"')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
        f'stroke-width="{STROKE}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )


_renderers = {}
_pixmaps = {}


def _renderer(name, color):
    key = (name, color)
    if key not in _renderers:
        _renderers[key] = QSvgRenderer(QByteArray(svg(name, color).encode('utf-8')))
    return _renderers[key]


def has(name):
    return name in SHAPES


def paint(painter, rect, name, color):
    """Desenha o ícone dentro de rect (QRectF) com o pintor de quem chama."""
    _renderer(name, QColor(color).name()).render(painter, QRectF(rect))


def pixmap(name, size, color, device_ratio=1.0):
    """O ícone como QPixmap quadrado de size pixels lógicos, nítido na escala da tela (device_ratio)."""
    color = QColor(color).name()
    ratio = max(1.0, float(device_ratio or 1.0))
    key = (name, int(size), color, ratio)
    cached = _pixmaps.get(key)
    if cached is not None:
        return cached
    side = max(1, round(size * ratio))
    image = QPixmap(side, side)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    _renderer(name, color).render(painter, QRectF(0, 0, side, side))
    painter.end()
    image.setDevicePixelRatio(ratio)
    _pixmaps[key] = image
    return image


def icon(name, color, size=20, device_ratio=2.0):
    """QIcon para botões (desenhado já em alta resolução: fica nítido também em telas com escala de 150-200%)."""
    result = QIcon()
    result.addPixmap(pixmap(name, size, color, device_ratio))
    return result


def icon_size(size=18):
    return QSize(size, size)


_themed = weakref.WeakKeyDictionary()  # botão -> (ícone, cor do tema, tamanho)
_listening = []


def set_themed_icon(button, name, token='icon', size=18):
    """Põe o ícone name no botão, na cor token do tema; quando o tema troca, o ícone é redesenhado na cor nova."""
    _themed[button] = (name, token, size)
    _apply(button)
    if not _listening:
        theme.manager().changed.connect(_refresh_all)
        _listening.append(True)


def _apply(button):
    name, token, size = _themed[button]
    button.setIcon(icon(name, COLORS[token], size))
    button.setIconSize(icon_size(size))


def _refresh_all(*_args):
    for button in list(_themed.keys()):
        try:
            _apply(button)
        except RuntimeError:  # o botão já foi apagado pelo Qt
            _themed.pop(button, None)
