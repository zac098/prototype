"""Tela de impressão do RDF (prévia e opções) e a impressão com essas opções, conferida num PDF de saída."""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import _source  # coloca a raiz do projeto no sys.path
import fitz
import numpy as np
from rdf.core import config
from rdf.pdftools import printing

HAS_QT = importlib.util.find_spec('PySide6') is not None


def make_pdf(path, pages=3, landscape=False, color=(0, 0, 0)):
    document = fitz.open()
    for number in range(pages):
        page = document.new_page(width=842 if landscape else 595, height=595 if landscape else 842)
        page.draw_rect(page.rect, color=color, fill=color)  # página toda pintada: fácil de medir na saída
        page.insert_text((60, 80), f'pagina {number + 1}', fontsize=30, color=(1, 1, 1))
    document.save(path)
    document.close()
    return Path(path)


class LayoutTests(unittest.TestCase):
    def test_pages_are_grouped_by_sheet(self):
        self.assertEqual(printing.sheets_for(range(5), 2), [[0, 1], [2, 3], [4]])
        self.assertEqual(printing.sheets_for([4, 0], 1), [[4], [0]])
        self.assertEqual(printing.sheets_for(range(3), 7), [[0], [1], [2]])  # valor estranho: uma por folha

    def test_automatic_orientation(self):
        portrait, landscape = (595, 842), (842, 595)
        self.assertFalse(printing.sheet_landscape(portrait, 1, 'auto'))
        self.assertTrue(printing.sheet_landscape(landscape, 1, 'auto'))
        self.assertTrue(printing.sheet_landscape(portrait, 2, 'auto'))  # duas em pé, lado a lado
        self.assertFalse(printing.sheet_landscape(portrait, 4, 'auto'))
        self.assertTrue(printing.sheet_landscape(portrait, 1, 'landscape'))
        self.assertFalse(printing.sheet_landscape(landscape, 1, 'portrait'))

    def test_the_grid_turns_with_the_sheet(self):
        self.assertEqual(printing.grid_for(2, True), (2, 1))
        self.assertEqual(printing.grid_for(2, False), (1, 2))
        self.assertEqual(printing.grid_for(6, False), (2, 3))

    def test_cells_and_placement(self):
        cells = printing.cell_rects((0, 0, 210, 100), 2, 1, 10)
        self.assertEqual(cells, [(0, 0, 100.0, 100.0), (110.0, 0, 100.0, 100.0)])
        x, y, width, height = printing.place_page((0, 0, 100, 100), (50, 100), 'fit', 1)
        self.assertEqual((x, y, width, height), (25.0, 0.0, 50.0, 100.0))
        _x, _y, width, _height = printing.place_page((0, 0, 100, 100), (50, 100), 'actual', 0.5)
        self.assertEqual(width, 25.0)  # tamanho real: 1 ponto do PDF = 0,5 pixel neste dispositivo

    def test_copies_the_app_repeats_when_the_driver_does_not(self):
        sheets = [[0], [1]]
        self.assertEqual(printing.sheet_plan(sheets, 2, True, False), [[0], [1], [0], [1]])
        self.assertEqual(printing.sheet_plan(sheets, 2, False, False), [[0], [0], [1], [1]])
        self.assertEqual(printing.sheet_plan(sheets, 3, True, True), sheets)


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class QtPrintCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from rdf.qt.__main__ import create_app

        cls.app = create_app([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.out = self.tmp / 'saida.pdf'

    def printer(self):
        from PySide6.QtPrintSupport import QPrinter

        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(str(self.out))
        return printer

    def output(self):
        with fitz.open(self.out) as document:
            return [(round(page.rect.width), round(page.rect.height)) for page in document]

    def dialog(self, pdf, printers=(['Impressora de teste'], 'Impressora de teste')):
        from rdf.qt.print_dialog import PrintDialog

        dialog = PrintDialog(pdf, 'teste', None, printers=printers)
        self.addCleanup(dialog.deleteLater)
        return dialog


class PrintWithSettingsTests(QtPrintCase):
    def test_two_pages_per_sheet_on_landscape_paper(self):
        source = make_pdf(self.tmp / 'a.pdf', pages=3)
        settings = printing.PrintSettings(per_sheet=2, paper='A4')
        pages, sheets = printing.print_with_settings(source, self.printer(), settings)
        self.assertEqual((pages, sheets), (3, 2))
        sizes = self.output()
        self.assertEqual(len(sizes), 2)
        self.assertGreater(sizes[0][0], sizes[0][1])  # folha deitada

    def test_chosen_pages_paper_and_orientation(self):
        source = make_pdf(self.tmp / 'a.pdf', pages=5)
        settings = printing.PrintSettings(pages=(4, 0), paper='Carta', orientation='landscape')
        printing.print_with_settings(source, self.printer(), settings)
        self.assertEqual(self.output(), [(792, 612), (792, 612)])

    def test_black_and_white_prints_without_color(self):
        source = make_pdf(self.tmp / 'cor.pdf', pages=1, color=(0.9, 0.1, 0.1))
        printing.print_with_settings(source, self.printer(), printing.PrintSettings(grayscale=True))
        with fitz.open(self.out) as document:
            pix = document[0].get_pixmap(dpi=30)
        pixels = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n).astype(int)
        self.assertLess((pixels.max(axis=2) - pixels.min(axis=2)).max(), 12)

    def test_normal_margins_leave_one_centimeter(self):
        source = make_pdf(self.tmp / 'a.pdf', pages=1)
        printing.print_with_settings(source, self.printer(), printing.PrintSettings(margins='normal'))
        with fitz.open(self.out) as document:
            pix = document[0].get_pixmap(dpi=72)
        pixels = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, 0]
        ys, xs = np.where(pixels < 128)
        to_mm = 25.4 / 72
        self.assertGreaterEqual(xs.min() * to_mm, 9)
        self.assertGreaterEqual(ys.min() * to_mm, 9)

    def test_a_page_outside_the_document_is_an_error(self):
        from rdf.pdftools import ops

        source = make_pdf(self.tmp / 'a.pdf', pages=2)
        with self.assertRaises(ops.PdfToolError):
            printing.print_with_settings(source, self.printer(), printing.PrintSettings(pages=(5,)))


