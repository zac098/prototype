"""Tudo o que o instalador usa: scripts, arquivos embutidos, pastas do executável e textos sem lixo."""

import importlib.util
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

import _source  # coloca a raiz do projeto no sys.path
from _source import ROOT
from rdf.core import config, ocr

CR_LF = bytes([13, 10])
BACKSLASH = chr(92)


def text_files():
    """Código, documentos e scripts versionados no projeto (sem pastas de build nem ambientes virtuais)."""
    skip = {'.venv', '.venv_build', '.git', '.claude', 'build', 'dist', 'resultados', 'installer_output'}
    patterns = ('*.py', '*.md', '*.txt', '*.bat', '*.iss', '*.toml')
    for pattern in patterns:
        for path in ROOT.rglob(pattern):
            relative = path.relative_to(ROOT)
            if skip.isdisjoint(relative.parts) and 'pdf pra testar programa' not in relative.parts:
                yield path


class BatchScriptTests(unittest.TestCase):
    """O cmd.exe não acha rótulos (goto) em .bat com finais de linha LF: o script precisa ser todo CRLF."""

    def setUp(self):
        self.script = (ROOT / 'packaging' / 'build_package.bat').read_bytes()

    def test_every_line_ends_with_crlf(self):
        lines = self.script.count(bytes([10]))
        self.assertGreater(lines, 100)
        self.assertEqual(self.script.count(CR_LF), lines)

    def test_gitattributes_keeps_it_that_way(self):
        rules = (ROOT / '.gitattributes').read_text(encoding='utf-8')
        self.assertIn('*.bat text eol=crlf', rules)

    def test_every_goto_has_its_label(self):
        text = self.script.decode('utf-8')
        labels = set(re.findall(r'^:([A-Z_]+)\s*$', text, flags=re.MULTILINE))
        targets = {t for t in re.findall(r'goto ([A-Za-z_]+)', text) if t.lower() != 'eof'}
        self.assertFalse(targets - labels, targets - labels)

    def test_it_checks_the_ocr_languages_and_builds_with_the_recipe(self):
        text = self.script.decode('utf-8')
        self.assertIn('tessdata' + BACKSLASH + 'por.traineddata', text)
        self.assertIn('tessdata' + BACKSLASH + 'eng.traineddata', text)
        self.assertIn('-m PyInstaller --noconfirm --clean "%ROOT%packaging' + BACKSLASH + 'rdf.spec"', text)
        self.assertIn('set "TESSERACT_DIR=', text)  # a receita lê a pasta do Tesseract desta variável

    def test_it_runs_the_self_test_and_delivers_both_versions(self):
        text = self.script.decode('utf-8')
        self.assertIn('RDF.exe" --autoteste "%SELFTEST%"', text)
        self.assertIn('goto SELFTEST_ERROR', text)
        self.assertIn('dist' + BACKSLASH + 'RDF_portatil.exe', text)


class InstallerScriptTests(unittest.TestCase):
    def test_the_installer_installs_the_folder_and_replaces_old_libraries(self):
        iss = (ROOT / 'packaging' / 'installer.iss').read_text(encoding='utf-8')
        self.assertIn('Source: "..' + BACKSLASH + 'dist' + BACKSLASH + 'RDF' + BACKSLASH + '*"; DestDir: "{app}"', iss)
        self.assertIn('recursesubdirs createallsubdirs', iss)
        # nada da versão anterior fica misturado com as bibliotecas novas
        self.assertIn('[InstallDelete]', iss)
        self.assertIn('Type: filesandordirs; Name: "{app}' + BACKSLASH + '_internal"', iss)

    def test_every_file_the_installer_needs_exists(self):
        iss = (ROOT / 'packaging' / 'installer.iss').read_text(encoding='utf-8')
        paths = re.findall(r'(?:Source: "|LicenseFile=|SetupIconFile=)([^";\r\n]+)', iss)
        self.assertGreaterEqual(len(paths), 4)
        built_by_pyinstaller = {'dist/RDF/*'}  # a pasta que o PyInstaller gera (RDF.exe + _internal)
        for raw in paths:
            normalized = raw.replace(BACKSLASH, '/')
            if normalized.endswith('DELIVERY_GUIDE.md') or normalized.lstrip('./') in built_by_pyinstaller:
                continue  # o guia é opcional (#if FileExists) e o .exe nasce do PyInstaller
            self.assertTrue((ROOT / 'packaging' / normalized).resolve().is_file(), raw)


