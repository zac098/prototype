"""Atualização pela interface (rdf/qt/updater.py): aviso na tela inicial, janela de download e instalação.

Nada aqui usa a internet: a procura e o download são funções falsas.
"""

import importlib.util
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import _source  # coloca a raiz do projeto no sys.path
from rdf.core import settings

HAS_QT = importlib.util.find_spec('PySide6') is not None

if HAS_QT:
    from PySide6.QtWidgets import QApplication

    from rdf.core.updates import Release, UpdateError
    from rdf.qt import updater
    from rdf.qt.__main__ import create_app


def make_release(version='9.1.0', installer=True):
    return Release(
        version=version,
        notes='## Novidades\n- Abre mais rápido',
        page_url='https://github.com/zac098/prototype/releases/tag/v' + version,
        installer_url='https://github.com/x/RDF_Setup.exe' if installer else '',
        installer_name='RDF_Setup_9.1.0.exe' if installer else '',
        installer_size=50 * 1024 * 1024 if installer else 0,
        checksums_url='https://github.com/x/SHA256SUMS.txt' if installer else '',
    )


def wait_until(condition, seconds=10):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    QApplication.processEvents()
    return condition()


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class QtCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app([])

    def setUp(self):
        settings.reset()
        self.addCleanup(settings.reset)


class ControllerTests(QtCase):
    def controller(self, check):
        controller = updater.UpdateController(check=check)
        self.addCleanup(controller.deleteLater)
        self.events = []
        controller.available.connect(lambda release: self.events.append(('nova', release.version)))
        controller.upToDate.connect(lambda: self.events.append(('em dia',)))
        controller.failed.connect(lambda message: self.events.append(('falhou', message)))
        return controller

    def test_a_new_version_is_announced_and_kept(self):
        controller = self.controller(lambda: make_release())
        self.assertTrue(controller.check(manual=False))
        self.assertTrue(wait_until(lambda: self.events))
        self.assertEqual(self.events, [('nova', '9.1.0')])
        self.assertEqual(controller.release.version, '9.1.0')
        self.assertFalse(controller.checking)

    def test_only_a_check_the_user_asked_for_says_there_is_nothing_new(self):
        controller = self.controller(lambda: None)
        controller.check(manual=False)
        self.assertTrue(wait_until(lambda: not controller.checking))
        self.assertEqual(self.events, [])  # a automática não incomoda ninguém
        controller.check(manual=True)
        self.assertTrue(wait_until(lambda: self.events))
        self.assertEqual(self.events, [('em dia',)])

    def test_without_internet_only_the_manual_check_complains(self):
        def offline():
            raise UpdateError('Não foi possível falar com o GitHub (sem rede).')

        controller = self.controller(offline)
        controller.check(manual=False)
        self.assertTrue(wait_until(lambda: not controller.checking))
        self.assertEqual(self.events, [])
        controller.check(manual=True)
        self.assertTrue(wait_until(lambda: self.events))
        self.assertEqual(self.events[0][0], 'falhou')
        self.assertIn('GitHub', self.events[0][1])

    def test_an_unexpected_error_never_escapes(self):
        controller = self.controller(lambda: 1 / 0)
        with self.assertLogs('rdf', 'ERROR'):  # vai para o log, com o rastro
            controller.check(manual=True)
            self.assertTrue(wait_until(lambda: self.events))
        self.assertEqual(self.events[0][0], 'falhou')

    def test_the_automatic_check_respects_the_setting(self):
        calls = []
        controller = self.controller(lambda: calls.append(1))
        settings.current().set('check_updates', False)
        controller.check_automatically()
        self.assertFalse(controller.checking)
        settings.current().set('check_updates', True)
        controller.check_automatically()
        self.assertTrue(wait_until(lambda: calls))

    def test_two_requests_at_once_make_one_check(self):
        gate = threading.Event()
        calls = []

        def slow():
            calls.append(1)
            gate.wait(5)

        controller = self.controller(slow)
        self.assertTrue(controller.check(manual=False))
        self.assertFalse(controller.check(manual=True))  # a que já está em andamento responde pelas duas
        gate.set()
        self.assertTrue(wait_until(lambda: self.events))
        self.assertEqual(calls, [1])
        self.assertEqual(self.events, [('em dia',)])  # e responde como pedida pelo usuário


