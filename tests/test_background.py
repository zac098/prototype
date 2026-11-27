"""Início automático com o Windows: o registro (chave de teste), a bandeja, fechar para a bandeja e --segundo-plano.

Nenhum teste grava na chave Run de verdade: o registro só é tocado numa chave temporária própria, apagada no fim.
"""

import importlib.util
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import _source  # coloca a raiz do projeto no sys.path
from rdf.core import autostart

HAS_QT = importlib.util.find_spec('PySide6') is not None

if HAS_QT:
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon
    from rdf.qt import __main__ as entry
    from rdf.qt.__main__ import create_app
    from rdf.qt.renamer import RenamerPage
    from rdf.qt.tray import TrayController
    from rdf.qt.window import MainWindow


@unittest.skipUnless(autostart.supported(), 'só no Windows')
class AutostartRegistryTests(unittest.TestCase):
    def setUp(self):
        import winreg

        self.winreg = winreg
        self.key = rf'Software\RDF-teste-{os.getpid()}-{time.monotonic_ns()}'
        self.addCleanup(self.delete_test_key)
        self.real_before = self.read(autostart.RUN_KEY)

    def delete_test_key(self):
        try:
            self.winreg.DeleteKey(self.winreg.HKEY_CURRENT_USER, self.key)
        except OSError:
            pass
        # a chave Run de verdade não pode ter mudado por causa dos testes
        self.assertEqual(self.read(autostart.RUN_KEY), self.real_before)

    def read(self, key):
        try:
            with self.winreg.OpenKey(self.winreg.HKEY_CURRENT_USER, key) as handle:
                return self.winreg.QueryValueEx(handle, autostart.VALUE_NAME)[0]
        except OSError:
            return None

    def test_it_starts_disabled(self):
        self.assertFalse(autostart.is_enabled(self.key))

    def test_enabling_stores_the_current_command_and_disabling_removes_it(self):
        self.assertTrue(autostart.set_enabled(True, self.key))
        self.assertTrue(autostart.is_enabled(self.key))
        self.assertEqual(self.read(self.key), autostart.command())
        self.assertFalse(autostart.set_enabled(False, self.key))
        self.assertFalse(autostart.is_enabled(self.key))
        self.assertIsNone(self.read(self.key))

    def test_disabling_twice_or_without_the_key_is_harmless(self):
        self.assertFalse(autostart.set_enabled(False, self.key))
        autostart.set_enabled(True, self.key)
        autostart.set_enabled(False, self.key)
        self.assertFalse(autostart.set_enabled(False, self.key))

    def test_enabling_again_refreshes_the_command(self):
        with self.winreg.CreateKey(self.winreg.HKEY_CURRENT_USER, self.key) as handle:
            self.winreg.SetValueEx(handle, autostart.VALUE_NAME, 0, self.winreg.REG_SZ, 'C:/lugar/antigo/RDF.exe')
        autostart.set_enabled(True, self.key)
        self.assertEqual(self.read(self.key), autostart.command())

    def test_a_blank_value_does_not_count_as_enabled(self):
        with self.winreg.CreateKey(self.winreg.HKEY_CURRENT_USER, self.key) as handle:
            self.winreg.SetValueEx(handle, autostart.VALUE_NAME, 0, self.winreg.REG_SZ, '  ')
        self.assertFalse(autostart.is_enabled(self.key))

    def test_the_default_key_is_the_users_run_key(self):
        self.assertEqual(autostart.RUN_KEY, r'Software\Microsoft\Windows\CurrentVersion\Run')


