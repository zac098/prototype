"""Erros inesperados (rdf/qt/errors.py): vão para o log com o rastro e aparecem num aviso curto, sem enxurrada."""

import importlib.util
import logging
import os
import sys
import threading
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import _source  # coloca a raiz do projeto no sys.path

HAS_QT = importlib.util.find_spec('PySide6') is not None

if HAS_QT:
    from rdf.qt import errors


def exc_info(error):
    try:
        raise error
    except BaseException as caught:  # o teste quer o objeto, seja qual for
        return type(caught), caught, caught.__traceback__


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class ReportTests(unittest.TestCase):
    def setUp(self):
        errors._state.update({'last': 0.0, 'showing': False})
        self.addCleanup(errors._state.update, {'last': 0.0, 'showing': False})

    def test_an_error_goes_to_the_log_with_the_traceback_and_is_shown(self):
        with self.assertLogs('rdf', 'CRITICAL') as logs, mock.patch.object(errors, '_show', return_value=True) as show:
            self.assertTrue(errors.report(*exc_info(ValueError('quebrou ao clicar'))))
        show.assert_called_once()
        self.assertIn('Traceback', '\n'.join(logs.output))
        self.assertIn('quebrou ao clicar', '\n'.join(logs.output))

    def test_a_repeated_error_does_not_become_a_flood_of_windows(self):
        with self.assertLogs('rdf', 'CRITICAL') as logs, mock.patch.object(errors, '_show', return_value=True) as show:
            for _ in range(5):
                errors.report(*exc_info(RuntimeError('timer com defeito')))
        self.assertEqual(show.call_count, 1)  # um aviso na tela...
        self.assertEqual(len(logs.output), 5)  # ...mas todos no log

    def test_errors_from_other_threads_only_go_to_the_log(self):
        seen = {}

        def worker():
            with mock.patch.object(errors, '_show') as show:
                seen['shown'] = errors.report(*exc_info(OSError('disco cheio')))
                seen['called'] = show.called

        with self.assertLogs('rdf', 'CRITICAL'):
            thread = threading.Thread(target=worker)
            thread.start()
            thread.join(10)
        self.assertEqual(seen, {'shown': False, 'called': False})  # janela só na thread da interface

    def test_ctrl_c_and_a_normal_exit_are_not_errors(self):
        with mock.patch.object(sys, '__excepthook__') as default, mock.patch.object(errors, '_show') as show:
            self.assertFalse(errors.report(*exc_info(KeyboardInterrupt())))
            self.assertFalse(errors.report(*exc_info(SystemExit(0))))
        default.assert_called_once()  # Ctrl+C segue o caminho normal do Python
        show.assert_not_called()

    def test_the_warning_names_the_error_and_where_the_log_is(self):
        from PySide6.QtWidgets import QMessageBox

        from rdf.qt.__main__ import create_app

        create_app([])
        seen = {}

        def fake_exec(box):
            seen['text'] = box.text()
            seen['details'] = box.informativeText()
            seen['buttons'] = [button.text() for button in box.buttons()]
            return 0

        with mock.patch.object(QMessageBox, 'exec', fake_exec):
            self.assertTrue(errors._show(ValueError('valor estranho')))
        self.assertIn('continua aberto', seen['text'])
        self.assertIn('ValueError: valor estranho', seen['details'])
        self.assertIn(str(errors.log_file()), seen['details'])
        self.assertIn('Abrir pasta do log', seen['buttons'])
        self.assertFalse(errors._state['showing'])

    def test_install_hooks_the_window_and_the_worker_threads(self):
        old_hook, old_thread_hook = sys.excepthook, threading.excepthook
        self.addCleanup(setattr, sys, 'excepthook', old_hook)
        self.addCleanup(setattr, threading, 'excepthook', old_thread_hook)
        errors.install()
        self.assertIs(sys.excepthook, errors.report)
        with self.assertLogs('rdf', 'CRITICAL'), mock.patch.object(errors, '_show') as show:
            thread = threading.Thread(target=lambda: 1 / 0)
            thread.start()
            thread.join(10)
        show.assert_not_called()  # erro numa thread de trabalho: só log


if __name__ == '__main__':
    logging.getLogger('rdf').setLevel(logging.INFO)
    unittest.main()
