"""Qualquer arquivo como PDF: imagens, texto, HTML, SVG, CBZ e documentos do Office (com o Office simulado)."""

import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import _source  # coloca a raiz do projeto no sys.path
import fitz
from PIL import Image
from rdf.pdftools import ops, sources


def make_pdf(path, pages=1):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    for number in range(pages):
        document.new_page().insert_text((72, 72), f'p{number + 1}')
    document.save(path)
    document.close()
    return path


class TempCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.out = self.tmp / 'saida'

    def convert(self, source):
        return sources.convert_to_pdf(source, self.out / f'{Path(source).stem}.pdf')

    def pdf_text(self, path):
        with fitz.open(path) as document:
            return ' '.join(page.get_text() for page in document)

    def pdf_pages(self, path):
        with fitz.open(path) as document:
            return [(round(page.rect.width), round(page.rect.height)) for page in document]


class CatalogTests(unittest.TestCase):
    def test_the_supported_formats(self):
        for extension in ('.pdf', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.tif', '.txt', '.md', '.html', '.svg'):
            self.assertIn(extension, sources.ALL_EXTENSIONS, extension)
        for extension in ('.docx', '.xlsx', '.pptx', '.doc', '.xls', '.ppt', '.rtf', '.odt'):
            self.assertIn(extension, sources.ALL_EXTENSIONS, extension)
        self.assertNotIn('.exe', sources.ALL_EXTENSIONS)
        self.assertNotIn('.zip', sources.ALL_EXTENSIONS)

    def test_only_office_files_are_slow(self):
        self.assertTrue(sources.is_slow('a.DOCX'))
        self.assertTrue(sources.is_slow('a.xlsx'))
        self.assertFalse(sources.is_slow('a.png'))
        self.assertFalse(sources.is_slow('a.pdf'))

    def test_labels_for_the_list(self):
        labels = {
            'a.pdf': 'PDF',
            'a.JPG': 'Imagem',
            'a.txt': 'Texto',
            'a.html': 'HTML',
            'a.docx': 'Word',
            'a.xlsx': 'Excel',
            'a.pptx': 'PowerPoint',
        }
        for name, label in labels.items():
            self.assertEqual(sources.kind_label(name), label, name)

    def test_the_file_dialog_offers_everything_first(self):
        filters = sources.file_dialog_filters().split(';;')
        self.assertTrue(filters[0].startswith('Todos os suportados'))
        self.assertIn('*.docx', filters[0])
        self.assertTrue(filters[-1].startswith('Todos os arquivos'))


class ImageTests(TempCase):
    def test_every_image_format_becomes_one_page_per_frame(self):
        for extension, fmt in (('png', 'PNG'), ('jpg', 'JPEG'), ('bmp', 'BMP'), ('gif', 'GIF'), ('webp', 'WEBP')):
            with self.subTest(extension=extension):
                path = self.tmp / f'a.{extension}'
                Image.new('RGB', (600, 400), 'orange').save(path, fmt)
                self.assertEqual(len(self.pdf_pages(self.convert(path))), 1)

    def test_a_multipage_tiff_keeps_its_pages(self):
        frames = [Image.new('RGB', (200, 200), color) for color in ('red', 'green', 'blue')]
        path = self.tmp / 'multi.tif'
        frames[0].save(path, save_all=True, append_images=frames[1:])
        self.assertEqual(len(self.pdf_pages(self.convert(path))), 3)

    def test_a_big_photo_is_scaled_down_to_fit_an_a4_page_in_its_orientation(self):
        landscape = self.tmp / 'paisagem.jpg'
        Image.new('RGB', (4000, 3000), 'teal').save(landscape)
        width, height = self.pdf_pages(self.convert(landscape))[0]
        self.assertLessEqual(width, 842)
        self.assertLessEqual(height, 595)
        self.assertGreater(width, height)
        portrait = self.tmp / 'retrato.jpg'
        Image.new('RGB', (3000, 4000), 'teal').save(portrait)
        width, height = self.pdf_pages(self.convert(portrait))[0]
        self.assertLessEqual((width, height), (595, 842))
        self.assertGreater(height, width)

    def test_a_small_image_is_not_enlarged(self):
        path = self.tmp / 'pequena.png'
        Image.new('RGB', (150, 100), 'white').save(path)
        width, height = self.pdf_pages(self.convert(path))[0]
        self.assertLess(width, 150)  # 150 px a 150 dpi = 72 pt

    def test_the_exif_rotation_is_applied(self):
        picture = Image.new('RGB', (400, 600), 'white')
        picture.paste((0, 0, 0), (0, 0, 400, 150))
        exif = Image.Exif()
        exif[274] = 3
        path = self.tmp / 'scanner.jpg'
        picture.save(path, 'JPEG', exif=exif)
        with fitz.open(self.convert(path)) as document:
            pix = document[0].get_pixmap(matrix=fitz.Matrix(0.3, 0.3))
        top, bottom = pix.pixel(pix.width // 2, 2), pix.pixel(pix.width // 2, pix.height - 3)
        self.assertGreater(sum(top), 600)  # topo branco
        self.assertLess(sum(bottom), 150)  # faixa preta foi para baixo

    def test_transparency_gets_a_white_background(self):
        path = self.tmp / 'transparente.png'
        Image.new('RGBA', (300, 400), (0, 0, 0, 0)).save(path)
        with fitz.open(self.convert(path)) as document:
            pix = document[0].get_pixmap(matrix=fitz.Matrix(0.3, 0.3))
        self.assertGreater(sum(pix.pixel(pix.width // 2, pix.height // 2)), 740)

    def test_a_broken_image_says_so(self):
        path = self.tmp / 'quebrada.png'
        path.write_bytes(b'isto nao e uma imagem')
        with self.assertRaises(ops.PdfToolError) as caught:
            self.convert(path)
        self.assertIn('quebrada.png', str(caught.exception))


class TextAndMarkupTests(TempCase):
    def test_text_keeps_accents_and_wraps_onto_a4_pages(self):
        path = self.tmp / 'nota.txt'
        path.write_text('Acentuação: ção, é, ü — <tags> & "aspas"\n' * 120, encoding='utf-8')
        converted = self.convert(path)
        self.assertEqual(set(self.pdf_pages(converted)), {(595, 842)})
        self.assertGreater(len(self.pdf_pages(converted)), 1)
        text = self.pdf_text(converted)
        self.assertIn('Acentuação: ção', text)
        self.assertIn('<tags> & "aspas"', text)  # aparece como texto, não como marcação

    def test_windows_ansi_text_is_read_too(self):
        path = self.tmp / 'ansi.txt'
        path.write_bytes('Açúcar é doce\n'.encode('cp1252'))
        self.assertIn('Açúcar é doce', self.pdf_text(self.convert(path)))

    def test_markdown_log_and_csv_are_shown_as_plain_text(self):
        for name, content in (('a.md', '# Titulo\n\n**negrito**'), ('a.csv', 'a;b\n1;2'), ('a.log', 'linha de log')):
            with self.subTest(name=name):
                path = self.tmp / name
                path.write_text(content, encoding='utf-8')
                self.assertIn(content.splitlines()[0], self.pdf_text(self.convert(path)))

    def test_html_is_rendered(self):
        path = self.tmp / 'a.html'
        path.write_text('<html><body><h1>Título</h1><p>Parágrafo: ção</p></body></html>', encoding='utf-8')
        text = self.pdf_text(self.convert(path))
        self.assertIn('Título', text)
        self.assertIn('Parágrafo: ção', text)
        self.assertNotIn('<h1>', text)

    def test_svg_and_cbz(self):
        svg = self.tmp / 'a.svg'
        svg.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><rect width="200" height="100"/></svg>'
        )
        self.assertEqual(self.pdf_pages(self.convert(svg)), [(200, 100)])
        cbz = self.tmp / 'a.cbz'
        with zipfile.ZipFile(cbz, 'w') as archive:
            for number in range(3):
                image = self.tmp / f'p{number}.png'
                Image.new('RGB', (300, 400), 'red').save(image)
                archive.write(image, image.name)
        self.assertEqual(len(self.pdf_pages(self.convert(cbz))), 3)

    def test_an_empty_text_file_is_still_a_valid_pdf_or_a_clear_error(self):
        path = self.tmp / 'vazio.txt'
        path.write_text('', encoding='utf-8')
        try:
            converted = self.convert(path)
        except ops.PdfToolError as exc:
            self.assertIn('vazio.txt', str(exc))
        else:
            self.assertGreaterEqual(len(self.pdf_pages(converted)), 1)


class ConversionRulesTests(TempCase):
    def test_a_pdf_is_not_converted(self):
        with self.assertRaises(ops.PdfToolError):
            self.convert(make_pdf(self.tmp / 'a.pdf'))

    def test_unsupported_and_missing_files_give_clear_errors(self):
        odd = self.tmp / 'a.xyz'
        odd.write_bytes(b'x')
        with self.assertRaises(ops.PdfToolError) as caught:
            self.convert(odd)
        self.assertIn('Formato não suportado', str(caught.exception))
        with self.assertRaises(ops.PdfToolError) as caught:
            self.convert(self.tmp / 'sumiu.png')
        self.assertIn('sumiu.png', str(caught.exception))

    def test_no_half_written_file_is_left_after_a_failure(self):
        path = self.tmp / 'quebrada.png'
        path.write_bytes(b'x')
        with self.assertRaises(ops.PdfToolError):
            self.convert(path)
        self.assertEqual([p for p in self.out.rglob('*') if p.is_file()], [])


class CacheTests(TempCase):
    def png(self, name='foto.png', size=(300, 200)):
        path = self.tmp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', size, 'white').save(path)
        return path

    def test_the_converted_pdf_keeps_the_original_name_and_is_reused(self):
        source = self.png()
        first = sources.cached_pdf(source, self.out)
        self.assertEqual(first.name, 'foto.pdf')
        mtime = first.stat().st_mtime_ns
        self.assertEqual(sources.cached_pdf(source, self.out), first)
        self.assertEqual(first.stat().st_mtime_ns, mtime)  # não converteu de novo

    def test_a_changed_source_is_converted_again(self):
        source = self.png()
        first = sources.cached_pdf(source, self.out)
        os.utime(first, (1, 1))  # a conversão ficou velha
        Image.new('RGB', (900, 600), 'black').save(source)
        again = sources.cached_pdf(source, self.out)
        self.assertGreater(again.stat().st_mtime, 1)
        self.assertEqual(self.pdf_pages(again)[0][0], 432)  # a imagem nova: 900 px a 150 dpi = 432 pt

    def test_the_same_name_in_two_folders_does_not_collide(self):
        a = sources.cached_pdf(self.png('x/relatorio.png'), self.out)
        b = sources.cached_pdf(self.png('y/relatorio.png', (600, 400)), self.out)
        self.assertNotEqual(a, b)
        self.assertEqual((a.name, b.name), ('relatorio.pdf', 'relatorio.pdf'))

    def test_cleanup_only_touches_the_cache_folder(self):
        source = self.png()
        converted = sources.cached_pdf(source, self.out)
        sources.cleanup([converted, source, self.tmp], self.out)
        self.assertFalse(converted.exists())
        self.assertTrue(source.exists())  # o arquivo do usuário nunca é apagado

    def test_source_cache_prepares_fast_files_and_leaves_office_and_pdf_alone(self):
        cache = sources.SourceCache(self.out)
        photo = self.png()
        pdf = make_pdf(self.tmp / 'a.pdf')
        word = self.tmp / 'oficio.docx'
        word.write_bytes(b'x')
        prepared = cache.prepare(photo)
        self.assertTrue(Path(prepared).is_file())
        self.assertIsNone(cache.prepare(pdf))
        self.assertIsNone(cache.prepare(word))
        self.assertEqual(cache.pdf_for(photo), prepared)
        self.assertEqual(cache.pdf_for(pdf), str(pdf))
        self.assertIsNone(cache.pdf_for(word))  # ainda não convertido

    def test_resolve_converts_what_is_missing_and_handles_lists(self):
        cache = sources.SourceCache(self.out)
        photo, pdf = self.png(), make_pdf(self.tmp / 'a.pdf')
        resolved = cache.resolve([str(pdf), str(photo)])
        self.assertEqual(resolved[0], str(pdf))
        self.assertTrue(resolved[1].endswith('foto.pdf'))
        self.assertEqual(cache.pdf_for(photo), resolved[1])

    def test_forget_and_clear_remove_the_converted_files(self):
        cache = sources.SourceCache(self.out)
        a, b = self.png('a.png'), self.png('b.png')
        pa, pb = cache.prepare(a), cache.prepare(b)
        cache.forget([a])
        self.assertFalse(Path(pa).exists())
        self.assertTrue(Path(pb).exists())
        cache.clear()
        self.assertFalse(Path(pb).exists())
        self.assertFalse(self.out.exists())


class OfficeTests(TempCase):
    def setUp(self):
        super().setUp()
        self.word = self.tmp / 'oficio.docx'
        self.word.write_bytes(b'conteudo')

    def fake_office(self, *, returncode=0, stdout='', stderr='', write=True):
        """Faz de conta que o Office converteu: grava um PDF no destino que o app pediu."""
        calls = []

        def run(script, source, temp):
            calls.append((script, Path(source), Path(temp)))
            if write:
                make_pdf(temp, 2)
            return subprocess.CompletedProcess([], returncode, stdout, stderr)

        return calls, mock.patch.object(sources, '_run_powershell', side_effect=run)

    def test_word_excel_and_powerpoint_use_their_own_program(self):
        expected = {'a.docx': 'Word', 'a.rtf': 'Word', 'a.xlsx': 'Excel', 'a.xls': 'Excel', 'a.pptx': 'PowerPoint'}
        for name, app in expected.items():
            with self.subTest(name=name), mock.patch.object(sources, 'office_available', return_value=True):
                source = self.tmp / name
                source.write_bytes(b'x')
                calls, patch = self.fake_office()
                with patch:
                    converted = self.convert(source)
                self.assertIn(f'{app}.Application', calls[0][0])
                self.assertEqual(len(self.pdf_pages(converted)), 2)

    def test_the_file_path_never_goes_inside_the_script(self):
        evil = self.tmp / "relatorio'; Remove-Item $TEMP -Recurse; $(calc) `x.docx"
        evil.write_bytes(b'x')
        calls, patch = self.fake_office()
        with patch, mock.patch.object(sources, 'office_available', return_value=True):
            self.convert(evil)
        script, source, _temp = calls[0]
        self.assertNotIn('Remove-Item', script)
        self.assertNotIn(evil.name, script)
        self.assertEqual(source, evil)  # o caminho vai à parte, por variável de ambiente

    def test_macros_are_disabled_and_only_what_rdf_opened_is_closed(self):
        calls, patch = self.fake_office()
        with patch, mock.patch.object(sources, 'office_available', return_value=True):
            self.convert(self.word)
        script = calls[0][0]
        self.assertIn('AutomationSecurity = 3', script)  # sem macros
        self.assertIn('$meus -contains $_.Id', script)  # só fecha os processos que o RDF criou
        self.assertNotIn('$antes -notcontains $_.Id } | Stop-Process', script)  # nunca "tudo o que é novo"
        self.assertIn('Stop-Process', script)  # mas não deixa para trás o que o RDF abriu
        self.assertIn('Tentar', script)  # repete quando o Office responde "ocupado"
        self.assertIn('WINWORD', script)

    def test_the_pdf_is_written_to_a_temp_name_ending_in_pdf_and_then_moved(self):
        calls, patch = self.fake_office()
        with patch, mock.patch.object(sources, 'office_available', return_value=True):
            dest = self.convert(self.word)
        temp = calls[0][2]
        self.assertTrue(temp.name.endswith('.pdf'))  # o Excel acrescenta .pdf a qualquer outro final
        self.assertNotEqual(temp, dest)
        self.assertFalse(temp.exists())
        self.assertTrue(dest.is_file())

    def test_without_office_the_message_names_the_program(self):
        with mock.patch.object(sources, 'office_available', return_value=False):
            with self.assertRaises(ops.PdfToolError) as caught:
                self.convert(self.word)
        self.assertIn('Microsoft Word', str(caught.exception))
        self.assertIn('oficio.docx', str(caught.exception))

    def test_a_failed_conversion_reports_the_reason_and_leaves_nothing(self):
        calls, patch = self.fake_office(returncode=1, stderr='Exceção: o arquivo está corrompido', write=False)
        with patch, mock.patch.object(sources, 'office_available', return_value=True):
            with self.assertRaises(ops.PdfToolError) as caught:
                self.convert(self.word)
        self.assertIn('Word não conseguiu converter', str(caught.exception))
        self.assertIn('corrompido', str(caught.exception))
        self.assertEqual([p for p in self.out.rglob('*') if p.is_file()], [])

    def test_a_password_protected_document_says_so(self):
        _calls, patch = self.fake_office(returncode=1, stderr='A senha está incorreta', write=False)
        with patch, mock.patch.object(sources, 'office_available', return_value=True):
            with self.assertRaises(ops.PdfToolError) as caught:
                self.convert(self.word)
        self.assertIn('protegido por senha', str(caught.exception))

    def test_an_empty_output_counts_as_failure(self):
        def run(script, source, temp):
            Path(temp).write_bytes(b'')
            return subprocess.CompletedProcess([], 0, '', '')

        with mock.patch.object(sources, '_run_powershell', side_effect=run):
            with mock.patch.object(sources, 'office_available', return_value=True):
                with self.assertRaises(ops.PdfToolError):
                    self.convert(self.word)

    def test_a_timeout_is_reported(self):
        with (
            mock.patch.object(sources, 'office_available', return_value=True),
            mock.patch.object(sources.subprocess, 'run', side_effect=subprocess.TimeoutExpired('powershell', 1)),
        ):
            with self.assertRaises(ops.PdfToolError) as caught:
                self.convert(self.word)
        self.assertIn('demorou mais de', str(caught.exception))

    def test_the_real_office_converts_a_word_document(self):
        """Só roda com RDF_TEST_OFFICE=1 (abre o Word de verdade, em segundo plano, e leva alguns segundos)."""
        if os.environ.get('RDF_TEST_OFFICE') != '1' or not sources.office_available(self.word):
            self.skipTest('defina RDF_TEST_OFFICE=1 em um computador com o Microsoft Word')
        docx = self.tmp / 'real.docx'
        with zipfile.ZipFile(docx, 'w') as archive:
            archive.writestr(
                '[Content_Types].xml',
                '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
            )
            archive.writestr(
                '_rels/.rels',
                '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                'Target="word/document.xml"/></Relationships>',
            )
            archive.writestr(
                'word/document.xml',
                '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t>Documento com acentuação: ção</w:t></w:r></w:p></w:body></w:document>',
            )
        self.assertIn('acentuação: ção', self.pdf_text(self.convert(docx)))


if __name__ == '__main__':
    unittest.main()
