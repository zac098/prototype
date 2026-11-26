"""Abre o RDF no novo visual (Qt): python -m rdf.qt"""

import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from rdf.core.autostart import BACKGROUND_FLAG
from rdf.core.config import app_base_dir, init, sweep_stale_data
from rdf.qt.single_instance import InstanceServer, files_from_args, send_to_running
from rdf.qt.theme import FONT_FAMILY, build_stylesheet
from rdf.qt.tray import TrayController
from rdf.qt.window import MainWindow


def create_app(argv=None):
    """QApplication com a fonte e o tema do RDF. Usado também pelos testes."""
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName('RDF')
    app.setFont(QFont(FONT_FAMILY, 10))
    app.setStyleSheet(build_stylesheet())
    return app


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
    if first:  # só o primeiro processo é dono das pastas temporárias
        sweep_stale_data()
    app.setQuitOnLastWindowClosed(False)  # quem encerra é a janela ao fechar de verdade (ou o "Sair" da bandeja)
    window = MainWindow()
    tray = TrayController(window) if TrayController.available() else None
    window.attach_tray(tray)
    server.filesReceived.connect(window.receive_print_files)
    if files or not (background and tray is not None):  # sem bandeja não há como reabrir: mostra a janela
        window.show()
    if files:
        window.receive_print_files(files)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