class StrayCharacterTests(unittest.TestCase):
    def test_no_control_characters_hide_in_source_or_docs(self):
        """Um backspace dentro de 'packaging...build' já quebrou um caminho em documentação."""
        found = {}
        for path in text_files():
            data = path.read_bytes()
            bad = [c for c in data if c < 32 and c not in (9, 10, 13)]
            if bad:
                found[str(path.relative_to(ROOT))] = len(bad)
        self.assertEqual(found, {})


class FrozenFolderTests(unittest.TestCase):
    def test_from_source_the_base_folder_is_the_project_root(self):
        self.assertEqual(config.app_base_dir(), ROOT)
        self.assertTrue((config.app_base_dir() / 'pyproject.toml').is_file())

    def test_packaged_the_base_folder_is_where_the_exe_lives(self):
        exe = ROOT / 'dist' / 'RDF.exe'
        with mock.patch.object(sys, 'frozen', True, create=True), mock.patch.object(sys, 'executable', str(exe)):
            self.assertEqual(config.app_base_dir(), exe.parent.resolve())

    def test_the_manual_tesseract_file_is_read_from_the_exe_folder_when_packaged(self):
        exe = ROOT / 'dist' / 'RDF.exe'
        with mock.patch.object(sys, 'frozen', True, create=True), mock.patch.object(sys, 'executable', str(exe)):
            candidates = config.tesseract_candidates(config.app_base_dir())
        self.assertNotIn('Tesseract-OCR', str(candidates[1] or ''))  # sem arquivo manual: não inventa caminho

    def test_the_icon_is_found_from_source_and_from_the_bundle(self):
        icon = config.resource_path('assets', 'icone.ico')
        self.assertTrue(icon.is_file())
        with mock.patch.object(sys, '_MEIPASS', str(ROOT), create=True):
            self.assertEqual(config.resource_path('assets', 'icone.ico'), icon)
        fake_bundle = Path(__file__).parent
        with mock.patch.object(sys, '_MEIPASS', str(fake_bundle), create=True):
            self.assertEqual(config.resource_path('assets', 'icone.ico'), fake_bundle / 'assets' / 'icone.ico')

    def test_the_missing_tesseract_message_points_to_something_that_exists(self):
        self.assertNotIn('.bat', ocr.TESSERACT_MISSING_MESSAGE)
        self.assertIn('tesseract_path.txt', ocr.TESSERACT_MISSING_MESSAGE)


