"""Miniaturas de páginas desenhadas em segundo plano: a janela nunca trava abrindo um PDF grande.

Um pedido (request) desenha as páginas pedidas, uma de cada vez, numa thread separada, e cada miniatura chega pelo
sinal ready na thread da janela. Um pedido novo (ou cancel) faz o anterior parar na próxima página: trocar de
arquivo no meio não gasta tempo desenhando o arquivo velho. O PyMuPDF é usado sob a trava global (ele não aceita duas
threads ao mesmo tempo), página por página, para não segurar a ferramenta que estiver rodando.
"""

import logging
import threading

import fitz
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage

from rdf.core.fitz_lock import FITZ_LOCK

LOGGER = logging.getLogger('rdf')


def render_page(document, index, width, height=None):
    """A página como QImage cabendo em width x height (só width: mantém a proporção pela largura)."""
    page = document[index]
    rect = page.rect
    zoom = width / max(1.0, rect.width)
    if height:
        zoom = min(zoom, height / max(1.0, rect.height))
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()


class _Signals(QObject):
    ready = Signal(int, str, int, QImage)  # pedido, caminho, página, imagem
    failed = Signal(int, str, str)  # pedido, caminho, motivo
    done = Signal(int)


class _Task(QRunnable):
    def __init__(self, signals, state, request, path, pages, width, height):
        super().__init__()
        self.signals, self.state = signals, state
        self.request, self.path, self.pages, self.width, self.height = request, path, pages, width, height

    def current(self):
        return self.state['request'] == self.request

    def run(self):
        document = None
        try:
            with FITZ_LOCK:
                document = fitz.open(self.path)
                total = document.page_count
            for index in self.pages:
                if not self.current():
                    return
                if not 0 <= index < total:
                    continue
                with FITZ_LOCK:
                    image = render_page(document, index, self.width, self.height)
                self.signals.ready.emit(self.request, self.path, index, image)
        except Exception as exc:  # arquivo apagado, corrompido ou protegido: a tela mostra um aviso
            LOGGER.warning('Miniatura indisponível de %s: %s', self.path, exc)
            self.signals.failed.emit(self.request, self.path, str(exc)[:120])
        finally:
            if document is not None:
                with FITZ_LOCK:
                    document.close()
            self.signals.done.emit(self.request)


class ThumbnailLoader(QObject):
    """Desenha miniaturas fora da thread da janela. ready(caminho, página, QImage) chega só do pedido mais recente."""

    ready = Signal(str, int, QImage)
    failed = Signal(str, str)
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = {'request': 0}
        self._lock = threading.Lock()
        # Sem pai: o objeto dos sinais vive enquanto alguma tarefa ainda o usa, mesmo se a tela já foi apagada.
        self._signals = _Signals()
        self._signals.ready.connect(self._on_ready)
        self._signals.failed.connect(self._on_failed)
        self._signals.done.connect(self._on_done)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        # Ao apagar a tela, a tarefa em curso para na próxima página (o pool espera por ela ao ser destruído).
        self.destroyed.connect(lambda *_args, state=self._state: state.__setitem__('request', -1))

    @property
    def request_id(self):
        return self._state['request']

    def request(self, path, pages, width, height=None):
        """Desenha as páginas (índices) de path. Cancela o pedido anterior. Devolve o número do pedido."""
        with self._lock:
            self._state['request'] += 1
            request = self._state['request']
        self.pool.start(_Task(self._signals, self._state, request, str(path), list(pages), width, height))
        return request

    def cancel(self):
        with self._lock:
            self._state['request'] += 1

    def wait(self, milliseconds=3000):
        return self.pool.waitForDone(milliseconds)

    def _on_ready(self, request, path, index, image):
        if request == self._state['request']:
            self.ready.emit(path, index, image)

    def _on_failed(self, request, path, reason):
        if request == self._state['request']:
            self.failed.emit(path, reason)

    def _on_done(self, request):
        if request == self._state['request']:
            self.finished.emit()
