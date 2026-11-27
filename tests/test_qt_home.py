"""Tela inicial da 4.0: favoritas, recentes, filtros por categoria, teclado, tema, diálogos e janela lembrada."""

import importlib.util
import os
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import _source  # coloca a raiz do projeto no sys.path

HAS_QT = importlib.util.find_spec('PySide6') is not None

if HAS_QT:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from rdf.core import settings
    from rdf.pdftools.registry import CATEGORIES, TOOLS
    from rdf.qt import motion, theme
    from rdf.qt.__main__ import create_app
    from rdf.qt.home import FAVORITES, RECENT
    from rdf.qt.window import MainWindow


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class HomeTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app([])

    def setUp(self):
        self.prefs = settings.reset()
        self.addCleanup(settings.reset)
        self.addCleanup(theme.apply, None, 'claro')
        patch = mock.patch.object(motion, '_enabled', False)
        patch.start()
        self.addCleanup(patch.stop)
        self.window = MainWindow()
        self.window.resize(1300, 760)
        self.window.show()
        self.addCleanup(self.close_window)
        self.home = self.window.home

    def close_window(self):
        from PySide6.QtCore import QEvent

        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)  # apaga de verdade: janelas velhas pesam nos testes

    def card(self, tool_id, section=None):
        cards = [card for card in self.home.cards if card.tool.id == tool_id]
        return cards[0] if section is None else cards[section]


class FavoritesTests(HomeTestCase):
    def test_the_star_marks_a_favorite_that_shows_up_first(self):
        row = self.card('compress')
        star = row.star_rect().center().toPoint()
        QTest.mouseClick(row, Qt.LeftButton, Qt.NoModifier, star)
        self.assertEqual(self.prefs.get('favorites'), ['compress'])
        self.assertEqual(self.home.section_titles[0], FAVORITES)
        self.assertEqual(self.home.cards[0].tool.id, 'compress')
        self.assertTrue(self.home.cards[0].favorite)
        self.assertIsNone(self.window.current_id)  # clicar na estrela não abre a ferramenta

    def test_ctrl_d_toggles_the_favorite_from_the_keyboard(self):
        row = self.card('ocr')
        row.setFocus()
        QTest.keyClick(row, Qt.Key_D, Qt.ControlModifier)
        self.assertTrue(self.prefs.is_favorite('ocr'))
        focused = self.window.focusWidget()
        self.assertEqual(focused.tool.id, 'ocr')  # o foco continua na mesma ferramenta
        QTest.keyClick(focused, Qt.Key_D, Qt.ControlModifier)
        self.assertFalse(self.prefs.is_favorite('ocr'))
        self.assertNotIn(FAVORITES, self.home.section_titles)

    def test_used_tools_appear_as_recent_after_coming_back(self):
        self.window.open_tool('split')
        self.window.request_home()
        self.assertEqual(self.home.section_titles[0], RECENT)
        self.assertEqual(self.home.cards[0].tool.id, 'split')

    def test_a_favorite_is_not_repeated_among_the_recent(self):
        self.prefs.toggle_favorite('split')
        self.window.open_tool('split')
        self.window.request_home()
        self.assertEqual(self.home.section_titles[:1], [FAVORITES])
        self.assertNotIn(RECENT, self.home.section_titles)

    def test_shortcut_sections_hide_while_searching(self):
        self.prefs.toggle_favorite('merge')
        self.home.refresh()
        self.home.search.edit.setText('senha')
        self.assertNotIn(FAVORITES, self.home.section_titles)


class FilterAndKeyboardTests(HomeTestCase):
    def test_category_chips_filter_the_list(self):
        self.home.chips['Segurança'].click()
        self.assertEqual(self.home.section_titles, ['Segurança'])
        self.home.chips['Todas'].click()
        self.assertEqual(self.home.section_titles, list(CATEGORIES))

    def test_enter_in_the_search_opens_the_best_match(self):
        self.home.search.edit.setText('comprimir')
        QTest.keyClick(self.home.search.edit, Qt.Key_Return)
        self.assertEqual(self.window.current_id, 'compress')

    def test_the_most_relevant_category_comes_first_while_searching(self):
        self.home.search.edit.setText('imagem')
        self.assertEqual(self.home.section_titles[0], 'Converter')

    def test_arrow_down_from_the_search_enters_the_list_and_arrows_move(self):
        self.home.search.focus_edit()
        QTest.keyClick(self.home.search.edit, Qt.Key_Down)
        first = self.window.focusWidget()
        self.assertIs(first, self.home.cards[0])
        QTest.keyClick(first, Qt.Key_Down)
        below = self.window.focusWidget()
        self.assertIsNot(below, first)
        self.assertGreater(below.mapToGlobal(below.rect().center()).y(), first.mapToGlobal(first.rect().center()).y())
        QTest.keyClick(below, Qt.Key_Up)
        self.assertIs(self.window.focusWidget(), first)
        QTest.keyClick(first, Qt.Key_Up)  # da primeira, sobe para a busca
        self.assertIs(self.window.focusWidget(), self.home.search.edit)

    def test_left_and_right_stay_on_the_same_line(self):
        self.home.layout_columns(force=True)
        self.assertGreaterEqual(self.home.columns, 2)
        start = next(card for card in self.home.cards if card.tool.id == 'merge')
        start.setFocus()
        QTest.keyClick(start, Qt.Key_Right)
        right = self.window.focusWidget()
        self.assertEqual(right.tool.id, 'split')
        QTest.keyClick(right, Qt.Key_Left)
        self.assertIs(self.window.focusWidget(), start)

    def test_an_empty_search_explains_and_suggests_words(self):
        self.home.search.edit.setText('xyzxyz')
        self.assertFalse(self.home.empty_label.isHidden())
        self.assertIn('xyzxyz', self.home.empty_label.text())


