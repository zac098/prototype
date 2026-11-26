"""Uma só janela do RDF por vez, e recebimento de arquivos vindos do menu do botão direito.

O Explorer abre o programa uma vez por arquivo selecionado ("Imprimir com o RDF" em cada PDF). Para isso virar uma
tela só, o primeiro processo escuta num canal local do usuário e os seguintes entregam a ele os arquivos e saem.
Quem consegue o arquivo de trava é o primeiro. A trava é o que garante uma só janela: no Windows o Qt deixa dois
processos escutarem no mesmo nome de canal, então o canal sozinho não serve para decidir quem é o primeiro.
"""

import getpass
import json
import logging
import re
import time
from pathlib import Path

from PySide6.QtCore import QDir, QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from rdf.pdftools import sources

LOGGER = logging.getLogger('rdf')
PRINT_FLAG = '--imprimir'
CONNECT_TIMEOUT_MS = 3000


def server_name():
    """Um nome por usuário do Windows, para duas contas abertas ao mesmo tempo não se misturarem."""
    user = re.sub(r'[^A-Za-z0-9_.-]', '_', getpass.getuser() or 'usuario')
    return f'RDF-{user}'


def files_from_args(argv):
    """Os arquivos que vêm depois de --imprimir na linha de comando: PDF, imagens, texto, Office... (os de outros
    formatos e os que não existem são ignorados)."""
    args = list(argv[1:])
    if PRINT_FLAG not in args:
        return []
    found = []
    for raw in args[args.index(PRINT_FLAG) + 1 :]:
        path = Path(raw)
        if sources.is_supported(path) and path.is_file():
            found.append(str(path.resolve()))
    return found


def send_to_running(files, name=None, timeout_ms=CONNECT_TIMEOUT_MS):
    """Entrega os arquivos à janela que já está aberta. True se ela recebeu.

    Tenta de novo por alguns segundos: o primeiro processo pode ter acabado de abrir e ainda não estar escutando."""
    socket = QLocalSocket()
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        socket.connectToServer(name or server_name())
        if socket.waitForConnected(min(500, timeout_ms)):
            break
        if time.monotonic() >= deadline:
            return False
        socket.abort()
        time.sleep(0.05)
    socket.write(json.dumps({'files': list(files)}).encode('utf-8'))
    ok = socket.waitForBytesWritten(timeout_ms)
    socket.disconnectFromServer()
    if socket.state() != QLocalSocket.UnconnectedState:
        socket.waitForDisconnected(timeout_ms)
    return ok


class InstanceServer(QObject):
    """Escuta os outros processos do RDF; cada pedido vira o sinal filesReceived (lista, possivelmente vazia)."""

    filesReceived = Signal(list)

    def __init__(self, name=None, parent=None):
        super().__init__(parent)
        self.name = name or server_name()
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.UserAccessOption)
        self._server.newConnection.connect(self._on_connection)
        self._buffers = {}
        self.listening = False  # False depois do listen(): a trava é nossa, mas o canal não abriu
        self._lock = QLockFile(str(Path(QDir.tempPath()) / f'{self.name}.lock'))
        self._lock.setStaleLockTime(
            0
        )  # sem prazo: só vale a checagem do processo (se ele não existe mais, a trava é velha)

    def listen(self):
        """True se este processo é o primeiro: pegou a trava e passa a escutar os outros."""
        if not self._lock.tryLock(0):
            return False
        QLocalServer.removeServer(self.name)  # sobra de um RDF que travou (fora do Windows o canal é um arquivo)
        self.listening = self._server.listen(self.name)
        if not self.listening:
            LOGGER.warning(
                'Canal local %s não abriu (%s): arquivos do botão direito não chegarão a esta janela',
                self.name,
                self._server.errorString(),
            )
        return True

    def close(self):
        self._server.close()
        self._lock.unlock()

    def _on_connection(self):
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            self._buffers[socket] = b''
            socket.readyRead.connect(
                lambda s=socket: self._buffers.__setitem__(s, self._buffers[s] + bytes(s.readAll()))
            )
            socket.disconnected.connect(lambda s=socket: self._finish(s))

    def _finish(self, socket):
        if socket not in self._buffers:  # o pedido já foi tratado
            return
        data = self._buffers.pop(socket) + bytes(socket.readAll())
        socket.deleteLater()
        try:
            files = [str(item) for item in json.loads(data.decode('utf-8')).get('files', [])]
        except (ValueError, AttributeError):
            files = []
        self.filesReceived.emit(files)
