"""Atualização pela interface: procura versão nova em segundo plano, avisa na tela inicial e cuida do download e da
instalação. A parte de rede (GitHub, download, soma SHA-256) está em rdf/core/updates.py.

- A procura automática roda alguns segundos depois de o app abrir e, com ele aberto o dia todo, uma vez por dia.
  Pode ser desligada nas Configurações. Sem internet ela falha calada (só vai para o log).
- Na cópia instalada, "Baixar e instalar" baixa o instalador, confere a soma, fecha o RDF (com as perguntas de
  sempre se houver trabalho) e roda o instalador em modo silencioso, que abre o app de novo no fim.
- Na versão portátil (ou rodando do código), o botão abre a página da versão para baixar.
"""

import logging
import subprocess
import sys
import threading

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
)

from rdf import APP_VERSION
from rdf.core import config, settings
from rdf.core.lazy import LazyModule

updates = LazyModule('rdf.core.updates')  # rede e download: carregados só na primeira procura

LOGGER = logging.getLogger('rdf')
DOWNLOAD_DIR = config.APP_DATA_DIR / 'atualizacao'
FIRST_CHECK_DELAY_MS = 6000  # depois de abrir: não disputa a abertura nem o pré-carregamento
CHECK_INTERVAL_MS = 24 * 3600 * 1000  # com o app aberto o dia todo (bandeja), procura de novo uma vez por dia


def megabytes(size):
    return f'{size / (1024 * 1024):.0f} MB'.replace('.', ',')


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)  # mensagem para o usuário; vazia quando foi cancelado
    progress = Signal(object, object)  # baixados, total (bytes)


class _Job(QRunnable):
    """Roda function(progresso) numa thread e responde pelos sinais. Nunca deixa um erro derrubar o app."""

    def __init__(self, signals, function):
        super().__init__()
        self.signals, self.function = signals, function

    def run(self):
        try:
            result = self.function(lambda done, total: self.signals.progress.emit(done, total))
        except updates.Cancelled:
            self.signals.failed.emit('')
        except updates.UpdateError as exc:
            self.signals.failed.emit(str(exc))
        except Exception as exc:
            LOGGER.exception('Erro inesperado na atualização')
            self.signals.failed.emit(f'Erro inesperado: {exc}')
        else:
            self.signals.done.emit(result)


class UpdateController(QObject):
    """Procura versões novas. available(release) traz a versão encontrada; upToDate e failed(mensagem) só respondem
    às procuras pedidas pelo usuário (a automática não incomoda ninguém se não houver novidade ou internet)."""

    available = Signal(object)
    upToDate = Signal()
    failed = Signal(str)

    def __init__(self, parent=None, check=None):
        super().__init__(parent)
        self.release = None  # a última versão nova encontrada
        self.checking = False
        self._manual = False
        self._check = check or (lambda: updates.check())
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._signals = _Signals()
        self._signals.done.connect(self._on_done)
        self._signals.failed.connect(self._on_failed)
        self._timer = QTimer(self)
        self._timer.setInterval(CHECK_INTERVAL_MS)
        self._timer.timeout.connect(self.check_automatically)

    def start(self, delay_ms=FIRST_CHECK_DELAY_MS):
        """Liga a procura automática: a primeira logo depois de abrir, depois uma vez por dia."""
        self._timer.start()
        QTimer.singleShot(delay_ms, self, self.check_automatically)

    def check_automatically(self):
        if settings.current().get('check_updates'):
            self.check(manual=False)

    def check(self, manual=True):
        """Procura em segundo plano. False se já havia uma procura em andamento (ela responde por esta também)."""
        self._manual = self._manual or manual
        if self.checking:
            return False
        self.checking = True
        self._pool.start(_Job(self._signals, lambda _progress: self._check()))
        return True

    def _on_done(self, release):
        manual, self.checking, self._manual = self._manual, False, False
        if release is not None:
            self.release = release
            self.available.emit(release)
        elif manual:
            self.upToDate.emit()

    def _on_failed(self, message):
        manual, self.checking, self._manual = self._manual, False, False
        LOGGER.info('Procura de atualização falhou: %s', message)
        if manual:
            self.failed.emit(message)