class CommandTests(unittest.TestCase):
    def test_the_packaged_app_starts_hidden(self):
        with (
            mock.patch.object(sys, 'frozen', True, create=True),
            mock.patch.object(sys, 'executable', r'C:\Apps\RDF\RDF.exe'),
        ):
            self.assertEqual(autostart.command(), r'"C:\Apps\RDF\RDF.exe" --segundo-plano')

    def test_from_source_it_runs_the_launcher_script_with_the_flag(self):
        command = autostart.command()
        self.assertTrue(command.startswith('"'))
        self.assertIn('rdf_app.py', command)
        self.assertTrue(command.endswith(' --segundo-plano'))

    def test_the_flag_is_the_one_the_installer_uses(self):
        iss = (_source.ROOT / 'packaging' / 'installer.iss').read_text(encoding='utf-8')
        self.assertIn(f'"" {autostart.BACKGROUND_FLAG}"', iss)


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class BackgroundCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app([])

    def setUp(self):
        # Nada daqui encerra o programa de verdade nem lê o registro de verdade.
        quit_patch = mock.patch.object(QApplication, 'quit')
        self.quit = quit_patch.start()
        self.addCleanup(quit_patch.stop)
        self.enabled = False
        enabled_patch = mock.patch('rdf.qt.window.autostart.is_enabled', side_effect=lambda: self.enabled)
        enabled_patch.start()
        self.addCleanup(enabled_patch.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        from rdf.core import settings

        settings.reset()  # cada teste começa sem favoritas, recentes nem janela salva
        self.window = MainWindow()
        self.window.resize(900, 600)
        self.window.show()
        self.addCleanup(self.close_window)
        self.tray = mock.MagicMock()
        self.window.attach_tray(self.tray)

    def close_window(self):
        self.window._quitting = True
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()


class TrayMenuTests(BackgroundCase):
    def make_tray(self):
        with mock.patch('rdf.qt.tray.autostart') as module:
            module.is_enabled.side_effect = lambda: self.enabled
            module.supported.return_value = True
            tray = TrayController(self.window)
        self.autostart_module = module
        return tray

    def test_the_menu_has_the_expected_entries_in_order(self):
        tray = self.make_tray()
        texts = [action.text() for action in tray.menu.actions() if not action.isSeparator()]
        self.assertEqual(texts, ['Abrir o RDF', 'Imprimir ou unir PDFs', 'Iniciar com o Windows', 'Sair'])
        self.assertTrue(tray.autostart_action.isCheckable())

    def test_the_checkbox_follows_the_registry_each_time_the_menu_opens(self):
        tray = self.make_tray()
        self.assertFalse(tray.autostart_action.isChecked())
        self.enabled = True  # ligado pelo instalador depois que o app abriu
        with mock.patch('rdf.qt.tray.autostart.is_enabled', return_value=True):
            tray.menu.aboutToShow.emit()
        self.assertTrue(tray.autostart_action.isChecked())

    def test_toggling_writes_to_the_registry_and_tells_the_user(self):
        tray = self.make_tray()
        with (
            mock.patch('rdf.qt.tray.autostart.set_enabled') as set_enabled,
            mock.patch('rdf.qt.tray.autostart.is_enabled', return_value=True),
            mock.patch.object(tray, 'show_message') as message,
        ):
            tray.autostart_action.setChecked(True)
        set_enabled.assert_called_once_with(True)
        message.assert_called_once()
        with (
            mock.patch('rdf.qt.tray.autostart.set_enabled') as set_enabled,
            mock.patch('rdf.qt.tray.autostart.is_enabled', return_value=False),
            mock.patch.object(tray, 'show_message') as message,
        ):
            tray.autostart_action.setChecked(False)
        set_enabled.assert_called_once_with(False)
        message.assert_not_called()

    def test_the_entries_open_the_window_the_print_tool_and_quit(self):
        with (
            mock.patch.object(self.window, 'show_from_tray') as show,
            mock.patch.object(self.window, 'show_tool') as show_tool,
            mock.patch.object(self.window, 'quit_app') as quit_app,
        ):
            tray = self.make_tray()
            tray.open_action.trigger()
            tray.print_action.trigger()
            tray.quit_action.trigger()
        show.assert_called_once()
        show_tool.assert_called_once_with('merge')
        quit_app.assert_called_once()

    def test_a_click_or_double_click_on_the_icon_opens_the_window(self):
        with mock.patch.object(self.window, 'show_from_tray') as show:
            tray = self.make_tray()
            tray.on_activated(QSystemTrayIcon.DoubleClick)
            tray.on_activated(QSystemTrayIcon.Trigger)
            tray.on_activated(QSystemTrayIcon.Context)  # o botão direito só abre o menu
        self.assertEqual(show.call_count, 2)

    def test_availability_comes_from_the_system(self):
        with mock.patch.object(QSystemTrayIcon, 'isSystemTrayAvailable', return_value=False):
            self.assertFalse(TrayController.available())
        with mock.patch.object(QSystemTrayIcon, 'isSystemTrayAvailable', return_value=True):
            self.assertTrue(TrayController.available())


class CloseToTrayTests(BackgroundCase):
    def test_without_a_tray_closing_really_closes(self):
        self.window.attach_tray(None)
        self.enabled = True
        self.assertFalse(self.window.background_mode())
        self.assertTrue(self.window.close())
        self.quit.assert_called()

    def test_with_autostart_off_closing_really_closes_and_hides_the_icon(self):
        self.assertFalse(self.window.background_mode())
        self.assertTrue(self.window.close())
        self.tray.hide.assert_called_once()
        self.quit.assert_called()

    def test_with_autostart_on_closing_hides_to_the_tray_instead(self):
        self.enabled = True
        self.assertTrue(self.window.background_mode())
        self.assertFalse(self.window.close())  # o evento foi ignorado
        self.assertFalse(self.window.isVisible())
        self.quit.assert_not_called()

    def test_the_balloon_hint_appears_only_the_first_time(self):
        self.enabled = True
        self.window.close()
        self.window.show()
        self.window.close()
        self.assertEqual(self.tray.show_message.call_count, 1)

    def test_it_never_blocks_the_windows_shutdown_or_logoff(self):
        self.enabled = True
        with mock.patch.object(QGuiApplication, 'isSavingSession', return_value=True):
            self.assertTrue(self.window.is_ending_session())
            self.assertTrue(self.window.close())
        self.quit.assert_called()

    def test_the_tray_quit_entry_really_quits_even_in_background_mode(self):
        self.enabled = True
        self.assertTrue(self.window.quit_app())
        self.quit.assert_called()
        self.assertFalse(self.window._quitting)

    def test_quitting_from_the_tray_still_respects_a_running_analysis(self):
        self.enabled = True
        page = self.window.open_tool('renamer')
        page.analysis_running = True
        with mock.patch.object(RenamerPage, 'warn') as warn:
            self.assertFalse(self.window.quit_app())
        warn.assert_called_once()
        self.quit.assert_not_called()
        self.assertFalse(self.window._quitting)
        page.analysis_running = False

    def test_work_in_progress_survives_hiding_to_the_tray(self):
        self.enabled = True
        page = self.window.open_tool('merge')
        page.running = True
        self.window.close()
        self.assertIn('merge', self.window.pages)
        self.assertTrue(page.running)
        page.running = False


class ComingBackTests(BackgroundCase):
    def test_bring_to_front_shows_a_window_hidden_in_the_tray(self):
        self.window.hide()
        self.assertFalse(self.window.isVisible())
        self.window.bring_to_front()
        self.assertTrue(self.window.isVisible())

    def test_files_from_the_context_menu_wake_the_hidden_window(self):
        self.window.hide()
        self.window.receive_print_files([])
        self.assertTrue(self.window.isVisible())

    def test_show_tool_opens_the_tool_and_brings_the_window_back(self):
        self.window.hide()
        page = self.window.show_tool('merge')
        self.assertIs(self.window.pages['merge'], page)
        self.assertTrue(self.window.isVisible())

    def test_show_tool_does_not_pull_you_out_of_unsaved_work(self):
        page = self.window.open_tool('split')
        page.files, page.dirty = ['x.pdf'], True
        with mock.patch.object(self.window, 'ask_unsaved_to_leave', return_value='stay'):
            self.assertIsNone(self.window.show_tool('merge'))
        self.assertEqual(self.window.current_id, 'split')
        page.files = []


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class MainFlagTests(unittest.TestCase):
    def run_main(self, argv, *, primary=True, files=(), tray_available=True):
        app = mock.MagicMock()
        app.exec.return_value = 0
        with (
            mock.patch.object(entry, 'create_app', return_value=app),
            mock.patch.object(entry, 'files_from_args', return_value=list(files)),
            mock.patch.object(entry, 'InstanceServer') as server_class,
            mock.patch.object(entry, 'send_to_running', return_value=True) as send,
            mock.patch.object(entry, 'init') as init,
            mock.patch.object(entry, 'MainWindow') as window_class,
            mock.patch.object(entry, 'TrayController') as tray_class,
            # main() de verdade liga o gancho global de erros, lê as preferências e aplica o tema: aqui não
            mock.patch.object(entry, 'errors'),
            mock.patch.object(entry, 'settings'),
            mock.patch.object(entry, 'theme'),
        ):
            server_class.return_value.listen.return_value = primary
            tray_class.available.return_value = tray_available
            code = entry.main(argv)
        return SimpleResult(code, app, send, init, window_class.return_value, tray_class)

    def test_the_background_flag_starts_hidden_in_the_tray(self):
        run = self.run_main(['RDF.exe', '--segundo-plano'])
        run.window.show.assert_not_called()
        run.tray_class.assert_called_once()
        run.app.setQuitOnLastWindowClosed.assert_called_once_with(False)
        run.app.exec.assert_called_once()

    def test_without_a_tray_yet_the_background_flag_waits_for_it(self):
        with mock.patch.object(entry, 'wait_for_tray') as wait:
            run = self.run_main(['RDF.exe', '--segundo-plano'], tray_available=False)
        run.window.show.assert_not_called()  # ainda não: no login a bandeja pode demorar a aparecer
        run.tray_class.assert_not_called()
        wait.assert_called_once_with(run.window)

    def wait_for_tray(self, appears_after):
        from PySide6.QtCore import QObject
        from rdf.qt.__main__ import create_app

        app = create_app([])

        class Window(QObject):
            def __init__(self):
                super().__init__()
                self.tray = None
                self.show = mock.Mock()

            def attach_tray(self, tray):
                self.tray = tray

        window = Window()
        checks = []

        def available():
            checks.append(1)
            return appears_after is not None and len(checks) > appears_after

        with (
            mock.patch.object(entry.TrayController, 'available', side_effect=available),
            mock.patch.object(entry, 'TrayController', wraps=entry.TrayController) as tray_class,
        ):
            tray_class.available = available
            tray_class.side_effect = lambda win: 'bandeja'
            entry.wait_for_tray(window, seconds=5, interval_ms=5)
            deadline = time.monotonic() + 3
            while window.tray is None and not window.show.called and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.005)
        return window

    def test_a_tray_that_appears_after_login_keeps_rdf_hidden_in_it(self):
        window = self.wait_for_tray(appears_after=2)
        self.assertEqual(window.tray, 'bandeja')
        window.show.assert_not_called()

    def test_if_the_tray_never_appears_the_window_is_shown(self):
        window = self.wait_for_tray(appears_after=None)
        self.assertIsNone(window.tray)
        window.show.assert_called_once()

    def test_a_normal_start_shows_the_window(self):
        run = self.run_main(['RDF.exe'])
        run.window.show.assert_called_once()

    def test_files_make_the_window_appear_even_with_the_background_flag(self):
        run = self.run_main(['RDF.exe', '--segundo-plano', '--imprimir', 'a.pdf'], files=['C:/a.pdf'])
        run.window.show.assert_called_once()
        run.window.receive_print_files.assert_called_once_with(['C:/a.pdf'])

    def test_the_background_flag_with_the_app_already_open_just_exits(self):
        run = self.run_main(['RDF.exe', '--segundo-plano'], primary=False)
        self.assertEqual(run.code, 0)
        run.send.assert_not_called()  # não pede para a janela aparecer
        run.init.assert_not_called()
        run.tray_class.assert_not_called()

    def test_a_normal_second_launch_still_asks_the_open_window_to_come_forward(self):
        run = self.run_main(['RDF.exe'], primary=False)
        self.assertEqual(run.code, 0)
        run.send.assert_called_once_with([])


class SimpleResult:
    def __init__(self, code, app, send, init, window, tray_class):
        self.code, self.app, self.send, self.init, self.window, self.tray_class = (
            code,
            app,
            send,
            init,
            window,
            tray_class,
        )


if __name__ == '__main__':
    unittest.main()