class DialogTests(QtPrintCase):
    def test_the_preview_shows_the_sheets_and_follows_the_options(self):
        dialog = self.dialog(make_pdf(self.tmp / 'a.pdf', pages=3))
        self.assertFalse(dialog.preview.pixmap().isNull())
        self.assertEqual(dialog.sheet_label.text(), 'Folha 1 de 3')
        dialog.per_sheet_combo.setCurrentIndex(dialog.per_sheet_combo.findData(2))
        dialog.refresh_preview()
        self.assertEqual(dialog.sheet_label.text(), 'Folha 1 de 2')
        self.assertIn('3 páginas em 2 folhas', dialog.summary.text())
        self.assertFalse(dialog.scale_combo.isEnabled())  # várias por folha: sempre ajustadas
        pixmap = dialog.preview.pixmap()
        self.assertGreater(pixmap.width(), pixmap.height())  # a prévia vira junto com a folha

    def test_navigation_between_sheets(self):
        dialog = self.dialog(make_pdf(self.tmp / 'a.pdf', pages=3))
        self.assertFalse(dialog.prev_button.isEnabled())
        dialog.next_button.click()
        dialog.next_button.click()
        self.assertEqual(dialog.sheet_label.text(), 'Folha 3 de 3')
        self.assertFalse(dialog.next_button.isEnabled())

    def test_typed_pages_are_checked_before_printing(self):
        dialog = self.dialog(make_pdf(self.tmp / 'a.pdf', pages=3))
        dialog.pages_combo.setCurrentIndex(dialog.pages_combo.findData('custom'))
        self.assertFalse(dialog.pages_edit.isHidden())
        dialog.pages_edit.setText('9')
        dialog.update_controls()
        self.assertFalse(dialog.print_button.isEnabled())
        self.assertFalse(dialog.error.isHidden())
        dialog.pages_edit.setText('3, 1')
        dialog.update_controls()
        self.assertTrue(dialog.print_button.isEnabled())
        self.assertEqual(dialog.settings().pages, (2, 0))

    def test_all_options_reach_the_settings(self):
        dialog = self.dialog(make_pdf(self.tmp / 'a.pdf', pages=2))
        dialog.copies_spin.setValue(3)
        dialog.collate_check.setChecked(False)
        dialog.paper_combo.setCurrentIndex(dialog.paper_combo.findData('Ofício'))
        dialog.color_combo.setCurrentIndex(dialog.color_combo.findData(True))
        dialog.duplex_combo.setCurrentIndex(dialog.duplex_combo.findData('long'))
        dialog.margins_combo.setCurrentIndex(dialog.margins_combo.findData('minimum'))
        settings = dialog.settings()
        self.assertEqual(
            (settings.copies, settings.collate, settings.paper, settings.grayscale, settings.duplex, settings.margins),
            (3, False, 'Ofício', True, 'long', 'minimum'),
        )

    def test_without_printers_nothing_can_be_printed(self):
        dialog = self.dialog(make_pdf(self.tmp / 'a.pdf', pages=1), printers=([], ''))
        self.assertFalse(dialog.print_button.isEnabled())
        self.assertFalse(dialog.no_printer.isHidden())

    def test_closing_releases_the_pdf_and_the_windows_button_says_so(self):
        dialog = self.dialog(make_pdf(self.tmp / 'a.pdf', pages=1))
        dialog.windows_button.click()
        self.assertEqual(dialog.result(), dialog.WINDOWS)
        self.assertIsNone(dialog.document)


