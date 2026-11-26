"""Mantém a janela viva durante trabalhos longos feitos na thread da interface (importar, exportar, adicionar).

Sem isto, o Windows marca o app como "Não está respondendo" enquanto converte dezenas de arquivos. Os eventos de
teclado e mouse ficam de fora (ExcludeUserInputEvents): o usuário não consegue clicar em outro botão no meio do
trabalho, mas a janela se redesenha e o Windows vê que o app está vivo.
"""

import time

from PySide6.QtCore import QEventLoop
from PySide6.QtWidgets import QApplication

MIN_INTERVAL = 0.05  # segundos entre uma troca de eventos e a próxima


class Responsive:
    """Chame pulse() a cada passo do trabalho; ele só troca eventos de tempos em tempos."""

    def __init__(self, interval=MIN_INTERVAL):
        self.interval = interval
        self._last = 0.0

    def pulse(self):
        now = time.monotonic()
        if now - self._last >= self.interval:
            self._last = now
            QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
