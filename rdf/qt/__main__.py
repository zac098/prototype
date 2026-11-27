"""Abre o RDF no novo visual (Qt): python -m rdf.qt"""

import importlib
import logging
import sys
import threading

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from rdf import APP_VERSION
from rdf.core import settings
from rdf.core.autostart import BACKGROUND_FLAG
from rdf.core.config import SETTINGS_FILE, app_base_dir, init, sweep_stale_data
from rdf.qt import errors, theme
from rdf.qt.single_instance import InstanceServer, files_from_args, send_to_running
from rdf.qt.theme import FONT_FAMILY
from rdf.qt.tray import TrayController
from rdf.qt.window import MainWindow


def create_app(argv=None):
    """QApplication com a fonte e o tema do RDF. Usado também pelos testes."""
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName('RDF')
    app.setApplicationVersion(APP_VERSION)
    app.setStyle('Fusion')  # segue a paleta do tema (claro ou escuro) também no que a folha de estilo não cobre
    app.setFont(QFont(FONT_FAMILY, 10))
    theme.apply(app, settings.current().get('theme'))
    return app


TRAY_WAIT_SECONDS = 45  # no login, a área de notificação do Windows pode demorar a aparecer
LOGGER = logging.getLogger('rdf')

# O que as ferramentas usam e a tela inicial não: carregado em segundo plano logo depois que a janela aparece, para a
# primeira ferramenta abrir sem esperar. Só módulos sem Qt (as telas continuam sendo criadas no fio principal).
PRELOAD_MODULES = ('fitz', 'PIL.Image', 'numpy', 'cv2', 'pytesseract', 'rdf.pdftools.sources', 'rdf.core.ocr')
PRELOAD_DELAY_MS = 800  # depois da primeira pintura da janela
PRELOAD_DELAY_BACKGROUND_MS = 15000  # no início automático: espera o Windows terminar de abrir os outros programas


def preload_in_background(modules=PRELOAD_MODULES):
    """Importa os módulos pesados numa thread à parte. Um que falhar aqui falha de novo, com a mensagem certa, quando
    a ferramenta for usada; por isso o erro só vai para o log."""

    def load():
        for name in modules:
            try:
                importlib.import_module(name)
            except Exception:
                LOGGER.warning('Pré-carregamento de %s falhou', name, exc_info=True)

    thread = threading.Thread(target=load, name='rdf-preload', daemon=True)
    thread.start()
    return thread


def wait_for_tray(window, seconds=TRAY_WAIT_SECONDS, interval_ms=1000):
    """Início automático sem bandeja ainda: espera ela aparecer (logo depois do login o Explorer pode não estar
    pronto). Se aparecer, o RDF fica escondido nela, como pedido; se não, mostra a janela, o único jeito de voltar."""

    def check(remaining):
        if window.tray is not None:
            return
        if TrayController.available():
            window.attach_tray(TrayController(window))
        elif remaining <= 0:
            window.show()
        else:
            QTimer.singleShot(interval_ms, window, lambda: check(remaining - 1))

    check(seconds)


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    app = create_app(argv)
    files = files_from_args(argv)  # vindos de "Imprimir com o RDF" (botão direito) ou de "Enviar para"
    background = BACKGROUND_FLAG in argv  # início automático com o Windows: fica escondido na bandeja
    server = InstanceServer()
    first = server.listen()
    if not first:
        # Já existe um RDF aberto: entrega a ele os arquivos (ou só pede para aparecer) e sai, sem abrir outra janela.
        if background and not files:
            return 0  # início automático com ele já aberto: não há nada a mostrar
        if send_to_running(files):
            return 0
    init(app_base_dir())  # pastas de dados, log e Tesseract: igual ao app atual
    errors.install()  # daqui em diante, nenhum erro some calado
    theme.apply(app, settings.load(SETTINGS_FILE).get('theme'))
    if first:  # só o primeiro processo é dono das pastas temporárias
        sweep_stale_data()
    app.setQuitOnLastWindowClosed(False)  # quem encerra é a janela ao fechar de verdade (ou o "Sair" da bandeja)
    window = MainWindow()
    tray = TrayController(window) if TrayController.available() else None
    window.attach_tray(tray)
    server.filesReceived.connect(window.receive_print_files)
    if files or not background:
        window.show()
    elif tray is None:  # início automático antes de a bandeja existir: espera por ela antes de mostrar a janela
        wait_for_tray(window)
    if files:
        window.receive_print_files(files)
    QTimer.singleShot(PRELOAD_DELAY_BACKGROUND_MS if background else PRELOAD_DELAY_MS, preload_in_background)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
