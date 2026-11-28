"""Tela das ferramentas na 4.0: miniaturas para escolher páginas, ordem por nome e por arrastar, resultado e prévia."""

import importlib.util
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import _source  # coloca a raiz do projeto no sys.path
import fitz
from rdf.pdftools.pages import format_page_ranges, parse_page_ranges

HAS_QT = importlib.util.find_spec('PySide6') is not None

if HAS_QT:
    from PySide6.QtCore import QEvent, QObject, Qt
    from rdf.core import settings
    from rdf.qt import motion
    from rdf.qt.__main__ import create_app
    from rdf.qt.thumbnails import ThumbnailLoader
    from rdf.qt.tool_page import natural_key
    from rdf.qt.window import MainWindow


def make_pdf(path, pages=1):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    for number in range(pages):
        document.new_page().insert_text((50, 50), f'p{number + 1}')
    document.save(path)
    document.close()
    return path


class RangeFormatTests(unittest.TestCase):
    def test_selection_becomes_short_ranges(self):
        self.assertEqual(format_page_ranges([0, 1, 2, 4, 7]), '1-3, 5, 8')
        self.assertEqual(format_page_ranges([4, 4, 0]), '1, 5')
        self.assertEqual(format_page_ranges([]), '')

    def test_a_custom_order_survives_the_round_trip(self):
        for order in ([2, 0, 1, 3, 4, 5], [9, 8, 7], [0], [1, 1, 2]):
            text = format_page_ranges(order, keep_order=True)
            self.assertEqual(parse_page_ranges(text, 10, allow_duplicates=True), order, text)


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class PageTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.prefs = settings.reset()
        self.addCleanup(settings.reset)
        patch = mock.patch.object(motion, '_enabled', False)
        patch.start()
        self.addCleanup(patch.stop)
        self.window = MainWindow()
        self.window.resize(1300, 800)
        self.window.show()
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)

    def wait_until(self, condition, timeout=10.0):
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > deadline:
                self.fail('tempo esgotado esperando a interface')
            self.app.processEvents()
            time.sleep(0.01)


class SelectPickerTests(PageTestCase):
    def setUp(self):
        super().setUp()
        self.page = self.window.open_tool('remove')
        self.page.add_paths([str(make_pdf(self.tmp / 'seis.pdf', 6))])
        self.picker = self.page.picker
        self.field = self.page.widgets['pages']

    def test_the_thumbnails_show_every_page_and_get_drawn(self):
        self.assertEqual(self.picker.grid.count(), 6)
        self.assertTrue(self.page.preview_side.isHidden())  # as miniaturas ocupam o lugar da prévia
        self.wait_until(lambda: len(self.picker.images) == 6)

    def test_clicking_thumbnails_fills_the_pages_field(self):
        for row in (0, 1, 2, 4):
            self.picker.grid.item(row).setSelected(True)
        self.assertEqual(self.field.text(), '1-3, 5')

    def test_typing_in_the_field_marks_the_thumbnails(self):
        self.field.setText('2, 4-5')
        self.assertEqual(self.picker.selected_pages(), [1, 3, 4])
        self.field.setText('99')  # inválido: as miniaturas ficam como estavam
        self.assertEqual(self.picker.selected_pages(), [1, 3, 4])

    def test_quick_buttons_choose_odd_even_all_and_none(self):
        self.picker.buttons['odd'].click()
        self.assertEqual(self.field.text(), '1, 3, 5')
        self.picker.buttons['even'].click()
        self.assertEqual(self.field.text(), '2, 4, 6')
        self.picker.buttons['all'].click()
        self.assertEqual(self.field.text(), '1-6')
        self.picker.buttons['none'].click()
        self.assertEqual(self.field.text(), '')

    def test_the_tool_runs_with_the_pages_chosen_by_thumbnail(self):
        self.picker.grid.item(0).setSelected(True)
        self.picker.grid.item(5).setSelected(True)
        target = self.tmp / 'saida.pdf'
        with mock.patch('rdf.qt.tool_page.QFileDialog.getSaveFileName', return_value=(str(target), '')):
            self.page.run()
        self.wait_until(lambda: not self.page.running)
        with fitz.open(target) as document:
            self.assertEqual([page.get_text().strip() for page in document], ['p2', 'p3', 'p4', 'p5'])

    def test_clearing_the_list_clears_the_thumbnails(self):
        self.page.clear_files()
        self.assertEqual(self.picker.grid.count(), 0)


