"""Acessibilidade, foco visível, nomes de arquivo do Windows, exportação sem sobrescrever e a entrega (CI, build)."""

import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _source  # coloca a raiz do projeto no sys.path
import fitz
from rdf.core import batch, config, exporter
from rdf.core.naming import MAX_NAME_LENGTH, safe_filename
from rdf.qt.theme import COLORS

ROOT = _source.ROOT


def luminance(color):
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def make_pdf(path):
    document = fitz.open()
    document.new_page()
    document.save(path)
    document.close()
    return str(path)


class FileNameTests(unittest.TestCase):
    def test_windows_reserved_names_get_a_prefix(self):
        for name in ('CON', 'nul', 'COM1', 'lpt9', 'AUX.txt', ' prn '):
            self.assertTrue(safe_filename(name).startswith('_'), name)

    def test_names_that_only_look_reserved_are_kept(self):
        for name in ('CONTA', 'COM10', 'AUXILIO', '1234 - JOSE'):
            self.assertEqual(safe_filename(name), name)

    def test_long_names_are_cut_and_control_characters_removed(self):
        self.assertLessEqual(len(safe_filename('A' * 400)), MAX_NAME_LENGTH)
        self.assertEqual(safe_filename('a\x00b\x1fc'), 'a b c')
        self.assertEqual(safe_filename('A' * 179 + ' .tail'), 'A' * 179)  # sem sobra de espaço ou ponto no fim


class ExportSafetyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def test_copy_never_overwrites_an_existing_file(self):
        source = make_pdf(self.tmp / 'a.pdf')
        target = self.tmp / 'novo.pdf'
        target.write_bytes(b'do usuario')
        with self.assertRaises(FileExistsError):
            exporter._copy_new(source, target)
        self.assertEqual(target.read_bytes(), b'do usuario')

    def test_copy_creates_the_file(self):
        source = make_pdf(self.tmp / 'a.pdf')
        exporter._copy_new(source, self.tmp / 'b.pdf')
        self.assertEqual((self.tmp / 'b.pdf').read_bytes(), Path(source).read_bytes())

    def test_an_unknown_category_from_a_tampered_session_never_becomes_a_folder(self):
        lote = batch.Batch()
        path = make_pdf(self.tmp / 'a.pdf')
        lote.load([path])
        lote.rows[path] = {'path': path, 'status': 'OK', 'new': 'N.PDF', 'category': '..\\fora'}
        result = exporter.export_batch(lote, self.tmp / 'saida')
        self.assertEqual(result.count, 1)
        self.assertTrue((self.tmp / 'saida' / 'N.PDF').is_file())
        self.assertFalse((self.tmp / 'fora').exists())

    def test_restoring_a_session_drops_an_unknown_category(self):
        path = make_pdf(self.tmp / 'a.pdf')
        data = {'files': [path], 'rows': [{'path': path, 'category': '../x', 'status': 'OK'}]}
        lote = batch.Batch()
        lote.restore_session(data, [path])
        self.assertIsNone(lote.rows[path]['category'])


class TesseractSearchTests(unittest.TestCase):
    def test_a_program_in_the_current_folder_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            planted = Path(tmp) / 'tesseract.exe'
            planted.write_bytes(b'x')
            with (
                mock.patch.object(config.shutil, 'which', return_value=str(planted)),
                mock.patch.object(config.Path, 'cwd', return_value=Path(tmp)),
            ):
                self.assertIsNone(config._which_outside_cwd('tesseract'))

    def test_a_program_elsewhere_is_found(self):
        with mock.patch.object(config.shutil, 'which', return_value=r'C:\Programas\tesseract.exe'):
            self.assertEqual(config._which_outside_cwd('tesseract'), r'C:\Programas\tesseract.exe')