class BannerTests(QtCase):
    def test_the_banner_shows_the_version_and_can_be_closed(self):
        banner = updater.UpdateBanner()
        self.addCleanup(banner.deleteLater)
        seen = []
        banner.updateRequested.connect(lambda: seen.append('atualizar'))
        banner.dismissed.connect(lambda: seen.append('fechou'))
        self.assertTrue(banner.isHidden())
        banner.show_release(make_release())
        self.assertFalse(banner.isHidden())
        self.assertIn('9.1.0', banner.title.text())
        banner.update_button.click()
        banner.close_button.click()
        self.assertEqual(seen, ['atualizar', 'fechou'])
        self.assertTrue(banner.isHidden())


class DialogTests(QtCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def dialog(self, release=None, installed=True, download=None):
        dialog = updater.UpdateDialog(
            release or make_release(), installed=installed, download=download, folder=self.tmp
        )
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_the_portable_copy_opens_the_release_page(self):
        dialog = self.dialog(installed=False)
        self.assertEqual(dialog.primary.text(), 'Abrir a página da versão')
        self.assertIn('portátil', dialog.info.text())
        with mock.patch.object(updater.QDesktopServices, 'openUrl') as opened:
            dialog.primary.click()
        self.assertEqual(opened.call_args[0][0].toString(), make_release().page_url)
        self.assertFalse(dialog.install_now)

    def test_download_then_install(self):
        def download(release, folder, progress, cancelled):
            progress(25, 100)
            path = Path(folder) / release.installer_name
            path.write_bytes(b'MZ')
            progress(100, 100)
            return path

        dialog = self.dialog(download=download)
        self.assertEqual(dialog.primary.text(), 'Baixar e instalar')
        self.assertIn('50 MB', dialog.info.text())
        dialog.primary.click()
        self.assertTrue(wait_until(lambda: dialog.state == 'ready'))
        self.assertEqual(dialog.primary.text(), 'Instalar agora')
        self.assertEqual(dialog.status.property('tone'), 'ok')
        dialog.primary.click()
        self.assertTrue(dialog.install_now)
        self.assertEqual(Path(dialog.installer).name, 'RDF_Setup_9.1.0.exe')

    def test_a_failed_download_can_be_tried_again(self):
        def download(release, folder, progress, cancelled):
            raise UpdateError('O arquivo baixado não confere com o publicado (veio corrompido). Tente de novo.')

        dialog = self.dialog(download=download)
        dialog.primary.click()
        self.assertTrue(wait_until(lambda: dialog.primary.text() == 'Tentar de novo'))
        self.assertEqual(dialog.state, 'idle')
        self.assertEqual(dialog.status.property('tone'), 'error')
        self.assertIn('corrompido', dialog.status.text())
        self.assertFalse(dialog.install_now)

    def test_cancel_stops_the_download(self):
        def download(release, folder, progress, cancelled):
            deadline = time.monotonic() + 5
            while not cancelled() and time.monotonic() < deadline:
                time.sleep(0.005)
            from rdf.core.updates import Cancelled

            raise Cancelled('Download cancelado.')

        dialog = self.dialog(download=download)
        dialog.primary.click()
        self.assertEqual(dialog.secondary.text(), 'Cancelar')
        dialog.secondary.click()
        self.assertTrue(wait_until(lambda: dialog.state == 'idle'))
        self.assertEqual(dialog.primary.text(), 'Baixar e instalar')
        self.assertTrue(dialog.wait_download(5000))

    def test_a_release_without_installer_points_to_the_page(self):
        dialog = self.dialog(make_release(installer=False), installed=True)
        self.assertEqual(dialog.primary.text(), 'Abrir a página da versão')


class WindowTests(QtCase):
    def setUp(self):
        super().setUp()
        from rdf.qt.window import MainWindow

        self.window = MainWindow()
        self.addCleanup(self.window.deleteLater)
        self.window.updater._check = lambda: make_release()

    def test_a_check_asked_by_the_user_opens_the_details_when_found(self):
        dialog = mock.Mock(install_now=False, installer=None)
        with mock.patch.object(self.window, 'make_update_dialog', return_value=dialog) as make:
            self.window.check_for_updates()
            self.assertTrue(wait_until(lambda: make.called))
        dialog.exec.assert_called_once()
        self.assertFalse(self.window.home.update_banner.isHidden())  # e o aviso fica na tela inicial

    def test_nothing_new_or_no_internet_get_a_clear_answer(self):
        self.window.updater._check = lambda: None
        with mock.patch.object(self.window, 'show_notice') as notice:
            self.window.check_for_updates()
            self.assertTrue(wait_until(lambda: notice.called))
        self.assertIn('versão mais nova', notice.call_args[0][1])

        def offline():
            raise UpdateError('Não foi possível falar com o GitHub (sem rede).')

        self.window.updater._check = offline
        with mock.patch.object(updater_window_box(), 'warning') as warning:
            self.window.check_for_updates()
            self.assertTrue(wait_until(lambda: warning.called))
        self.assertIn('sem rede', warning.call_args[0][2])

    def test_the_automatic_check_only_shows_the_banner(self):
        with mock.patch.object(self.window, 'make_update_dialog') as make:
            self.window.updater.check(manual=False)
            self.assertTrue(wait_until(lambda: not self.window.home.update_banner.isHidden()))
        make.assert_not_called()

    def test_installing_closes_the_app_first_and_then_runs_the_installer(self):
        with (
            mock.patch.object(self.window, 'quit_app', return_value=True) as quit_app,
            mock.patch('rdf.qt.window.launch_installer') as launch,
        ):
            self.assertTrue(self.window.install_update('C:/temp/RDF_Setup_9.1.0.exe'))
        quit_app.assert_called_once()
        launch.assert_called_once_with('C:/temp/RDF_Setup_9.1.0.exe')

    def test_if_the_user_stays_nothing_is_installed(self):
        with (
            mock.patch.object(self.window, 'quit_app', return_value=False),
            mock.patch('rdf.qt.window.launch_installer') as launch,
            mock.patch.object(self.window, 'show_notice') as notice,
        ):
            self.assertFalse(self.window.install_update('C:/temp/RDF_Setup_9.1.0.exe'))
        launch.assert_not_called()
        self.assertIn('adiada', notice.call_args[0][0])

    def test_the_help_menu_and_the_settings_offer_a_check(self):
        menu = self.window.home.help_menu()
        self.addCleanup(menu.deleteLater)
        self.assertIn('Procurar atualizações', [action.text() for action in menu.actions()])
        dialog = self.window.make_settings_dialog()
        self.addCleanup(dialog.deleteLater)
        self.assertTrue(dialog.check_updates.isChecked())
        dialog.check_updates.setChecked(False)
        self.assertFalse(settings.current().get('check_updates'))
        with mock.patch.object(self.window.updater, 'check') as check:
            dialog.updates_button.click()
        check.assert_called_once_with(manual=True)


def updater_window_box():
    from rdf.qt import window

    return window.QMessageBox


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class LaunchTests(unittest.TestCase):
    def test_the_installer_is_started_detached_with_the_silent_options(self):
        with mock.patch('subprocess.Popen') as popen:
            updater.launch_installer(Path('C:/temp/RDF_Setup_9.1.0.exe'))
        command = popen.call_args[0][0]
        self.assertIn('/SILENT', command)
        self.assertTrue(popen.call_args[1]['close_fds'])


if __name__ == '__main__':
    unittest.main()