class OrderPickerTests(PageTestCase):
    def setUp(self):
        super().setUp()
        self.page = self.window.open_tool('organize')
        self.page.add_paths([str(make_pdf(self.tmp / 'quatro.pdf', 4))])
        self.picker = self.page.picker
        self.field = self.page.widgets['order']

    def test_moving_a_page_writes_the_new_order(self):
        self.picker.grid.item(3).setSelected(True)
        self.picker.buttons['left'].click()
        self.assertEqual(self.picker.order(), [0, 1, 3, 2])
        self.assertEqual(self.field.text(), '1-2, 4, 3')

    def test_reverse_reset_and_delete(self):
        self.picker.buttons['reverse'].click()
        self.assertEqual(self.field.text(), '4, 3, 2, 1')
        self.picker.buttons['reset'].click()
        self.assertEqual(self.field.text(), '1-4')
        self.picker.grid.item(1).setSelected(True)
        self.picker.remove_selected()
        self.assertEqual(self.field.text(), '1, 3-4')

    def test_typing_an_order_rearranges_the_thumbnails(self):
        self.field.setText('4, 1')
        self.assertEqual(self.picker.order(), [3, 0])

    def test_the_picker_hides_when_the_order_is_simply_reversed(self):
        self.page.widgets['mode'].setCurrentText('Inverter a ordem')
        self.assertTrue(self.picker.isHidden())
        self.page.widgets['mode'].setCurrentText('Ordem personalizada')
        self.assertFalse(self.picker.isHidden())


class FileOrderTests(PageTestCase):
    def test_natural_order_puts_2_before_10(self):
        names = ['folha 10.pdf', 'folha 2.pdf', 'Folha 1.pdf']
        self.assertEqual(sorted(names, key=natural_key), ['Folha 1.pdf', 'folha 2.pdf', 'folha 10.pdf'])

    def test_sort_by_name_reorders_the_merge_list(self):
        page = self.window.open_tool('merge')
        paths = [str(make_pdf(self.tmp / name)) for name in ('c10.pdf', 'c2.pdf', 'c1.pdf')]
        page.add_paths(paths)
        page.sort_by_name()
        self.assertEqual([Path(p).name for p in page.files], ['c1.pdf', 'c2.pdf', 'c10.pdf'])

    def test_a_drag_inside_the_list_becomes_the_merge_order(self):
        page = self.window.open_tool('merge')
        page.add_paths([str(make_pdf(self.tmp / name)) for name in ('a.pdf', 'b.pdf', 'c.pdf')])
        item = page.tree.takeTopLevelItem(2)  # o que o arrastar faz por dentro: tira e põe em outra posição
        page.tree.insertTopLevelItem(0, item)
        page.tree.reordered.emit()
        self.assertEqual([Path(p).name for p in page.files], ['c.pdf', 'a.pdf', 'b.pdf'])

    def test_files_can_not_be_dropped_inside_another_file(self):
        page = self.window.open_tool('merge')
        page.add_paths([str(make_pdf(self.tmp / 'a.pdf')), str(make_pdf(self.tmp / 'b.pdf'))])
        flags = page.tree.topLevelItem(0).flags()
        self.assertTrue(flags & Qt.ItemIsDragEnabled)
        self.assertFalse(flags & Qt.ItemIsDropEnabled)


