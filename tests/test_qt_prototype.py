"""Protótipo do novo visual (PySide6): tela inicial, ferramentas, botão Voltar, busca, rolagem e execução real.

Roda sem janela de verdade (plataforma "offscreen") e é ignorado se o PySide6 não estiver instalado.
"""

import importlib.util
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import _source  # coloca a raiz do projeto no sys.path
import fitz

HAS_QT = importlib.util.find_spec('PySide6') is not None

if HAS_QT:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QComboBox
    from rdf.pdftools import jobs, ops
    from rdf.pdftools.registry import CATEGORIES, TOOLS
    from rdf.qt import motion
    from rdf.qt.__main__ import create_app
    from rdf.qt.theme import COLORS, build_stylesheet
    from rdf.qt.widgets import SmoothScrollArea, mix
    from rdf.qt.window import APP_TITLE, MainWindow


def make_pdf(path, pages=1):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    for number in range(pages):
        document.new_page().insert_text((50, 50), f'p{number}')
    document.save(path)
    document.close()
    return path


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class QtTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        from rdf.core import settings

        settings.reset()  # cada teste começa sem favoritas, recentes nem janela salva
        self.window = MainWindow()
        self.window.resize(1100, 700)
        self.window.show()
        self.addCleanup(self.close_window)
        patch = mock.patch.object(motion, '_enabled', True)
        patch.start()
        self.addCleanup(patch.stop)

    def close_window(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def wait_until(self, condition, timeout=10.0):
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > deadline:
                self.fail('tempo esgotado esperando a interface')
            self.app.processEvents()
            time.sleep(0.01)


class StyleTests(QtTestCase):
    def test_the_stylesheet_has_no_unreplaced_tokens(self):
        css = build_stylesheet()
        self.assertNotIn('@', css)
        self.assertIn(COLORS['brand'], css)
        icon_paths = [part.split('"')[1] for part in css.split('url(')[1:]]
        self.assertEqual(len(icon_paths), 4)  # tique, seta da lista e setas do campo numérico
        for path in icon_paths:
            self.assertTrue(Path(path).is_file(), path)

    def test_mix_goes_between_two_colors(self):
        self.assertEqual(mix('#000000', '#ffffff', 0).name(), '#000000')
        self.assertEqual(mix('#000000', '#ffffff', 1).name(), '#ffffff')
        self.assertEqual(mix('#000000', '#ffffff', 0.5).name(), '#808080')
        self.assertEqual(mix('#102030', '#405060', 9).name(), '#405060')


class HomeTests(QtTestCase):
    def test_tools_are_grouped_by_category_and_the_renamer_comes_first(self):
        home = self.window.home
        self.assertEqual(home.section_titles, list(CATEGORIES))
        self.assertEqual(home.cards[0].tool.id, 'renamer')
        self.assertEqual({card.tool.id for card in home.cards}, {tool.id for tool in TOOLS})

    def test_search_keeps_only_the_sections_with_matches(self):
        home = self.window.home
        home.search.edit.setText('senha')
        self.assertEqual(home.section_titles, ['Segurança'])
        self.assertEqual({card.tool.id for card in home.cards}, {'protect', 'unlock'})
        home.search.clear()
        self.assertEqual(len(home.cards), len(TOOLS))

    def test_a_search_without_results_says_so(self):
        self.window.home.search.edit.setText('zzzzzz')
        self.assertEqual(self.window.home.cards, [])
        self.assertFalse(self.window.home.empty_label.isHidden())

    def test_columns_follow_the_window_width(self):
        self.window.resize(1400, 700)
        self.app.processEvents()
        self.window.home.layout_columns(force=True)
        self.assertEqual(self.window.home.columns, 3)
        self.window.resize(800, 600)
        self.app.processEvents()
        self.window.home.layout_columns(force=True)
        self.assertLessEqual(self.window.home.columns, 2)

    def test_the_search_bar_shows_its_shortcut_until_there_is_text(self):
        bar = self.window.home.search
        self.assertFalse(bar.hint.isHidden())
        bar.edit.setText('a')
        self.assertTrue(bar.hint.isHidden())
        self.assertFalse(bar.clear_button.isHidden())
        bar.clear()
        self.assertTrue(bar.clear_button.isHidden())


class NavigationTests(QtTestCase):
    def test_clicking_a_row_opens_the_tool_and_back_returns_home(self):
        row = next(card for card in self.window.home.cards if card.tool.id == 'split')
        QTest.mouseClick(row, Qt.LeftButton, Qt.NoModifier, row.rect().center())
        self.assertEqual(self.window.current_id, 'split')
        self.assertIn('Dividir PDF', self.window.windowTitle())
        button = self.window.back_button
        self.assertIsNotNone(button)
        QTest.mouseClick(button, Qt.LeftButton, Qt.NoModifier, button.rect().center())
        self.assertIsNone(self.window.current_id)
        self.assertEqual(self.window.windowTitle(), APP_TITLE)
        self.assertIsNone(self.window.back_button)

    def test_every_tool_page_builds(self):
        for tool in TOOLS:
            with self.subTest(tool=tool.id):
                page = self.window.open_tool(tool.id)
                self.assertIs(self.window.stack.currentWidget(), page)
        self.window.show_home()

    def test_show_home_alone_keeps_the_tool_as_it_was(self):
        page = self.window.open_tool('merge')
        page.add_paths([str(make_pdf(self.tmp / 'a.pdf'))])
        self.window.show_home()
        self.assertIs(self.window.open_tool('merge'), page)
        self.assertEqual(len(page.files), 1)

    def test_escape_clears_the_search_first_and_then_leaves_the_tool(self):
        self.window.home.search.edit.setText('senha')
        self.window.on_escape()
        self.assertEqual(self.window.home.search.text(), '')
        self.window.open_tool('merge')
        self.window.on_escape()
        self.assertIsNone(self.window.current_id)

    def test_ctrl_f_goes_home_and_focuses_the_search(self):
        self.window.open_tool('merge')
        self.window.focus_search()
        self.assertIsNone(self.window.current_id)
        # focusWidget() diz quem recebe o foco dentro da janela, mesmo sem o foco real do Windows (teste).
        self.assertIs(self.window.focusWidget(), self.window.home.search.edit)

    def test_the_renamer_opens_inside_the_window(self):
        from rdf.qt.renamer import RenamerPage

        page = self.window.open_tool('renamer')
        self.assertIsInstance(page, RenamerPage)
        self.assertIs(self.window.stack.currentWidget(), page)


class MotionTests(QtTestCase):
    def wheel(self, widget, delta):
        event = QWheelEvent(
            widget.rect().center(),
            widget.mapToGlobal(widget.rect().center()),
            QPoint(0, 0),
            QPoint(0, delta),
            Qt.NoButton,
            Qt.NoModifier,
            Qt.NoScrollPhase,
            False,
        )
        self.app.sendEvent(widget, event)

    def test_the_wheel_glides_to_its_target_and_stops_at_the_ends(self):
        self.window.resize(780, 520)
        self.app.processEvents()
        scroll = self.window.home.scroll
        bar = scroll.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        self.wheel(scroll.viewport(), -120)
        self.assertTrue(scroll.gliding())
        self.wait_until(lambda: not scroll.gliding())
        self.assertGreater(bar.value(), 0)
        for _ in range(60):
            self.wheel(scroll.viewport(), -120)
        self.wait_until(lambda: not scroll.gliding())
        self.assertEqual(bar.value(), bar.maximum())
        for _ in range(60):
            self.wheel(scroll.viewport(), 120)
        self.wait_until(lambda: not scroll.gliding())
        self.assertEqual(bar.value(), 0)

    def test_without_animations_the_scroll_and_hover_are_immediate(self):
        self.window.resize(780, 520)
        self.app.processEvents()
        scroll = self.window.home.scroll
        with mock.patch.object(motion, '_enabled', False):
            self.wheel(scroll.viewport(), -120)
            self.assertFalse(scroll.gliding())
            self.assertGreater(scroll.verticalScrollBar().value(), 0)
            row = self.window.home.cards[0]
            row.animate_to(1.0)
            self.assertEqual(row.level(), 1.0)

    def test_hover_fades_in_and_out(self):
        row = self.window.home.cards[0]
        row.animate_to(1.0)
        self.assertLess(row.level(), 1.0)
        self.wait_until(lambda: row.level() == 1.0)
        row.animate_to(0.0)
        self.wait_until(lambda: row.level() == 0.0)

    def test_the_scroll_area_is_the_smooth_one(self):
        self.assertIsInstance(self.window.home.scroll, SmoothScrollArea)


class ToolPageTests(QtTestCase):
    def test_wrong_files_are_rejected_with_a_message(self):
        page = self.window.open_tool('merge')
        fake = self.tmp / 'fake.pdf'
        fake.write_bytes(b'not a pdf')
        page.add_paths([str(fake)])
        self.assertEqual(page.files, [])
        self.assertIn('inválido', page.message.text())
        page.add_paths([str(self.tmp / 'programa.exe')])
        self.assertIn('Nenhum arquivo compatível', page.message.text())
        page.add_paths([str(self.tmp / 'x.txt')])  # um formato aceito, mas o arquivo não existe
        self.assertEqual(page.files, [])
        self.assertIn('x.txt', page.message.text())

    def test_adding_files_fills_the_list_with_pages_and_a_preview(self):
        page = self.window.open_tool('merge')
        page.add_paths([str(make_pdf(self.tmp / 'a.pdf', 2)), str(make_pdf(self.tmp / 'b.pdf', 3))])
        self.assertEqual(page.counter.text(), '2 arquivos  ·  5 páginas')
        self.assertEqual(page.tree.topLevelItemCount(), 2)
        self.wait_until(lambda: not page.preview.pixmap().isNull())  # desenhada em segundo plano

    def test_duplicates_are_ignored_and_files_can_be_moved_and_removed(self):
        page = self.window.open_tool('merge')
        a, b = str(make_pdf(self.tmp / 'a.pdf')), str(make_pdf(self.tmp / 'b.pdf'))
        page.add_paths([a, b])
        page.add_paths([a])
        self.assertEqual(page.files, [a, b])
        page.tree.setCurrentItem(page.tree.topLevelItem(1))
        page.tree.topLevelItem(1).setSelected(True)
        page.tree.topLevelItem(0).setSelected(False)
        page.move(-1)
        self.assertEqual(page.files, [b, a])
        page.remove_selected()
        self.assertEqual(len(page.files), 1)
        page.clear_files()
        self.assertEqual(page.files_stack.currentIndex(), 0)

    def test_a_single_file_tool_keeps_only_one_file(self):
        page = self.window.open_tool('split')
        a, b = str(make_pdf(self.tmp / 'a.pdf')), str(make_pdf(self.tmp / 'b.pdf'))
        page.add_paths([a, b])
        self.assertEqual(page.files, [a])
        page.add_paths([b])
        self.assertEqual(page.files, [b])

    def test_needing_files_and_valid_numbers_are_checked_before_running(self):
        page = self.window.open_tool('merge')
        page.run()
        self.assertIn('pelo menos 2', page.message.text())
        self.assertEqual(page.message.property('tone'), 'error')

    def test_options_show_and_hide_with_the_others(self):
        page = self.window.open_tool('split')
        ranges, every = (page.option_frames[key][0] for key in ('ranges', 'every'))
        self.assertFalse(ranges.isHidden())
        self.assertTrue(every.isHidden())
        mode_frame = page.option_frames['mode'][0]
        mode_frame.findChild(QComboBox).setCurrentText('A cada N páginas')
        self.assertTrue(ranges.isHidden())
        self.assertFalse(every.isHidden())

    def test_a_narrow_window_hides_the_preview_and_shortens_the_buttons(self):
        page = self.window.open_tool('merge')
        page.add_paths([str(make_pdf(self.tmp / 'a.pdf'))])
        self.window.resize(800, 560)
        self.app.processEvents()
        self.assertTrue(page.narrow)
        self.assertTrue(page.preview_side.isHidden())
        self.assertEqual(page.add_button.text(), 'Adicionar')
        self.window.resize(1400, 700)
        self.app.processEvents()
        self.assertFalse(page.narrow)
        self.assertEqual(page.add_button.text(), 'Adicionar mais')

    def test_same_named_files_from_different_folders_get_different_destinations(self):
        page = self.window.open_tool('compress')
        page.add_paths([str(make_pdf(self.tmp / folder / 'doc.pdf')) for folder in ('x', 'y', 'z')])
        out = self.tmp / 'saida'
        out.mkdir()
        with mock.patch('rdf.qt.tool_page.QFileDialog.getExistingDirectory', return_value=str(out)):
            planned = page.ask_destination()
        self.assertEqual(len({str(dest).lower() for _origin, dest in planned}), 3)

    def test_merging_two_pdfs_runs_in_the_background_and_reports_the_result(self):
        page = self.window.open_tool('merge')
        page.add_paths([str(make_pdf(self.tmp / 'a.pdf', 2)), str(make_pdf(self.tmp / 'b.pdf', 3))])
        target = self.tmp / 'unido.pdf'
        with mock.patch('rdf.qt.tool_page.QFileDialog.getSaveFileName', return_value=(str(target), '')):
            page.run()
        self.assertTrue(page.running)
        self.assertEqual(page.run_button.text(), 'Cancelar tarefa')  # durante o trabalho, o botão vira Cancelar
        self.wait_until(lambda: not page.running)
        self.assertEqual(page.run_button.text(), page.tool.action)
        self.assertTrue(page.run_button.isEnabled())
        self.assertFalse(page.has_unsaved_work())  # depois de processar, não há mais nada a perder
        with fitz.open(target) as document:
            self.assertEqual(document.page_count, 5)
        self.assertIn('unidos', page.message.text())
        self.assertEqual(page.message.property('tone'), 'ok')
        self.assertFalse(page.open_folder_button.isHidden())
        self.assertFalse(page.open_file_button.isHidden())

    def test_a_failure_is_shown_as_an_error_and_the_page_is_usable_again(self):
        page = self.window.open_tool('remove')
        page.add_paths([str(make_pdf(self.tmp / 'a.pdf', 2))])
        target = self.tmp / 'out.pdf'
        with mock.patch('rdf.qt.tool_page.QFileDialog.getSaveFileName', return_value=(str(target), '')):
            page.run()
        self.wait_until(lambda: not page.running)
        self.assertEqual(page.message.property('tone'), 'error')
        self.assertFalse(target.exists())
        self.assertTrue(page.run_button.isEnabled())

    def test_closing_while_running_asks_first(self):
        page = self.window.open_tool('merge')
        page.running = True
        with mock.patch('rdf.qt.window.QMessageBox.warning', return_value=mock.sentinel.no) as warning:
            self.assertFalse(self.window.close())
        warning.assert_called_once()
        page.running = False


class IncomingFilesTests(QtTestCase):
    """Arquivos que chegam do menu do botão direito: o Explorer abre o RDF uma vez por arquivo."""

    def setUp(self):
        super().setUp()
        self.files = [str(make_pdf(self.tmp / f'{n}.pdf')) for n in (101838, 102879, 112291)]

    def test_files_arriving_one_by_one_open_the_merge_tool_once_with_all_of_them(self):
        for path in self.files:
            self.window.receive_print_files([path])
        self.assertIsNone(self.window.current_id)  # ainda esperando os outros chegarem
        self.wait_until(lambda: self.window.current_id == 'merge')
        self.assertEqual(self.window.pages['merge'].files, self.files)

    def test_the_same_file_twice_is_added_once(self):
        self.window.receive_print_files([self.files[0]])
        self.window.receive_print_files([self.files[0], self.files[1]])
        self.wait_until(lambda: self.window.current_id == 'merge')
        self.assertEqual(self.window.pages['merge'].files, self.files[:2])

    def test_a_request_without_files_only_brings_the_window_forward(self):
        with mock.patch.object(self.window, 'bring_to_front') as front:
            self.window.receive_print_files([])
        front.assert_called_once()
        self.assertFalse(self.window._incoming_timer.isActive())
        self.assertIsNone(self.window.current_id)

    def test_it_will_not_pull_you_out_of_another_tool_that_you_chose_to_stay_in(self):
        page = self.window.open_tool('split')
        page.add_paths([self.files[0]])  # trabalho não salvo
        with (
            mock.patch.object(self.window, 'ask_unsaved_to_leave', return_value='stay'),
            mock.patch.object(self.window, 'show_notice') as notice,
        ):
            self.assertFalse(self.window.open_print_with(self.files))
        notice.assert_called_once()
        self.assertEqual(self.window.current_id, 'split')
        self.assertNotIn('merge', self.window.pages)

    def test_it_leaves_the_other_tool_when_you_agree_and_prints_there(self):
        page = self.window.open_tool('split')
        page.add_paths([self.files[0]])
        with mock.patch.object(self.window, 'ask_unsaved_to_leave', return_value='discard'):
            self.assertTrue(self.window.open_print_with(self.files))
        self.assertEqual(self.window.current_id, 'merge')
        self.assertEqual(len(self.window.pages['merge'].files), 3)

    def test_files_are_added_to_a_print_screen_that_is_already_open(self):
        page = self.window.open_tool('merge')
        page.add_paths([self.files[0]])
        self.assertTrue(self.window.open_print_with(self.files[1:]))
        self.assertIs(self.window.pages['merge'], page)
        self.assertEqual(page.files, self.files[:1] + self.files[1:])

    def test_it_does_not_touch_a_print_job_in_progress(self):
        page = self.window.open_tool('merge')
        page.running = True
        with mock.patch.object(self.window, 'show_notice') as notice:
            self.assertFalse(self.window.open_print_with(self.files))
        notice.assert_called_once()
        self.assertEqual(page.files, [])
        page.running = False


class LeavingTests(QtTestCase):
    """Sair de uma ferramenta: protege a tarefa em andamento e o trabalho não salvo, e zera a tela ao sair."""

    def slow_tool(self):
        state = {'started': False, 'cancelled_inside': False}

        def run(source, dest, values, progress):
            state['started'] = True
            for _ in range(500):
                try:
                    progress(0.5, 'trabalhando')
                except jobs.Cancelled:
                    state['cancelled_inside'] = True
                    raise
                time.sleep(0.01)
            return ops.Result([Path(dest)], 'terminou')

        return SimpleNamespace(id='lenta', action='Executar', run=run), state

    def start_slow_job(self, page):
        tool, state = self.slow_tool()
        page.tool = tool
        page.start_worker([('a.pdf', self.tmp / 'saida.pdf')], {})
        self.wait_until(lambda: state['started'])
        return state

    def test_leaving_without_work_resets_the_tool(self):
        page = self.window.open_tool('merge')
        self.assertTrue(self.window.request_home())
        self.assertIsNone(self.window.current_id)
        self.assertNotIn('merge', self.window.pages)
        self.assertIsNot(self.window.open_tool('merge'), page)

    def test_chosen_files_ask_before_leaving_and_staying_keeps_them(self):
        page = self.window.open_tool('merge')
        page.add_paths([str(make_pdf(self.tmp / 'a.pdf'))])
        self.assertTrue(page.has_unsaved_work())
        with mock.patch.object(self.window, 'ask_unsaved_to_leave', return_value='stay') as ask:
            self.assertFalse(self.window.request_home())
        ask.assert_called_once()
        self.assertEqual(self.window.current_id, 'merge')
        self.assertEqual(len(page.files), 1)

    def test_discarding_leaves_and_the_tool_comes_back_empty(self):
        page = self.window.open_tool('merge')
        page.add_paths([str(make_pdf(self.tmp / 'a.pdf'))])
        with mock.patch.object(self.window, 'ask_unsaved_to_leave', return_value='discard'):
            self.assertTrue(self.window.request_home())
        fresh = self.window.open_tool('merge')
        self.assertIsNot(fresh, page)
        self.assertEqual(fresh.files, [])

    def test_escape_and_the_back_button_are_guarded_too(self):
        page = self.window.open_tool('merge')
        page.add_paths([str(make_pdf(self.tmp / 'a.pdf'))])
        with mock.patch.object(self.window, 'ask_unsaved_to_leave', return_value='stay') as ask:
            self.window.on_escape()
            QTest.mouseClick(page.back_button, Qt.LeftButton, Qt.NoModifier, page.back_button.rect().center())
            self.window.focus_search()
        self.assertEqual(ask.call_count, 3)
        self.assertEqual(self.window.current_id, 'merge')

    def test_files_that_were_already_processed_do_not_ask(self):
        page = self.window.open_tool('merge')
        page.add_paths([str(make_pdf(self.tmp / 'a.pdf')), str(make_pdf(self.tmp / 'b.pdf'))])
        page.dirty = False  # como depois de um processamento bem-sucedido
        with mock.patch.object(self.window, 'ask_unsaved_to_leave') as ask:
            self.assertTrue(self.window.request_home())
        ask.assert_not_called()

    def test_leaving_during_a_task_asks_and_staying_keeps_it_running(self):
        page = self.window.open_tool('merge')
        state = self.start_slow_job(page)
        self.addCleanup(lambda: (page.request_cancel(), self.wait_until(lambda: not page.running)))
        with mock.patch.object(self.window, 'ask_cancel_to_leave', return_value=False) as ask:
            self.assertFalse(self.window.request_home())
        ask.assert_called_once()
        self.assertTrue(page.running)
        self.assertFalse(page.cancel_event.is_set())
        self.assertEqual(self.window.current_id, 'merge')
        self.assertFalse(state['cancelled_inside'])

    def test_leaving_during_a_task_cancels_it_and_resets_the_tool(self):
        page = self.window.open_tool('merge')
        state = self.start_slow_job(page)
        with mock.patch.object(self.window, 'ask_cancel_to_leave', return_value=True):
            self.assertTrue(self.window.request_home())
        self.assertTrue(state['cancelled_inside'])
        self.assertIsNone(self.window.current_id)
        self.assertNotIn('merge', self.window.pages)
        self.assertFalse((self.tmp / 'saida.pdf').exists())
        self.assertIsNot(self.window.open_tool('merge'), page)

    def test_the_run_button_cancels_after_confirmation(self):
        page = self.window.open_tool('merge')
        state = self.start_slow_job(page)
        with mock.patch.object(page, 'confirm_cancel', return_value=False):
            page.on_run_clicked()
        self.assertTrue(page.running)
        with mock.patch.object(page, 'confirm_cancel', return_value=True):
            page.on_run_clicked()
        self.wait_until(lambda: not page.running)
        self.assertTrue(state['cancelled_inside'])
        self.assertIn('cancelada', page.message.text())
        self.assertEqual(page.run_button.text(), page.tool.action)
        self.assertTrue(page.run_button.isEnabled())


if __name__ == '__main__':
    unittest.main()
