"""Autoteste (python -m rdf --autoteste): o mesmo que o CI roda no executável antes de publicar uma versão."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _source import ROOT
from rdf import selftest

HAS_QT = importlib.util.find_spec('PySide6') is not None


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class SelfTestRunTests(unittest.TestCase):
    def test_the_self_test_checks_everything_and_reports_in_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_file = Path(tmp) / 'autoteste.json'
            env = dict(os.environ, QT_QPA_PLATFORM='offscreen', LOCALAPPDATA=tmp)
            result = subprocess.run(
                [sys.executable, '-m', 'rdf', '--autoteste', str(report_file)],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=300,
            )
            report = json.loads(report_file.read_text(encoding='utf-8'))
        checks = {item['nome']: item for item in report['verificacoes']}
        self.assertEqual(set(checks), {'bibliotecas', 'tesseract', 'ferramentas de PDF', 'interface'})
        for name in ('bibliotecas', 'ferramentas de PDF', 'interface'):
            self.assertTrue(checks[name]['ok'], checks[name])
        self.assertIn('RenamerPage', checks['interface']['detalhe'])  # todas as telas abriram
        if shutil.which('tesseract'):  # com o Tesseract, a leitura de verdade também passa
            self.assertTrue(checks['tesseract']['ok'], checks['tesseract'])
            self.assertTrue(report['ok'])
            self.assertEqual(result.returncode, 0, result.stderr)
        else:  # sem ele (CI sem OCR), o autoteste diz exatamente isso e sai com erro
            self.assertFalse(checks['tesseract']['ok'])
            self.assertEqual(result.returncode, 1)
        self.assertFalse(report['empacotado'])


class SelfTestUnitTests(unittest.TestCase):
    def test_a_failing_check_does_not_hide_the_others(self):
        def broken():
            raise RuntimeError('quebrado de propósito')

        checks = (('um', broken), ('dois', lambda: 'tudo certo'))
        with mock.patch.object(selftest, 'CHECKS', checks):
            report = selftest.run()
        self.assertFalse(report['ok'])
        self.assertEqual([item['ok'] for item in report['verificacoes']], [False, True])
        self.assertIn('quebrado de propósito', report['verificacoes'][0]['detalhe'])
        self.assertIn('RuntimeError', report['verificacoes'][0]['rastro'])

    def test_main_writes_the_report_where_asked_and_returns_the_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'saida.json'
            with mock.patch.object(selftest, 'run', return_value={'ok': True, 'verificacoes': []}):
                self.assertEqual(selftest.main(['RDF.exe', '--autoteste', str(target)]), 0)
            self.assertTrue(json.loads(target.read_text(encoding='utf-8'))['ok'])
            with mock.patch.object(selftest, 'run', return_value={'ok': False, 'verificacoes': []}):
                self.assertEqual(selftest.main(['RDF.exe', '--autoteste', str(target)]), 1)

    def test_the_bundled_tesseract_must_be_the_one_used(self):
        """No CI o Tesseract também está instalado no sistema: achar só esse não pode passar como sucesso."""
        with tempfile.TemporaryDirectory() as bundle, tempfile.TemporaryDirectory() as system:
            other = Path(system) / 'tesseract.exe'
            with (
                mock.patch.object(sys, '_MEIPASS', bundle, create=True),
                mock.patch('rdf.core.config.configure_tesseract', return_value=str(other)),
            ):
                with self.assertRaisesRegex(RuntimeError, 'embutido'):
                    selftest._check_tesseract()

    def test_the_entry_point_routes_the_flag_to_the_self_test(self):
        import rdf.__main__ as entry

        with mock.patch.object(selftest, 'main', return_value=0) as run:
            self.assertEqual(entry.main(['RDF.exe', '--autoteste', 'x.json']), 0)
        run.assert_called_once()


if __name__ == '__main__':
    unittest.main()
