"""Unir PDF com o botão Imprimir: a tela de impressão do RDF (quando não há Edge) e a impressão por QPrinter."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _source  # coloca a raiz do projeto no sys.path
import fitz
from PIL import Image
from rdf.core import config
from rdf.pdftools import ops, printing, sources


def make_pdf(path, pages=2, size=(595, 842)):
    document = fitz.open()
    for number in range(pages):
        document.new_page(width=size[0], height=size[1]).insert_text((72, 72), f'pagina {number + 1}')
    document.save(path)
    document.close()
    return str(path)


def page_sizes(path):
    with fitz.open(path) as document:
        return [(round(page.rect.width), round(page.rect.height)) for page in document]


class FakePrinter:
    def __init__(self, copies=1, multiple=True, collate=True, page_range=False, first=0, last=0):
        self._copies, self._multiple, self._collate = copies, multiple, collate
        self._range, self._first, self._last = page_range, first, last

    def copyCount(self):
        return self._copies

    def supportsMultipleCopies(self):
        return self._multiple

    def collateCopies(self):
        return self._collate

    def printRange(self):
        from PySide6.QtPrintSupport import QPrinter

        return QPrinter.PageRange if self._range else QPrinter.AllPages

    def fromPage(self):
        return self._first

    def toPage(self):
        return self._last


class CopyPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from rdf.qt.__main__ import create_app

        cls.app = create_app([])

    def test_the_driver_makes_the_copies_when_it_can(self):
        self.assertEqual(printing.copy_plan(FakePrinter(copies=3, multiple=True), [0, 1]), [0, 1])

    def test_without_driver_support_collated_copies_repeat_the_whole_document(self):
        self.assertEqual(printing.copy_plan(FakePrinter(copies=2, multiple=False, collate=True), [0, 1]), [0, 1, 0, 1])

    def test_without_driver_support_uncollated_copies_repeat_each_page(self):
        self.assertEqual(printing.copy_plan(FakePrinter(copies=2, multiple=False, collate=False), [0, 1]), [0, 0, 1, 1])

    def test_a_single_copy_is_never_repeated(self):
        self.assertEqual(printing.copy_plan(FakePrinter(copies=1, multiple=False), [0, 1]), [0, 1])

    def test_all_pages_or_the_range_from_the_dialog(self):
        self.assertEqual(printing.selected_pages(FakePrinter(), 4), [0, 1, 2, 3])
        self.assertEqual(printing.selected_pages(FakePrinter(page_range=True, first=2, last=3), 4), [1, 2])
        self.assertEqual(printing.selected_pages(FakePrinter(page_range=True, first=3, last=0), 4), [2])
        self.assertEqual(printing.selected_pages(FakePrinter(page_range=True, first=2, last=99), 4), [1, 2, 3])

    def test_a_range_past_the_end_is_an_error_with_a_message(self):
        with self.assertRaises(ops.PdfToolError):
            printing.selected_pages(FakePrinter(page_range=True, first=9, last=10), 4)


class MissingConversionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.image = self.tmp / 'WhatsApp Image 2026-11-24 at 14.20.41.jpeg'
        Image.new('RGB', (300, 400), 'white').save(self.image, 'JPEG')
        self.cache = sources.SourceCache(self.tmp / 'cache')

    def test_a_converted_pdf_that_vanished_is_converted_again(self):
        first = Path(self.cache.prepare(self.image))
        first.unlink()  # limpeza, antivírus ou outra janela apagou a cópia
        again = Path(self.cache.resolve(self.image))
        self.assertTrue(again.is_file())
        self.assertEqual(len(fitz.open(again)), 1)

    def test_pdf_for_also_recovers_a_vanished_conversion(self):
        Path(self.cache.prepare(self.image)).unlink()
        self.assertTrue(Path(self.cache.pdf_for(self.image)).is_file())

    def test_pdf_for_is_none_for_something_never_converted(self):
        self.assertIsNone(self.cache.pdf_for(self.image))

    def test_an_original_that_is_gone_too_gives_a_clear_error(self):
        Path(self.cache.prepare(self.image)).unlink()
        self.image.unlink()
        with self.assertRaises(ops.PdfToolError):
            self.cache.resolve(self.image)


class MergePrintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from rdf.qt.__main__ import create_app

        cls.app = create_app([])

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        patcher = mock.patch.object(config, 'CONVERT_DIR', self.tmp / 'convertidos')
        patcher.start()
        self.addCleanup(patcher.stop)
        # Sem o Edge: estes testes cobrem a tela de impressão do RDF (no Windows, com o Edge instalado, o "Imprimir"
        # abriria o Edge de verdade no meio dos testes).
        no_edge = mock.patch('rdf.qt.print_dialog.edge_path', return_value=None)
        no_edge.start()
        self.addCleanup(no_edge.stop)
        from rdf.pdftools.registry import TOOLS_BY_ID
        from rdf.qt.merge_page import MergePage

        self.page = MergePage(TOOLS_BY_ID['merge'])
        self.addCleanup(self.page.deleteLater)
        self.out = self.tmp / 'impresso.pdf'
        self.dialogs = []

    def printer_to_file(self):
        from PySide6.QtPrintSupport import QPrinter

        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(str(self.out))
        return printer

    def fake_dialog(self, accept=True):
        def make(printer):
            dialog = mock.Mock()
            dialog.exec.return_value = 1 if accept else 0
            self.dialogs.append((dialog, printer))
            return dialog

        return mock.patch.object(self.page, 'make_print_dialog', side_effect=make)

    def windows_path(self):
        """Na tela de impressão do RDF, escolhe "Janela do Windows": estes testes cobrem esse caminho."""
        from rdf.qt.print_dialog import PrintDialog

        preview = mock.Mock()
        preview.exec.return_value = PrintDialog.WINDOWS
        return mock.patch.object(self.page, 'make_preview_dialog', return_value=preview)

    def print_it(self, accept=True):
        with (
            mock.patch.object(self.page, 'make_printer', side_effect=self.printer_to_file),
            self.fake_dialog(accept),
            self.windows_path(),
        ):
            self.page.print_files()

    def add(self, *paths):
        self.page.add_paths([str(p) for p in paths])

    def test_the_print_button_exists_and_follows_the_list(self):
        self.assertEqual(self.page.print_button.text(), 'Imprimir…')
        self.assertFalse(self.page.print_button.isEnabled())
        self.add(make_pdf(self.tmp / 'a.pdf'))
        self.assertTrue(self.page.print_button.isEnabled())  # um arquivo só já basta para imprimir
        self.page.clear_files()
        self.assertFalse(self.page.print_button.isEnabled())

    def test_the_button_is_off_while_a_task_runs(self):
        self.add(make_pdf(self.tmp / 'a.pdf'))
        self.page.running = True
        self.page.update_print_button()
        self.assertFalse(self.page.print_button.isEnabled())
        self.page.running = False

    def test_nothing_in_the_list_says_what_to_do(self):
        self.page.print_files()
        self.assertEqual(self.page.message.property('tone'), 'error')
        self.assertFalse(self.dialogs)

    def test_a_single_file_is_printed_by_itself(self):
        self.add(make_pdf(self.tmp / 'a.pdf', pages=3))
        self.print_it()
        self.assertEqual(len(fitz.open(self.out)), 3)
        self.assertEqual(self.page.message.property('tone'), 'ok')
        self.assertIn('3 página(s)', self.page.message.text())

    def test_several_files_are_joined_in_the_list_order_and_printed_as_one_document(self):
        self.add(make_pdf(self.tmp / 'a.pdf', pages=1), make_pdf(self.tmp / 'b.pdf', pages=2))
        self.page.files = list(reversed(self.page.files))  # a ordem da lista é a ordem do papel
        self.page.refresh_files()
        self.print_it()
        with fitz.open(self.out) as document:
            self.assertEqual(len(document), 3)
        dialog, printer = self.dialogs[0]
        self.assertEqual(printer.docName(), 'RDF - 2 arquivos')
        dialog.setMinMax.assert_called_once_with(1, 3)

    def files_left_by_printing(self):
        """Tudo o que ficou no disco depois de imprimir, fora dos arquivos do teste e da saída da impressora falsa."""
        return sorted(p.name for p in self.page.cache.folder.rglob('*.pdf') if 'impressao' in p.parts)

    def test_printing_saves_nothing_the_joined_pdf_is_deleted_after(self):
        originals = [make_pdf(self.tmp / 'a.pdf'), make_pdf(self.tmp / 'b.pdf', pages=2)]
        self.add(*originals)
        seen = {}

        def dialog(printer):
            seen['during'] = self.files_left_by_printing()  # existe só enquanto a janela de impressão está aberta
            return mock.Mock(exec=mock.Mock(return_value=1))

        with (
            mock.patch.object(self.page, 'make_printer', side_effect=self.printer_to_file),
            mock.patch.object(self.page, 'make_print_dialog', side_effect=dialog),
            self.windows_path(),
        ):
            self.page.print_files()
        self.assertEqual(seen['during'], ['juntados.pdf'])
        self.assertEqual(self.files_left_by_printing(), [])
        self.assertFalse(self.page.print_folder.exists())
        self.assertEqual(sorted(p.name for p in self.tmp.glob('*.pdf')), ['a.pdf', 'b.pdf', 'impresso.pdf'])

    def test_cancelling_or_failing_also_deletes_the_joined_pdf(self):
        self.add(make_pdf(self.tmp / 'a.pdf'), make_pdf(self.tmp / 'b.pdf'))
        self.print_it(accept=False)
        self.assertFalse(self.page.print_folder.exists())
        with mock.patch.object(printing, 'print_document', side_effect=ops.PdfToolError('A impressora não aceitou')):
            self.print_it()
        self.assertFalse(self.page.print_folder.exists())

    def test_a_single_original_file_is_never_deleted_by_printing(self):
        original = make_pdf(self.tmp / 'unico.pdf')
        self.add(original)
        self.print_it()
        self.assertTrue(Path(original).exists())

    def test_the_print_button_says_it_saves_nothing(self):
        self.assertIn('nada fica salvo', self.page.print_hint.text())
        self.assertIn('Não salva', self.page.print_button.toolTip())

    def test_the_document_name_is_the_file_name_when_there_is_one_file(self):
        self.add(make_pdf(self.tmp / 'Extrato.pdf'))
        self.print_it()
        self.assertEqual(self.dialogs[0][1].docName(), 'Extrato.pdf')

    def test_images_are_converted_and_printed(self):
        photo = self.tmp / 'foto.jpg'
        Image.new('RGB', (600, 800), 'white').save(photo, 'JPEG')
        self.add(photo, make_pdf(self.tmp / 'a.pdf', pages=1))
        self.print_it()
        self.assertEqual(len(fitz.open(self.out)), 2)

    def test_cancelling_the_windows_dialog_prints_nothing(self):
        self.add(make_pdf(self.tmp / 'a.pdf'))
        self.print_it(accept=False)
        self.assertFalse(self.out.exists())
        self.assertIn('cancelada', self.page.message.text())

    def test_each_page_keeps_its_orientation(self):
        document = fitz.open()
        document.new_page(width=595, height=842)
        document.new_page(width=842, height=595)
        wide = self.tmp / 'misto.pdf'
        document.save(wide)
        document.close()
        self.add(wide)
        self.print_it()
        sizes = page_sizes(self.out)
        self.assertLess(sizes[0][0], sizes[0][1])
        self.assertGreater(sizes[1][0], sizes[1][1])

    def test_a_locked_pdf_gives_a_clear_message_before_the_dialog(self):
        locked = self.tmp / 'trancado.pdf'
        ops.protect_pdf(make_pdf(self.tmp / 'a.pdf'), locked, 'senha')
        self.page.files = [str(locked)]
        self.page.info[str(locked)] = {'detail': 'protegido', 'size': 1, 'pages': 0, 'locked': True, 'kind': 'PDF'}
        self.print_it()
        self.assertEqual(self.page.message.property('tone'), 'error')
        self.assertIn('senha', self.page.message.text())
        self.assertFalse(self.dialogs)

    def test_a_printer_that_refuses_the_document_is_reported(self):
        self.add(make_pdf(self.tmp / 'a.pdf'))
        with mock.patch.object(printing, 'print_document', side_effect=ops.PdfToolError('A impressora não aceitou')):
            self.print_it()
        self.assertIn('não aceitou', self.page.message.text())
        self.assertEqual(self.page.message.property('tone'), 'error')

    def test_a_failure_in_the_middle_aborts_the_print_job(self):
        from PySide6.QtPrintSupport import QPrinter

        pdf = make_pdf(self.tmp / 'a.pdf', pages=2)
        printer = self.printer_to_file()
        with (
            mock.patch.object(printer, 'abort', wraps=printer.abort) as abort,
            mock.patch.object(QPrinter, 'newPage', side_effect=RuntimeError('papel acabou')),
        ):
            with self.assertRaises(RuntimeError):
                printing.print_document(pdf, printer)
        abort.assert_called()

    def test_the_ctrl_p_shortcut_prints(self):
        from PySide6.QtGui import QShortcut

        shortcuts = [s for s in self.page.findChildren(QShortcut) if s.key().toString() == 'Ctrl+P']
        self.assertEqual(len(shortcuts), 1)

    def test_merging_still_needs_two_files_but_printing_does_not(self):
        self.add(make_pdf(self.tmp / 'a.pdf'))
        self.page.run()
        self.assertEqual(self.page.message.property('tone'), 'error')  # Unir pede 2 arquivos
        self.assertTrue(self.page.print_button.isEnabled())


class RegistryTests(unittest.TestCase):
    def test_the_print_tool_is_gone_and_merge_mentions_printing(self):
        from rdf.pdftools.registry import TOOLS_BY_ID, search_tools

        self.assertNotIn('print', TOOLS_BY_ID)
        self.assertEqual(search_tools('imprimir')[0].id, 'merge')
        self.assertFalse((_source.ROOT / 'rdf' / 'qt' / 'print_page.py').exists())


if __name__ == '__main__':
    unittest.main()