class MergeFlowTests(QtPrintCase):
    def test_print_from_merge_uses_the_preview_and_saves_nothing(self):
        from rdf.core import settings
        from rdf.pdftools.registry import TOOLS_BY_ID
        from rdf.qt.merge_page import MergePage
        from rdf.qt.print_dialog import PrintDialog

        settings.reset()
        patch = mock.patch.object(config, 'CONVERT_DIR', self.tmp / 'temp')
        patch.start()
        self.addCleanup(patch.stop)
        page = MergePage(TOOLS_BY_ID['merge'])
        self.addCleanup(page.deleteLater)
        page.add_paths([str(make_pdf(self.tmp / 'a.pdf', pages=1)), str(make_pdf(self.tmp / 'b.pdf', pages=3))])
        seen = {}

        def make_preview(pdf, title):
            dialog = PrintDialog(pdf, title, None, printers=(['Impressora de teste'], 'Impressora de teste'))
            dialog.per_sheet_combo.setCurrentIndex(dialog.per_sheet_combo.findData(2))
            seen['title'] = title
            dialog.exec = lambda: 1
            dialog.make_printer = self.printer
            return dialog

        with mock.patch.object(page, 'make_preview_dialog', side_effect=make_preview):
            page.print_files()
        self.assertEqual(seen['title'], 'RDF - 2 arquivos')
        self.assertEqual(len(self.output()), 2)  # 4 páginas, 2 por folha
        self.assertIn('4 página(s) em 2 folha(s)', page.message.text())
        self.assertFalse(page.print_folder.exists())

    def test_cancelling_the_preview_prints_nothing(self):
        from rdf.core import settings
        from rdf.pdftools.registry import TOOLS_BY_ID
        from rdf.qt.merge_page import MergePage

        settings.reset()
        patch = mock.patch.object(config, 'CONVERT_DIR', self.tmp / 'temp')
        patch.start()
        self.addCleanup(patch.stop)
        page = MergePage(TOOLS_BY_ID['merge'])
        self.addCleanup(page.deleteLater)
        page.add_paths([str(make_pdf(self.tmp / 'a.pdf', pages=1))])
        preview = mock.Mock()
        preview.exec.return_value = 0
        with mock.patch.object(page, 'make_preview_dialog', return_value=preview):
            page.print_files()
        self.assertIn('cancelada', page.message.text())
        self.assertFalse(self.out.exists())


if __name__ == '__main__':
    unittest.main()