class ResultTests(PageTestCase):
    def run_compress(self, page):
        target = self.tmp / 'menor.pdf'
        with mock.patch('rdf.qt.tool_page.QFileDialog.getSaveFileName', return_value=(str(target), '')):
            page.run()
        self.wait_until(lambda: not page.running)
        return target

    def test_after_success_you_can_start_over(self):
        page = self.window.open_tool('compress')
        page.add_paths([str(make_pdf(self.tmp / 'a.pdf'))])
        with mock.patch.object(page, 'open_path') as opened:
            self.run_compress(page)
        opened.assert_not_called()  # abrir a pasta sozinho é uma escolha nas configurações
        self.assertFalse(page.again_button.isHidden())
        page.again_button.click()
        self.assertEqual(page.files, [])
        self.assertTrue(page.open_folder_button.isHidden())

    def test_the_folder_opens_by_itself_when_the_user_wants(self):
        self.prefs.set('open_folder_after', True)
        page = self.window.open_tool('compress')
        page.add_paths([str(make_pdf(self.tmp / 'a.pdf'))])
        with mock.patch.object(page, 'open_path') as opened:
            self.run_compress(page)
        opened.assert_called_once_with(self.tmp)

    def test_the_last_folder_is_remembered_while_the_app_is_open(self):
        page = self.window.open_tool('compress')
        chosen = str(make_pdf(self.tmp / 'pasta' / 'a.pdf'))
        with mock.patch('rdf.qt.tool_page.QFileDialog.getOpenFileNames', return_value=([chosen], '')) as dialog:
            page.add_dialog()
            page.add_dialog()
        self.assertEqual(self.prefs.get('last_folder'), str(self.tmp / 'pasta'))
        self.assertEqual(dialog.call_args_list[1].args[2], str(self.tmp / 'pasta'))
        self.assertNotIn('last_folder', self.prefs.persisted())  # o nome da pasta pode identificar alguém


class LoaderTests(PageTestCase):
    def test_only_the_latest_request_is_delivered(self):
        loader = ThumbnailLoader()
        self.addCleanup(loader.deleteLater)
        first = make_pdf(self.tmp / 'um.pdf', 3)
        second = make_pdf(self.tmp / 'dois.pdf', 2)
        received = []
        loader.ready.connect(lambda path, index, image: received.append((Path(path).name, index, image.width())))
        loader.request(first, range(3), 60)
        loader.request(second, range(2), 60)
        self.wait_until(lambda: len([r for r in received if r[0] == 'dois.pdf']) == 2)
        loader.wait()
        self.app.processEvents()
        self.assertTrue(all(name == 'dois.pdf' for name, _index, _width in received))
        self.assertTrue(all(width == 60 for _name, _index, width in received))

    def test_a_missing_file_is_reported(self):
        loader = ThumbnailLoader()
        self.addCleanup(loader.deleteLater)
        failures = []
        loader.failed.connect(lambda path, reason: failures.append(reason))
        loader.request(self.tmp / 'nao-existe.pdf', [0], 60)
        self.wait_until(lambda: failures)

    def test_the_preview_loader_answers_through_an_object_that_outlives_the_screen(self):
        """A prévia do renomeador: uma página ainda em desenho quando a tela é apagada avisa por um objeto que continua
        vivo (como nas miniaturas), e não por um filho da tela que o Qt pode estar apagando ao mesmo tempo."""
        from rdf.qt.preview import PageLoader

        screen = QObject()
        loader = PageLoader(screen)
        self.assertIsNone(loader._signals.parent())
        pages = []
        loader.loaded.connect(lambda path, index, image, total, request: pages.append((index, total, request)))
        loader.request(str(make_pdf(self.tmp / 'duas.pdf', 2)), 1, 7)
        self.wait_until(lambda: pages)
        self.assertEqual(pages, [(1, 2, 7)])
        loader.wait()
        screen.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class RemovalMarkTests(PageTestCase):
    def test_pages_chosen_for_removal_are_marked(self):
        page = self.window.open_tool('remove')
        page.add_paths([str(make_pdf(self.tmp / 'tres.pdf', 3))])
        page.widgets['pages'].setText('2')
        self.assertEqual(page.picker._marked, {1})
        page.picker.buttons['none'].click()
        self.assertEqual(page.picker._marked, set())
        self.assertFalse(self.window.open_tool('extract').picker.marks_removal)  # extrair não remove nada


if __name__ == '__main__':
    unittest.main()
