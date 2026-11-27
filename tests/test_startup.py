"""Abertura rápida: a janela aparece sem carregar o que só as ferramentas usam (PyMuPDF, Pillow, OpenCV, Tesseract).

Esses módulos levam a maior parte do tempo de abertura; eles entram na primeira ferramenta aberta, ou antes, pelo
pré-carregamento em segundo plano que começa logo depois de a janela aparecer.
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

from _source import ROOT

HAS_QT = importlib.util.find_spec('PySide6') is not None
HEAVY = ('cv2', 'numpy', 'fitz', 'pymupdf', 'PIL', 'pytesseract')


def run_python(code):
    with tempfile.TemporaryDirectory() as data:
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen', LOCALAPPDATA=data)
        return subprocess.run(
            [sys.executable, '-c', code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=180
        )


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class LightStartupTests(unittest.TestCase):
    def test_the_home_screen_opens_without_the_heavy_libraries(self):
        code = (
            'import sys\n'
            'from rdf.qt.__main__ import create_app\n'
            'from rdf.qt.window import MainWindow\n'
            'app = create_app([])\n'
            'window = MainWindow()\n'
            'window.show()\n'
            'app.processEvents()\n'
            'window.home.search.edit.setText("comprimir")\n'  # a busca também não precisa deles
            'app.processEvents()\n'
            f'print(sorted(name for name in {HEAVY!r} if name in sys.modules))\n'
        )
        result = run_python(code)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip().splitlines()[-1], '[]')

    def test_a_tool_still_opens_and_loads_what_it_needs(self):
        code = (
            'import sys\n'
            'from rdf.qt.__main__ import create_app\n'
            'from rdf.qt.window import MainWindow\n'
            'app = create_app([])\n'
            'window = MainWindow()\n'
            'page = window.open_tool("compress")\n'
            'print(type(page).__name__, "fitz" in sys.modules)\n'
        )
        result = run_python(code)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip().splitlines()[-1], 'ToolPage True')


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class QtTranslationTests(unittest.TestCase):
    def test_qt_own_texts_are_in_portuguese(self):
        """Botões Sim/Não das perguntas e o menu de copiar e colar dos campos vinham em inglês."""
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtWidgets import QMessageBox

        from rdf.qt.__main__ import create_app

        create_app([])
        create_app([])  # de novo: a tradução não é instalada duas vezes
        self.assertEqual(QCoreApplication.translate('QPlatformTheme', '&Yes'), '&Sim')
        self.assertEqual(QCoreApplication.translate('QLineEdit', '&Copy'), '&Copiar')
        box = QMessageBox()
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        self.assertEqual(sorted(button.text() for button in box.buttons()), ['&Não', '&Sim'])
        box.deleteLater()


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class PageClassTests(unittest.TestCase):
    def test_each_tool_gets_its_own_screen(self):
        from rdf.pdftools.registry import TOOLS, TOOLS_BY_ID
        from rdf.qt.window import page_class

        self.assertEqual(page_class(TOOLS_BY_ID['renamer']).__name__, 'RenamerPage')
        self.assertEqual(page_class(TOOLS_BY_ID['merge']).__name__, 'MergePage')
        self.assertEqual(page_class(TOOLS_BY_ID['metadata']).__name__, 'MetadataPage')
        self.assertEqual(page_class(TOOLS_BY_ID['compress']).__name__, 'ToolPage')
        for tool in TOOLS:
            with self.subTest(tool=tool.id):
                self.assertTrue(callable(page_class(tool)))


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class PreloadTests(unittest.TestCase):
    def test_preload_runs_in_a_background_thread_and_never_raises(self):
        from rdf.qt import __main__ as entry

        with self.assertLogs('rdf', 'WARNING') as logs:
            thread = entry.preload_in_background(('json', 'rdf_modulo_que_nao_existe'))
            thread.join(30)
        self.assertFalse(thread.is_alive())
        self.assertTrue(thread.daemon)  # nunca segura o fechamento do app
        self.assertIn('rdf_modulo_que_nao_existe', '\n'.join(logs.output))

    def test_the_preloaded_modules_are_the_ones_the_tools_use(self):
        from rdf.qt import __main__ as entry

        for name in entry.PRELOAD_MODULES:
            with self.subTest(module=name):
                self.assertIsNotNone(importlib.util.find_spec(name))
        self.assertNotIn('PySide6', ' '.join(entry.PRELOAD_MODULES))  # telas Qt só no fio principal


class LazyModuleTests(unittest.TestCase):
    def test_the_module_is_imported_only_on_first_use(self):
        from rdf.core.lazy import LazyModule

        name = 'colorsys'  # módulo simples da biblioteca padrão: pode ser descarregado sem afetar o resto
        sys.modules.pop(name, None)
        lazy = LazyModule(name)
        self.assertNotIn(name, sys.modules)
        self.assertEqual(lazy.rgb_to_hsv(1.0, 0.0, 0.0), (0.0, 1.0, 1.0))
        self.assertIn(name, sys.modules)
        self.assertIn(name, repr(lazy))


if __name__ == '__main__':
    unittest.main()