class EntryPointTests(unittest.TestCase):
    """O app é o Qt, e o instalador não leva o Tkinter."""

    HAS_QT = importlib.util.find_spec('PySide6') is not None

    @unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
    def test_the_default_entry_opens_the_qt_app(self):
        import rdf.__main__ as entry

        with mock.patch('rdf.qt.__main__.main', return_value=0) as qt_main:
            self.assertEqual(entry.main(), 0)
        qt_main.assert_called_once()

    def test_the_launcher_script_and_the_console_command_use_that_entry(self):
        launcher = (ROOT / 'rdf_app.py').read_text(encoding='utf-8')
        self.assertIn('from rdf.__main__ import main', launcher)
        self.assertIn('sys.exit(run())', launcher)
        self.assertIn('rdf = "rdf.__main__:main"', (ROOT / 'pyproject.toml').read_text(encoding='utf-8'))

    def test_the_build_leaves_tkinter_out(self):
        spec = (ROOT / 'packaging' / 'rdf.spec').read_text(encoding='utf-8')
        script = (ROOT / 'packaging' / 'build_package.bat').read_text(encoding='utf-8')
        self.assertIn("'tkinter',", spec)
        self.assertIn("'tkinterdnd2',", spec)
        self.assertNotIn('tkinterdnd2', script)
        self.assertNotIn('TCL_LIBRARY', script)  # sem a heurística de achar o Tcl/Tk, que falhava com o Python da Store
        self.assertIn('console=False', spec)  # janela, sem console preto atrás

    def test_the_installer_adds_the_print_entries_to_the_windows_menus(self):
        iss = (ROOT / 'packaging' / 'installer.iss').read_text(encoding='utf-8')
        self.assertIn('PrivilegesRequired=lowest', iss)  # HKA vira HKCU: nada de administrador
        key = r'Software\Classes\SystemFileAssociations\.pdf\shell\RDFImprimir'
        self.assertIn(f'Subkey: "{key}"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"', iss)
        self.assertIn('Flags: uninsdeletekey', iss)  # o desinstalador apaga a entrada
        self.assertIn('--imprimir ""%1""', iss)  # o arquivo clicado vai entre aspas (nomes com espaço)
        self.assertIn(f'Subkey: "{key}\\command"', iss)
        self.assertIn('{sendto}\\RDF - Imprimir arquivos', iss)
        self.assertIn('Parameters: "--imprimir"', iss)
        for task in ('contextmenu', 'sendto'):
            self.assertIn(f'Name: "{task}"', iss)
            self.assertIn(f'Tasks: {task}', iss)

    def test_the_flag_in_the_installer_is_the_one_the_app_reads(self):
        from rdf.qt.single_instance import PRINT_FLAG

        iss = (ROOT / 'packaging' / 'installer.iss').read_text(encoding='utf-8')
        self.assertIn(f' {PRINT_FLAG} ', iss)
        self.assertIn(f'Parameters: "{PRINT_FLAG}"', iss)

    def test_the_installer_offers_autostart_unchecked_and_cleans_it_up_on_uninstall(self):
        iss = (ROOT / 'packaging' / 'installer.iss').read_text(encoding='utf-8')
        task = next(line for line in iss.splitlines() if line.startswith('Name: "autostart"'))
        self.assertIn('Flags: unchecked', task)  # nunca liga sozinho: quem decide é o usuário
        run_key = r'Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "RDF"'
        entry = next(line for line in iss.splitlines() if run_key in line)
        self.assertIn('--segundo-plano', entry)
        self.assertIn('Flags: uninsdeletevalue', entry)
        self.assertIn('Tasks: autostart', entry)
        self.assertIn('Root: HKA', entry)  # por usuário (PrivilegesRequired=lowest): sem administrador
        # o valor também pode ter sido criado pelo menu da bandeja: o desinstalador apaga de qualquer jeito
        self.assertIn('procedure CurUninstallStepChanged', iss)
        self.assertIn(r"RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'RDF')", iss)

    def test_pyside6_is_a_pinned_dependency_and_matches_what_is_installed(self):
        requirements = (ROOT / 'requirements.txt').read_text(encoding='utf-8')
        match = re.search(r'^PySide6-Essentials==([\d.]+)$', requirements, flags=re.MULTILINE)
        self.assertIsNotNone(
            match,
            'PySide6-Essentials precisa estar fixado em requirements.txt (sem o metapacote PySide6: WebEngine e outros pesam centenas de MB)',
        )
        if self.HAS_QT:
            from importlib.metadata import version

            self.assertEqual(version('PySide6_Essentials'), match.group(1))
        self.assertFalse((ROOT / 'requirements-qt.txt').exists())  # agora é parte de requirements.txt


if __name__ == '__main__':
    unittest.main()