class ThemeAndDialogTests(HomeTestCase):
    def test_choosing_a_theme_applies_and_remembers_it(self):
        self.window.set_theme('escuro')
        self.assertTrue(theme.is_dark())
        self.assertEqual(theme.COLORS['bg'], theme.DARK['bg'])
        self.assertEqual(self.prefs.get('theme'), 'escuro')
        self.assertIn(theme.DARK['surface'], self.app.styleSheet())
        self.window.toggle_theme()
        self.assertFalse(theme.is_dark())
        self.assertEqual(self.prefs.get('theme'), 'claro')

    def test_the_theme_menu_offers_the_three_modes(self):
        menu = self.home.theme_menu()
        labels = [action.text() for action in menu.actions()]
        self.assertEqual(len(labels), 3)
        self.assertTrue(any(action.isChecked() for action in menu.actions()))
        received = []
        self.home.themeRequested.connect(received.append)
        menu.actions()[2].trigger()
        self.assertEqual(received, ['escuro'])

    def test_settings_change_preferences_right_away(self):
        dialog = self.window.make_settings_dialog()
        dialog.open_folder.setChecked(True)
        self.assertTrue(self.prefs.get('open_folder_after'))
        dialog.theme_combo.setCurrentIndex(2)
        self.assertEqual(self.prefs.get('theme'), 'escuro')
        self.assertTrue(theme.is_dark())
        self.prefs.toggle_favorite('merge')
        dialog.clear_button.click()
        self.assertEqual(self.prefs.get('favorites'), [])
        dialog.close()

    def test_about_and_shortcuts_dialogs_build(self):
        from rdf.qt import app_dialogs

        about = app_dialogs.about_dialog(self.window, None)
        self.assertIn('4.0', about.findChildren(type(self.home.empty_label))[1].text())
        shortcuts = app_dialogs.shortcuts_dialog(self.window)
        texts = [label.text() for label in shortcuts.findChildren(type(self.home.empty_label))]
        self.assertIn('F1', texts)
        self.assertIn('Ctrl+D', texts)
        names = [name for name, _version in app_dialogs.library_versions()]
        self.assertIn('PyMuPDF', names)

    def test_the_header_buttons_have_names_for_screen_readers(self):
        for button in (self.home.theme_button, self.home.settings_button, self.home.help_button):
            self.assertTrue(button.accessibleName())


class GeometryTests(HomeTestCase):
    def test_the_window_comes_back_where_it_was(self):
        self.window.resize(790, 560)  # cabe na tela falsa (800x600) dos testes e respeita o mínimo
        self.app.processEvents()
        self.window.save_geometry()
        self.assertTrue(self.prefs.get('window_geometry'))
        other = MainWindow()
        self.addCleanup(other.deleteLater)
        self.assertEqual((other.width(), other.height()), (790, 560))

    def test_a_broken_saved_size_is_ignored(self):
        self.prefs.set('window_geometry', 'isto não é base64 ☃')
        other = MainWindow()
        self.addCleanup(other.deleteLater)
        self.assertGreater(other.width(), 0)


class CatalogTests(unittest.TestCase):
    def test_every_tool_is_somewhere_on_the_home_screen(self):
        self.assertTrue(TOOLS)


if __name__ == '__main__':
    unittest.main()


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class MetadataPageTests(HomeTestCase):
    def test_the_current_information_fills_the_fields(self):
        import tempfile
        from pathlib import Path

        import fitz

        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        source = Path(folder.name) / 'meta.pdf'
        document = fitz.open()
        document.new_page()
        document.set_metadata({'title': 'Título antigo', 'author': 'Autor Fictício', 'creator': 'Editor X'})
        document.save(source)
        document.close()
        page = self.window.open_tool('metadata')
        page.add_paths([str(source)])
        self.assertEqual(page.widgets['title'].text(), 'Título antigo')
        self.assertEqual(page.widgets['author'].text(), 'Autor Fictício')
        self.assertIn('Editor X', page.info_label.text())
        page.clear_files()
        self.assertIn('Adicione', page.info_label.text())
