"""Receita do executável (packaging/rdf.spec) e o que fica de fora dele (packaging/bundle_rules.py).

O que estas regras tiram nunca é usado pelo RDF; o CI confere de verdade rodando o executável com --autoteste. Aqui
ficam as garantias que não dependem do Windows: o que sai, o que fica e como as DLLs do Tesseract são escolhidas.
"""

import sys
import tempfile
import unittest
from pathlib import Path

from _source import ROOT

sys.path.insert(0, str(ROOT / 'packaging'))
import bundle_rules  # noqa: E402

SPEC = (ROOT / 'packaging' / 'rdf.spec').read_text(encoding='utf-8')


class KeepRulesTests(unittest.TestCase):
    def test_what_the_rdf_never_uses_is_left_out(self):
        for dest in (
            r'PySide6\opengl32sw.dll',
            r'PySide6\d3dcompiler_47.dll',
            r'cv2\opencv_videoio_ffmpeg4110_64.dll',
            r'cv2\data\haarcascade_frontalface_default.xml',
            r'PySide6\plugins\tls\qschannelbackend.dll',
            r'PySide6\plugins\platforms\qoffscreen.dll',
            r'PySide6\translations\qtbase_de.qm',
            r'PySide6\translations\qt_help_pt_BR.qm',
            r'pymupdf\mupdf-devel\lib\mupdfcpp64.lib',
            r'pymupdf\mupdf-devel\include\mupdf\fitz.h',
            r'PIL\_avif.cp313-win_amd64.pyd',
            'libcrypto-3-x64.dll',  # OpenSSL do Qt (o HTTPS do RDF é pelo Python)
        ):
            with self.subTest(dest=dest):
                self.assertFalse(bundle_rules.should_keep(dest))

    def test_what_the_rdf_needs_stays(self):
        for dest in (
            r'PySide6\Qt6Core.dll',
            r'PySide6\Qt6Network.dll',  # uma janela só: o canal local entre os processos
            r'PySide6\plugins\platforms\qwindows.dll',
            r'PySide6\plugins\imageformats\qico.dll',  # o ícone do app
            r'PySide6\plugins\imageformats\qsvg.dll',
            r'PySide6\plugins\iconengines\qsvgicon.dll',
            r'PySide6\translations\qtbase_pt_BR.qm',  # Sim e Não em português
            r'cv2\cv2.pyd',
            r'pymupdf\mupdfcpp64.dll',
            r'Tesseract-OCR\tesseract.exe',
            'assets/icone.ico',
            'libcrypto-3.dll',  # OpenSSL do Python (_ssl): a atualização usa
            'libssl-3.dll',
        ):
            with self.subTest(dest=dest):
                self.assertTrue(bundle_rules.should_keep(dest))

    def test_filter_keeps_the_pyinstaller_entries_untouched(self):
        toc = [
            (r'PySide6\Qt6Gui.dll', r'C:\py\PySide6\Qt6Gui.dll', 'BINARY'),
            (r'PySide6\opengl32sw.dll', r'C:\py\PySide6\opengl32sw.dll', 'BINARY'),
        ]
        self.assertEqual(bundle_rules.filter_toc(toc), toc[:1])


class TesseractTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)
        names = (
            'tesseract.exe',
            'libtesseract-5.dll',
            'libleptonica-6.dll',
            'libpng16-16.dll',
            'zlib1.dll',
            'libicudt74.dll',  # só os programas de treino usam
            'text2image.exe',
            'libpango-1.0-0.dll',
        )
        for name in names:
            (self.folder / name).write_bytes(b'MZ')
        tessdata = self.folder / 'tessdata'
        (tessdata / 'configs').mkdir(parents=True)
        for name in ('por.traineddata', 'eng.traineddata', 'osd.traineddata', 'spa.traineddata', 'pdf.ttf'):
            (tessdata / name).write_bytes(b'x')
        for name in ('pdf', 'tsv', 'hocr'):
            (tessdata / 'configs' / name).write_text('config', encoding='utf-8')
        # Quem importa quem (como no cabeçalho dos arquivos); nomes do Windows ficam de fora sozinhos.
        self.graph = {
            'tesseract.exe': ['LIBTESSERACT-5.DLL', 'KERNEL32.dll', 'msvcrt.dll'],
            'libtesseract-5.dll': ['libleptonica-6.dll', 'zlib1.dll'],
            'libleptonica-6.dll': ['libpng16-16.dll', 'libtesseract-5.dll'],  # ciclo: não pode travar
            'libpng16-16.dll': ['zlib1.dll'],
            'zlib1.dll': [],
        }

    def read_imports(self, path):
        return self.graph.get(Path(path).name, [])

    def test_only_the_dlls_tesseract_loads_are_kept(self):
        self.assertEqual(
            bundle_rules.dll_closure(self.folder, read_imports=self.read_imports),
            ['libleptonica-6.dll', 'libpng16-16.dll', 'libtesseract-5.dll', 'zlib1.dll'],
        )

    def test_the_bundle_gets_the_program_its_dlls_two_languages_and_the_configs(self):
        files = bundle_rules.tesseract_files(self.folder, read_imports=self.read_imports)
        bundled = {f'{dest}/{source.name}' for source, dest in files}
        self.assertIn('Tesseract-OCR/tesseract.exe', bundled)
        self.assertIn('Tesseract-OCR/libtesseract-5.dll', bundled)
        self.assertIn('Tesseract-OCR/tessdata/por.traineddata', bundled)
        self.assertIn('Tesseract-OCR/tessdata/eng.traineddata', bundled)
        self.assertIn('Tesseract-OCR/tessdata/pdf.ttf', bundled)  # PDF pesquisável (ferramenta OCR)
        self.assertIn('Tesseract-OCR/tessdata/configs/tsv', bundled)  # leitura com posições (pytesseract)
        for left_out in (
            'libicudt74.dll',
            'text2image.exe',
            'libpango-1.0-0.dll',
            'osd.traineddata',
            'spa.traineddata',
        ):
            self.assertFalse(any(item.endswith('/' + left_out) for item in bundled), left_out)

    def test_the_tesseract_enters_after_the_analysis_with_full_destinations(self):
        toc = bundle_rules.tesseract_toc(self.folder, read_imports=self.read_imports)
        entries = {dest: kind for dest, _source, kind in toc}
        self.assertEqual(entries['Tesseract-OCR/tesseract.exe'], 'BINARY')
        self.assertEqual(entries['Tesseract-OCR/zlib1.dll'], 'BINARY')
        self.assertEqual(entries['Tesseract-OCR/tessdata/por.traineddata'], 'DATA')
        self.assertTrue(all(dest.startswith('Tesseract-OCR/') for dest in entries))  # nada na pasta principal

    def test_a_missing_language_stops_the_build(self):
        (self.folder / 'tessdata' / 'por.traineddata').unlink()
        with self.assertRaisesRegex(FileNotFoundError, 'por'):
            bundle_rules.tesseract_files(self.folder, read_imports=self.read_imports)

    def test_a_folder_without_tesseract_stops_the_build(self):
        (self.folder / 'tesseract.exe').unlink()
        with self.assertRaisesRegex(FileNotFoundError, 'tesseract.exe'):
            bundle_rules.tesseract_files(self.folder, read_imports=self.read_imports)


class SpecTests(unittest.TestCase):
    def test_both_deliveries_come_from_one_recipe(self):
        self.assertIn("COLLECT(installed, a.binaries, a.datas + tesseract, name='RDF'", SPEC)
        self.assertIn("name='RDF_portatil'", SPEC)
        self.assertIn('exclude_binaries=True', SPEC)  # a pasta: as bibliotecas ficam ao lado, não dentro do .exe

    def test_screens_imported_by_name_are_bundled(self):
        """A abertura rápida importa as telas e os módulos pesados pelo nome: o PyInstaller não os veria sozinho."""
        self.assertIn("collect_submodules('rdf')", SPEC)
        from rdf.qt import __main__ as entry
        from rdf.qt import window

        named = [
            window.RENAMER_PAGE[0],
            window.DEFAULT_PAGE[0],
            *(module for module, _ in window.CUSTOM_PAGES.values()),
        ]
        named += [name for name in entry.PRELOAD_MODULES if name.startswith('rdf.')]
        for module in named:
            with self.subTest(module=module):
                self.assertTrue(module.startswith('rdf.'))
                self.assertTrue((ROOT / (module.replace('.', '/') + '.py')).is_file())
        third_party = {name.split('.')[0] for name in entry.PRELOAD_MODULES if not name.startswith('rdf.')}
        self.assertTrue(third_party <= {'fitz', 'PIL', 'numpy', 'cv2', 'pytesseract'})  # todos já usados pelo rdf

    def test_the_tesseract_is_bundled_as_plain_files_with_the_filter(self):
        self.assertIn('tesseract = bundle_rules.tesseract_toc(TESSERACT_DIR)', SPEC)
        self.assertIn('a.datas + tesseract', SPEC)  # depois da análise: sem DLLs repetidas na pasta principal
        self.assertNotIn('tesseract_files(TESSERACT_DIR)', SPEC)
        self.assertIn('a.binaries = bundle_rules.filter_toc(a.binaries)', SPEC)
        self.assertIn('a.datas = bundle_rules.filter_toc(a.datas)', SPEC)
        self.assertIn("(ICON, 'assets')", SPEC)

    def test_the_exe_carries_the_app_version_for_windows(self):
        self.assertIn("StringStruct('ProductVersion', APP_VERSION)", SPEC)
        self.assertIn('upx=False', SPEC)  # UPX costuma disparar falso positivo de antivírus


if __name__ == '__main__':
    unittest.main()
