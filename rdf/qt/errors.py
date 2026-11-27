"""Erros inesperados nunca somem calados.

Com o pythonw (sem console) e no executável empacotado, uma exceção dentro de um clique ou de um timer do Qt ia para
lugar nenhum: o botão simplesmente "não fazia nada". O gancho instalado aqui grava o erro completo no log e mostra um
aviso curto, com o caminho do log. O aviso aparece no máximo uma vez a cada poucos segundos (um erro repetido num
timer não vira uma enxurrada de janelas) e só na thread da janela; erros de outras threads vão só para o log.
"""

import logging
import sys
import threading
import time

from rdf.core import config

LOGGER = logging.getLogger('rdf')
MIN_INTERVAL = 5.0  # segundos entre dois avisos na tela

_state = {'last': 0.0, 'showing': False}


def log_file():
    return config.LOG_DIR / config.LOG_FILE_NAME


def report(exc_type, exc, tb, show=True):
    """Grava o erro no log e, se der, avisa o usuário. Devolve True se mostrou o aviso."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return False
    if issubclass(exc_type, SystemExit):
        return False
    LOGGER.critical('Erro inesperado', exc_info=(exc_type, exc, tb))
    if not show or threading.current_thread() is not threading.main_thread():
        return False
    now = time.monotonic()
    if _state['showing'] or now - _state['last'] < MIN_INTERVAL:
        return False
    _state['last'] = now
    return _show(exc)


def _show(exc):
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QApplication, QMessageBox

    if QApplication.instance() is None:
        return False
    _state['showing'] = True
    try:
        box = QMessageBox(QMessageBox.Critical, 'Erro inesperado', '', QMessageBox.NoButton)
        box.setText('Aconteceu um erro inesperado. O RDF continua aberto, mas a última ação pode não ter terminado.')
        box.setInformativeText(
            f'{type(exc).__name__}: {str(exc)[:300]}\n\nOs detalhes foram gravados em:\n{log_file()}'
        )
        logs = box.addButton('Abrir pasta do log', QMessageBox.ActionRole)
        box.addButton('Fechar', QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is logs:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(config.LOG_DIR)))
        return True
    finally:
        _state['showing'] = False


def install():
    """Liga o gancho para a thread da janela e para as threads de trabalho."""
    sys.excepthook = report
    threading.excepthook = lambda args: report(args.exc_type, args.exc_value, args.exc_traceback, show=False)