class UpdateBanner(QFrame):
    """Faixa discreta no topo da tela inicial: há versão nova. "Atualizar" abre os detalhes; o X esconde até a
    próxima vez que o RDF abrir."""

    updateRequested = Signal()
    dismissed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('updateBanner')
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 10, 10, 10)
        row.setSpacing(12)
        self.dot = QLabel()
        self.dot.setObjectName('updateDot')
        self.dot.setFixedSize(8, 8)
        row.addWidget(self.dot, 0, Qt.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        self.title = QLabel('')
        self.title.setObjectName('rowTitle')
        self.subtitle = QLabel('Melhorias e correções. A atualização leva cerca de um minuto e mantém suas escolhas.')
        self.subtitle.setObjectName('rowDescription')
        self.subtitle.setWordWrap(True)
        texts.addWidget(self.title)
        texts.addWidget(self.subtitle)
        row.addLayout(texts, 1)
        self.update_button = QPushButton('Atualizar…')
        self.update_button.setProperty('variant', 'primary')
        self.update_button.setProperty('size', 'small')
        self.update_button.setCursor(Qt.PointingHandCursor)
        self.update_button.clicked.connect(self.updateRequested)
        row.addWidget(self.update_button, 0, Qt.AlignVCenter)
        self.close_button = QToolButton()
        self.close_button.setObjectName('searchClear')
        self.close_button.setText('×')
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setToolTip('Lembrar na próxima vez que o RDF abrir')
        self.close_button.setAccessibleName('Fechar o aviso de atualização')
        self.close_button.clicked.connect(self._dismiss)
        row.addWidget(self.close_button, 0, Qt.AlignVCenter)
        self.hide()

    def show_release(self, release):
        self.title.setText(f'Nova versão do RDF: {release.version}')
        self.setAccessibleName(f'Nova versão do RDF disponível: {release.version}')
        self.show()

    def _dismiss(self):
        self.hide()
        self.dismissed.emit()


class UpdateDialog(QDialog):
    """Novidades da versão e download com progresso. Ao fechar com "Instalar agora", install_now fica True e
    installer aponta o instalador conferido: quem abriu o diálogo fecha o RDF e roda o instalador."""

    def __init__(self, release, parent=None, installed=None, download=None, folder=None):
        super().__init__(parent)
        self.release = release
        self.installed = updates.is_installed_copy() if installed is None else installed
        self.can_install = self.installed and release.can_install
        self.installer = None
        self.install_now = False
        self.state = 'idle'  # idle, downloading, ready
        self._download = download or updates.download_installer
        self._folder = folder or DOWNLOAD_DIR
        self._cancel = threading.Event()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._signals = _Signals()  # sem pai: se a janela fechar no meio, o download ainda tem onde avisar
        self._signals.done.connect(self._on_downloaded)
        self._signals.failed.connect(self._on_failed)
        self._signals.progress.connect(self._on_progress)

        self.setWindowTitle('Atualizar o RDF')
        self.setModal(True)
        self.setMinimumWidth(540)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(10)
        title = QLabel(f'Versão {release.version} disponível')
        title.setObjectName('dialogTitle')
        layout.addWidget(title)
        lead = QLabel(f'Você está usando a versão {APP_VERSION}.')
        lead.setObjectName('pageLead')
        layout.addWidget(lead)
        heading = QLabel('Novidades')
        heading.setObjectName('groupTitle')
        layout.addWidget(heading)
        self.notes = QTextBrowser()
        self.notes.setObjectName('releaseNotes')
        self.notes.setOpenExternalLinks(True)
        self.notes.setMarkdown(updates.notes_for_app(release.notes) or 'Melhorias e correções.')
        self.notes.setMinimumHeight(160)
        self.notes.setMaximumHeight(300)
        layout.addWidget(self.notes)
        self.info = QLabel(self._info_text())
        self.info.setObjectName('hint')
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        self.status.setProperty('tone', 'info')
        self.status.hide()
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.secondary = QPushButton('Agora não')
        self.secondary.clicked.connect(self._on_secondary)
        self.primary = QPushButton('Baixar e instalar' if self.can_install else 'Abrir a página da versão')
        self.primary.setProperty('variant', 'primary')
        self.primary.setDefault(True)
        self.primary.clicked.connect(self._on_primary)
        buttons.addWidget(self.secondary)
        buttons.addWidget(self.primary)
        layout.addLayout(buttons)

    def _info_text(self):
        if self.can_install:
            size = f'Download de {megabytes(self.release.installer_size)}. ' if self.release.installer_size else ''
            return (
                f'{size}O RDF fecha, instala a versão nova e abre de novo sozinho; as configurações e as favoritas '
                'continuam. O arquivo é conferido antes de instalar.'
            )
        if not self.installed:
            return 'Esta é a versão portátil (ou o código-fonte): baixe o RDF novo na página da versão.'
        return 'Esta versão não tem instalador para baixar automaticamente: baixe-o na página da versão.'

    def set_status(self, text, tone='info'):
        self.status.setText(text)
        self.status.setProperty('tone', tone)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.status.setVisible(bool(text))

    # ---- ações ---------------------------------------------------------------------------
    def _on_primary(self):
        if not self.can_install:
            QDesktopServices.openUrl(QUrl(self.release.page_url))
            self.accept()
        elif self.state == 'ready':
            self.install_now = True
            self.accept()
        elif self.state == 'idle':
            self.start_download()

    def _on_secondary(self):
        if self.state == 'downloading':
            self._cancel.set()
            self.secondary.setEnabled(False)
            self.set_status('Cancelando…')
        else:
            self.reject()

    def start_download(self):
        self.state = 'downloading'
        self._cancel.clear()
        self.primary.setEnabled(False)
        self.secondary.setText('Cancelar')
        self.secondary.setEnabled(True)
        self.progress.setValue(0)
        self.progress.show()
        self.set_status('Baixando…')
        release, folder, cancel = self.release, self._folder, self._cancel
        self._pool.start(_Job(self._signals, lambda progress: self._download(release, folder, progress, cancel.is_set)))

    def _on_progress(self, done, total):
        if total:
            self.progress.setValue(int(100 * done / total))
            self.set_status(f'Baixando… {megabytes(done)} de {megabytes(total)}')

    def _on_downloaded(self, path):
        self.installer = path
        self.state = 'ready'
        self.progress.setValue(100)
        self.secondary.setText('Depois')
        self.secondary.setEnabled(True)
        self.primary.setText('Instalar agora')
        self.primary.setEnabled(True)
        self.primary.setFocus()
        self.set_status(
            f'Pronto e conferido. Ao instalar, o RDF fecha, atualiza para a versão {self.release.version} e abre de '
            'novo sozinho.',
            'ok',
        )

    def _on_failed(self, message):
        self.state = 'idle'
        self.progress.hide()
        self.secondary.setText('Agora não')
        self.secondary.setEnabled(True)
        self.primary.setEnabled(True)
        self.primary.setText('Tentar de novo' if message else 'Baixar e instalar')
        self.set_status(message, 'error' if message else 'info')

    def reject(self):
        self._cancel.set()  # fechar a janela no meio do download o interrompe
        super().reject()

    def wait_download(self, timeout_ms=30000):
        """Espera o download terminar (testes e fechamento)."""
        return self._pool.waitForDone(timeout_ms)


def launch_installer(installer):
    """Roda o instalador como processo independente: ele continua depois que o RDF fecha."""
    command = updates.installer_command(installer)
    flags = 0
    if sys.platform == 'win32':
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(command, close_fds=True, creationflags=flags)