class InstanceChannelTests(unittest.TestCase):
    def test_a_channel_that_does_not_open_is_reported_not_silent(self):
        from rdf.qt import single_instance

        server = single_instance.InstanceServer(name='RDF-teste-canal-falha')
        try:
            with (
                mock.patch.object(server._server, 'listen', return_value=False),
                self.assertLogs('rdf', level='WARNING') as logs,
            ):
                self.assertTrue(server.listen())  # a trava é nossa: continua sendo o primeiro processo
            self.assertFalse(server.listening)
            self.assertIn('não abriu', logs.output[0])
        finally:
            server.close()


class AccessibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from rdf.qt.__main__ import create_app

        cls.app = create_app([])

    def test_custom_painted_widgets_have_a_name_a_screen_reader_can_read(self):
        from rdf.pdftools.registry import TOOLS
        from rdf.qt.widgets import BackButton, SearchBar, ToolRow

        self.assertEqual(BackButton().accessibleName(), 'Voltar')
        search = SearchBar()
        self.assertTrue(search.edit.accessibleName())
        self.assertTrue(search.clear_button.accessibleName())
        for tool in TOOLS:
            row = ToolRow(tool)
            self.assertEqual(row.accessibleName(), tool.title)
            self.assertEqual(row.accessibleDescription(), tool.description)

    def test_option_fields_are_named_after_their_label(self):
        from rdf.pdftools.registry import TOOLS_BY_ID
        from rdf.qt.tool_page import ToolPage

        tool = TOOLS_BY_ID['split']
        page = ToolPage(tool)
        for option in tool.options:
            widget = page.widgets[option.key]
            if option.kind != 'bool':
                self.assertEqual(widget.accessibleName(), option.label)

    def test_icon_only_buttons_are_named(self):
        from rdf.pdftools.registry import TOOLS_BY_ID
        from rdf.qt.tool_page import ToolPage

        page = ToolPage(TOOLS_BY_ID['merge'])
        self.assertTrue(page.up_button.accessibleName())
        self.assertTrue(page.down_button.accessibleName())

    def test_keyboard_focus_has_a_ring_with_enough_contrast(self):
        from rdf.qt.theme import build_stylesheet

        css = build_stylesheet()
        for selector in ('QPushButton:focus', 'QCheckBox::indicator:focus', 'QTreeWidget:focus'):
            self.assertRegex(css, re.escape(selector) + r'\s*\{[^}]*2px solid')
        # o anel (marca ou tinta) contra o fundo ao redor: mínimo de 3:1 (WCAG 1.4.11)
        self.assertGreaterEqual(contrast(COLORS['brand'], COLORS['surface']), 3)
        self.assertGreaterEqual(contrast(COLORS['brand'], COLORS['brand_soft']), 3)
        self.assertGreaterEqual(contrast(COLORS['ink'], COLORS['surface']), 3)


class DeliveryTests(unittest.TestCase):
    def test_ci_runs_lint_and_the_tests_with_coverage(self):
        ci = (ROOT / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8')
        for step in ('ruff check', 'ruff format --check', 'coverage run -m unittest discover', 'coverage report'):
            self.assertIn(step, ci)
        self.assertIn('QT_QPA_PLATFORM: offscreen', ci)
        self.assertIn('coverage', (ROOT / 'requirements-dev.txt').read_text(encoding='utf-8'))

    def test_the_build_leaves_out_what_the_app_does_not_use(self):
        bat = (ROOT / 'packaging' / 'build_package.bat').read_text(encoding='utf-8')
        for module in ('QtWebEngineCore', 'QtQml', 'QtQuick', 'QtPdf', 'QtSql'):
            self.assertIn(f'--exclude-module PySide6.{module}', bat)

    def test_the_app_only_imports_qt_modules_that_ship_in_essentials(self):
        essentials = {'QtCore', 'QtGui', 'QtWidgets', 'QtNetwork', 'QtPrintSupport'}
        found = set()
        for path in (ROOT / 'rdf').rglob('*.py'):
            found |= set(re.findall(r'PySide6\.(Qt\w+)', path.read_text(encoding='utf-8')))
        self.assertTrue(found)
        self.assertLessEqual(found, essentials)


if __name__ == '__main__':
    unittest.main()
