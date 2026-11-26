"""Prévia de página do renomeador: visualizador com zoom e carregamento em segundo plano."""

import logging

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QGraphicsScene, QGraphicsView

from rdf.core.imaging import render_pdf_page
from rdf.qt.theme import COLORS

LOGGER = logging.getLogger('rdf')
MAX_ZOOM = 4.0
ZOOM_STEP = 1.2
WHEEL_ZOOM = 1.15


class PreviewView(QGraphicsView):
    """Mostra uma página. Começa ajustada à largura; zoom pelos botões, Ctrl+roda ou Ctrl +/-; arrastar move."""

    zoomChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setFrameShape(QFrame.NoFrame)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setBackgroundBrush(QBrush(QColor('#e8efef')))
        self.setStyleSheet('QGraphicsView { border: 1px solid #c7d7d6; border-radius: 8px; }')
        self._pixmap_item = None
        self.zoom = 1.0
        self.min_zoom = 1.0
        self.fitted = True

    def has_image(self):
        return self._pixmap_item is not None

    def clear(self):
        self.scene().clear()
        self._pixmap_item = None
        self.zoom = self.min_zoom = 1.0
        self.fitted = True
        self.resetTransform()
        self.zoomChanged.emit(1.0)

    def set_message(self, text, error=False):
        self.clear()
        item = self.scene().addText(text)
        item.setDefaultTextColor(QColor(COLORS['danger'] if error else COLORS['faint']))
        item.setPos(12, 12)
        self.scene().setSceneRect(item.boundingRect().translated(12, 12))

    def set_image(self, array):
        """array: imagem RGB do OpenCV/numpy (altura x largura x 3)."""
        height, width = array.shape[:2]
        image = QImage(array.data, width, height, 3 * width, QImage.Format_RGB888).copy()
        self.clear()
        self._pixmap_item = self.scene().addPixmap(QPixmap.fromImage(image))
        self._pixmap_item.setTransformationMode(Qt.SmoothTransformation)
        self.scene().setSceneRect(self._pixmap_item.boundingRect())
        self.fit()

    def _fit_scale(self):
        if not self._pixmap_item:
            return 1.0
        rect = self._pixmap_item.boundingRect()
        available = max(1, self.viewport().width() - 2)
        return max(0.01, available / rect.width())

    def fit(self):
        """Ajusta a página à largura da área (a página rola na vertical)."""
        if not self._pixmap_item:
            return
        self.min_zoom = self._fit_scale()
        self.fitted = True
        self._apply(self.min_zoom)
        self.verticalScrollBar().setValue(0)
        self.horizontalScrollBar().setValue(0)

    def zoom_by(self, factor):
        if not self._pixmap_item:
            return
        self.min_zoom = self._fit_scale()
        target = max(self.min_zoom, min(MAX_ZOOM, self.zoom * factor))
        self.fitted = target <= self.min_zoom * 1.02
        self._apply(target)

    def _apply(self, zoom):
        self.zoom = zoom
        self.resetTransform()
        self.scale(zoom, zoom)
        self.zoomChanged.emit(zoom)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            self.zoom_by(WHEEL_ZOOM if event.angleDelta().y() > 0 else 1 / WHEEL_ZOOM)
            event.accept()
        else:
            super().wheelEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._pixmap_item and self.fitted:
            self.fit()
        elif self._pixmap_item:
            self.min_zoom = self._fit_scale()
            if self.zoom < self.min_zoom:
                self._apply(self.min_zoom)


class _Signals(QObject):
    loaded = Signal(str, int, object, int, int)  # caminho, página, imagem, total de páginas, pedido
    failed = Signal(object, int)  # erro, pedido


class _RenderTask(QRunnable):
    def __init__(self, signals, path, page_index, request):
        super().__init__()
        self.signals, self.path, self.page_index, self.request = signals, path, page_index, request

    def run(self):
        # Só renderiza e avisa por sinal: quem mexe na tela é a thread principal.
        try:
            image, total = render_pdf_page(self.path, self.page_index)
            self.signals.loaded.emit(self.path, self.page_index, image, total, self.request)
        except Exception as exc:
            LOGGER.exception('Falha ao carregar página %s de %s', self.page_index + 1, self.path)
            self.signals.failed.emit(exc, self.request)


class PageLoader(QObject):
    """Renderiza páginas em segundo plano. O resultado chega pelos sinais loaded e failed."""

    loaded = Signal(str, int, object, int, int)
    failed = Signal(object, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._signals = _Signals(self)
        self._signals.loaded.connect(self.loaded)
        self._signals.failed.connect(self.failed)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)

    def request(self, path, page_index, request):
        self.pool.start(_RenderTask(self._signals, path, page_index, request))

    def wait(self, milliseconds=3000):
        return self.pool.waitForDone(milliseconds)
