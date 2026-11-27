"""Uma só janela do RDF e recebimento de PDFs pelo menu do botão direito ("Imprimir com o RDF" / "Enviar para")."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import _source  # coloca a raiz do projeto no sys.path

HAS_QT = importlib.util.find_spec('PySide6') is not None

if HAS_QT:
    from rdf.qt import __main__ as entry
    from rdf.qt.__main__ import create_app
    from rdf.qt.single_instance import PRINT_FLAG, InstanceServer, files_from_args, send_to_running


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class ArgumentsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def touch(self, name):
        path = self.tmp / name
        path.write_bytes(b'%PDF-1.4')
        return str(path)

    def test_without_the_flag_nothing_is_received(self):
        self.assertEqual(files_from_args(['RDF.exe']), [])
        self.assertEqual(files_from_args(['RDF.exe', self.touch('a.pdf')]), [])

    def test_the_supported_files_after_the_flag_are_returned_and_the_rest_ignored(self):
        a, b = self.touch('a.pdf'), self.touch('B.PDF')
        photo, notes, word = self.touch('foto.jpg'), self.touch('notas.txt'), self.touch('oficio.docx')
        program, archive = self.touch('instalador.exe'), self.touch('lote.zip')
        missing = str(self.tmp / 'sumiu.pdf')
        found = files_from_args(['RDF.exe', PRINT_FLAG, a, photo, program, missing, notes, archive, word, b])
        self.assertEqual([Path(p).name for p in found], ['a.pdf', 'foto.jpg', 'notas.txt', 'oficio.docx', 'B.PDF'])

    def test_the_flag_alone_is_just_a_request_to_show_the_window(self):
        self.assertEqual(files_from_args(['RDF.exe', PRINT_FLAG]), [])


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app([])

    def setUp(self):
        self.name = f'RDF-teste-{os.getpid()}-{time.monotonic_ns()}'
        self.server = InstanceServer(self.name)
        self.assertTrue(self.server.listen())
        self.addCleanup(self.server.close)
        self.received = []
        self.server.filesReceived.connect(self.received.append)

    def send_from_other_process(self, files, name=None):
        """Como o Explorer faz: outro processo do RDF entrega os arquivos (aqui, um Python à parte)."""
        code = ';'.join(
            [
                'import os, sys',
                "os.environ['QT_QPA_PLATFORM'] = 'offscreen'",
                f'sys.path.insert(0, {str(_source.ROOT)!r})',
                'from rdf.qt.__main__ import create_app',
                'create_app([])',
                'from rdf.qt.single_instance import send_to_running',
                f'sys.exit(0 if send_to_running({list(files)!r}, {name or self.name!r}, 3000) else 1)',
            ]
        )
        return subprocess.Popen([sys.executable, '-c', code], stderr=subprocess.PIPE)

    def finish(self, *processes):
        deadline = time.monotonic() + 60
        while any(p.poll() is None for p in processes) and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        for process in processes:
            process.stderr.close()
        return [p.returncode for p in processes]

    def wait_for(self, count):
        deadline = time.monotonic() + 5
        while len(self.received) < count and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)

    def test_only_the_first_process_gets_to_listen(self):
        second = InstanceServer(self.name)
        self.assertFalse(second.listen())

    def test_files_sent_by_another_process_reach_the_window(self):
        self.assertEqual(self.finish(self.send_from_other_process(['C:/a.pdf', 'C:/b.pdf'])), [0])
        self.wait_for(1)
        self.assertEqual(self.received, [['C:/a.pdf', 'C:/b.pdf']])

    def test_several_launches_in_a_row_each_arrive(self):
        launches = [self.send_from_other_process([f'C:/{number}.pdf']) for number in range(4)]  # ao mesmo tempo
        self.assertEqual(self.finish(*launches), [0, 0, 0, 0])
        self.wait_for(4)
        self.assertEqual(sorted(item[0] for item in self.received), [f'C:/{n}.pdf' for n in range(4)])

    def test_an_empty_request_still_arrives_so_the_window_can_come_to_the_front(self):
        self.assertEqual(self.finish(self.send_from_other_process([])), [0])
        self.wait_for(1)
        self.assertEqual(self.received, [[]])

    def test_garbage_is_ignored_without_breaking_the_server(self):
        from PySide6.QtNetwork import QLocalSocket

        socket = QLocalSocket()
        socket.connectToServer(self.name)
        self.assertTrue(socket.waitForConnected(2000))
        socket.write(b'isto nao e json')
        socket.waitForBytesWritten(2000)
        socket.disconnectFromServer()
        self.wait_for(1)
        self.assertEqual(self.received, [[]])
        self.assertEqual(self.finish(self.send_from_other_process(['C:/x.pdf'])), [0])
        self.wait_for(2)
        self.assertEqual(self.received[-1], ['C:/x.pdf'])

    def test_many_requests_in_a_row_never_crash_the_window(self):
        """Regressão: o servidor guardava o objeto Python de cada conexão (num lambda), já apagada pelo Qt. Quando a
        conexão seguinte nascia no mesmo endereço de memória, recebia esse objeto velho e o RDF fechava sozinho.
        Roda num processo à parte: se ele cair, o teste falha em vez de derrubar a suíte."""
        code = textwrap.dedent(
            f"""
            import gc, json, os, sys, time
            os.environ['QT_QPA_PLATFORM'] = 'offscreen'
            sys.path.insert(0, {str(_source.ROOT)!r})
            from PySide6.QtNetwork import QLocalSocket
            from rdf.qt.__main__ import create_app
            from rdf.qt.single_instance import InstanceServer
            app = create_app([])
            received = []
            for round_ in range(2):
                name = {self.name!r} + f'-seguidos-{{round_}}'
                server = InstanceServer(name)
                assert server.listen()
                server.filesReceived.connect(received.append)
                for number in range(30):
                    before = len(received)
                    socket = QLocalSocket()
                    socket.connectToServer(name)
                    assert socket.waitForConnected(2000)
                    socket.write(json.dumps({{'files': [f'C:/{{round_}}-{{number}}.pdf']}}).encode())
                    socket.waitForBytesWritten(2000)
                    socket.disconnectFromServer()
                    deadline = time.monotonic() + 5
                    while len(received) == before and time.monotonic() < deadline:
                        app.processEvents()
                        time.sleep(0.001)
                    del socket
                    if number % 7 == 0:
                        gc.collect()
                server.close()
            print(len(received))
            """
        )
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertEqual(result.stdout.strip(), '60')

    def test_sending_with_nobody_listening_reports_failure(self):
        self.assertFalse(send_to_running(['C:/a.pdf'], f'{self.name}-ninguem', timeout_ms=200))

    def test_the_json_message_format_is_stable(self):
        # o formato é parte do contrato entre duas versões do RDF abertas ao mesmo tempo
        self.assertEqual(json.loads(json.dumps({'files': ['x']})), {'files': ['x']})


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class MainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app([])

    def test_a_second_launch_hands_over_the_files_and_exits_without_a_window(self):
        with (
            mock.patch.object(entry, 'files_from_args', return_value=['C:/a.pdf']),
            mock.patch.object(entry.InstanceServer, 'listen', return_value=False),
            mock.patch.object(entry, 'send_to_running', return_value=True) as send,
            mock.patch.object(entry, 'MainWindow') as window,
            mock.patch.object(entry, 'init') as init,
        ):
            self.assertEqual(entry.main(['RDF.exe', PRINT_FLAG, 'C:/a.pdf']), 0)
        send.assert_called_once_with(['C:/a.pdf'])
        window.assert_not_called()
        init.assert_not_called()


if __name__ == '__main__':
    unittest.main()
