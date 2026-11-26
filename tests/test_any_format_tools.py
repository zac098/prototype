"""As ferramentas e a impressão aceitam imagens, texto e documentos do Office (convertidos para PDF)."""

import unittest
from pathlib import Path
from unittest import mock

import _source  # coloca a raiz do projeto no sys.path
import fitz
from PIL import Image
from rdf.core import config
from rdf.pdftools import ops, sources
from test_qt_prototype import HAS_QT, QtTestCase, make_pdf


def office_that_writes_two_pages(source, dest):
    make_pdf(dest, 2)


class AnyFormatCase(QtTestCase):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(config, 'CONVERT_DIR', self.tmp / 'convertidos')
        patch.start()
        self.addCleanup(patch.stop)
        office = mock.patch.object(sources, 'office_available', return_value=True)
        office.start()
        self.addCleanup(office.stop)

    def photo(self, name='foto.png', size=(400, 300)):
        path = self.tmp / name
        Image.new('RGB', size, 'orange').save(path)
        return str(path)

    def text(self, name='nota.txt'):
        path = self.tmp / name
        path.write_text('Linha com acentuação: ção\n' * 10, encoding='utf-8')
        return str(path)

    def word(self, name='oficio.docx'):
        path = self.tmp / name
        path.write_bytes(b'conteudo do word')
        return str(path)

    def pages_of(self, path):
        with fitz.open(path) as document:
            return document.page_count


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class ToolsAcceptOtherFormatsTests(AnyFormatCase):
    def test_merge_joins_a_pdf_an_image_and_a_text_file(self):
        page = self.window.open_tool('merge')
        pdf = str(make_pdf(self.tmp / 'a.pdf', 2))
        page.add_paths([pdf, self.photo(), self.text()])
        self.assertEqual([Path(f).name for f in page.files], ['a.pdf', 'foto.png', 'nota.txt'])
        self.assertEqual(page.counter.text(), '3 arquivos  ·  4 páginas')
        kinds = [page.tree.topLevelItem(i).text(1) for i in range(3)]
        self.assertEqual(kinds, ['PDF', 'Imagem', 'Texto'])
        target = self.tmp / 'unido.pdf'
        with mock.patch('rdf.qt.tool_page.QFileDialog.getSaveFileName', return_value=(str(target), '')):
            page.run()
        self.wait_until(lambda: not page.running)
        self.assertEqual(page.message.property('tone'), 'ok')
        self.assertEqual(self.pages_of(target), 4)

    def test_the_list_has_a_type_column_only_for_tools_that_take_any_file(self):
        merge = self.window.open_tool('merge')
        self.assertEqual(merge.tree.headerItem().text(1), 'Tipo')
        images = self.window.open_tool('images-to-pdf')
        self.assertNotEqual(images.tree.headerItem().text(1), 'Tipo')

    def test_every_tool_that_takes_pdfs_takes_other_files_except_repair_and_unlock(self):
        from rdf.pdftools.registry import TOOLS

        only_pdf = {tool.id for tool in TOOLS if not tool.special and tool.inputs == 'pdf' and not tool.any_format}
        self.assertEqual(only_pdf, {'repair', 'unlock'})

    def test_repair_and_unlock_still_take_only_pdf(self):
        for tool_id in ('repair', 'unlock'):
            with self.subTest(tool=tool_id):
                page = self.window.open_tool(tool_id)
                page.add_paths([self.photo()])
                self.assertEqual(page.files, [])
                self.assertIn('Nenhum arquivo compatível', page.message.text())
                self.assertEqual(page.accepted_text, 'PDFs')

    def test_the_tool_says_what_it_accepts(self):
        page = self.window.open_tool('compress')
        self.assertIn('Word, Excel e PowerPoint', page.accepted_text)
        page.add_paths([str(self.tmp / 'programa.exe')])
        self.assertIn('Nenhum arquivo compatível', page.message.text())
        self.assertIn('Word, Excel e PowerPoint', page.message.text())

    def test_a_broken_image_is_reported_by_name(self):
        page = self.window.open_tool('merge')
        broken = self.tmp / 'quebrada.png'
        broken.write_bytes(b'nao e imagem')
        page.add_paths([str(broken)])
        self.assertEqual(page.files, [])
        self.assertIn('quebrada.png', page.message.text())

    def test_without_office_the_document_is_refused_with_the_program_name(self):
        page = self.window.open_tool('merge')
        with mock.patch.object(sources, 'office_available', return_value=False):
            page.add_paths([self.word()])
        self.assertEqual(page.files, [])
        self.assertIn('Microsoft Word', page.message.text())

    def test_an_office_document_waits_for_the_run_to_be_converted(self):
        page = self.window.open_tool('merge')
        pdf = str(make_pdf(self.tmp / 'a.pdf', 3))
        with mock.patch.object(sources, '_office_to_pdf', side_effect=office_that_writes_two_pages) as office:
            page.add_paths([self.word(), pdf])
            office.assert_not_called()  # converter o Office leva segundos: fica para a hora de executar
            self.assertEqual(page.tree.topLevelItem(0).text(1), 'Word')
            self.assertEqual(page.tree.topLevelItem(0).text(2), 'ao processar')
            target = self.tmp / 'unido.pdf'
            with mock.patch('rdf.qt.tool_page.QFileDialog.getSaveFileName', return_value=(str(target), '')):
                page.run()
            self.wait_until(lambda: not page.running)
            office.assert_called_once()
        self.assertEqual(self.pages_of(target), 5)  # 2 do Word + 3 do PDF

    def test_the_preview_of_an_office_document_waits_too(self):
        page = self.window.open_tool('compress')
        page.add_paths([self.word()])
        self.assertIn('depois de processar', page.preview.text())

    def test_one_office_failure_does_not_stop_the_other_files(self):
        page = self.window.open_tool('compress')
        good = str(make_pdf(self.tmp / 'bom.pdf'))
        page.add_paths([good, self.word()])
        out = self.tmp / 'saida'
        out.mkdir()
        with (
            mock.patch.object(sources, '_office_to_pdf', side_effect=ops.PdfToolError('o Word travou')),
            mock.patch('rdf.qt.tool_page.QFileDialog.getExistingDirectory', return_value=str(out)),
        ):
            page.run()
            self.wait_until(lambda: not page.running)
        self.assertEqual([p.name for p in out.iterdir()], ['bom_comprimido.pdf'])
        self.assertIn('oficio.docx', page.message.text())
        self.assertIn('o Word travou', page.message.text())

    def test_converted_files_are_deleted_when_removed_cleared_or_the_tool_is_left(self):
        page = self.window.open_tool('merge')
        a, b = self.photo('a.png'), self.photo('b.png')
        page.add_paths([a, b])
        converted_a, converted_b = page.cache.pdf_for(a), page.cache.pdf_for(b)
        self.assertTrue(Path(converted_a).is_file() and Path(converted_b).is_file())
        page.tree.topLevelItem(0).setSelected(True)
        page.remove_selected()
        self.assertFalse(Path(converted_a).exists())
        self.assertTrue(Path(converted_b).exists())
        page.clear_files()
        self.assertFalse(Path(converted_b).exists())
        page.add_paths([a])
        folder = page.cache.folder
        self.assertTrue(folder.exists())
        with mock.patch.object(self.window, 'ask_unsaved_to_leave', return_value='discard'):
            self.assertTrue(self.window.request_home())
        self.assertFalse(folder.exists())

    def test_replacing_the_file_of_a_single_file_tool_drops_the_old_conversion(self):
        page = self.window.open_tool('split')
        first, second = self.photo('um.png'), self.photo('dois.png')
        page.add_paths([first])
        converted = page.cache.pdf_for(first)
        page.add_paths([second])
        self.assertEqual([Path(f).name for f in page.files], ['dois.png'])
        self.assertFalse(Path(converted).exists())

    def test_dropping_a_folder_picks_up_every_supported_file(self):
        folder = self.tmp / 'pasta'
        folder.mkdir()
        Image.new('RGB', (200, 100), 'red').save(folder / 'a.jpg')
        (folder / 'b.txt').write_text('texto', encoding='utf-8')
        (folder / 'c.exe').write_bytes(b'x')
        page = self.window.open_tool('merge')
        page.add_paths([str(folder)])
        self.assertEqual(sorted(Path(f).name for f in page.files), ['a.jpg', 'b.txt'])


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class MergeOtherFormatsTests(AnyFormatCase):
    def test_the_merge_tool_takes_any_file_and_has_the_print_button(self):
        page = self.window.open_tool('merge')
        page.add_paths([self.photo(), self.text(), str(make_pdf(self.tmp / 'a.pdf'))])
        self.assertEqual(len(page.files), 3)
        self.assertIn('Word, Excel e PowerPoint', page.accepted_text)
        self.assertTrue(page.print_button.isEnabled())

    def test_the_window_opens_merge_with_images_sent_from_the_explorer(self):
        self.assertTrue(self.window.open_print_with([self.photo(), self.text()]))
        self.assertEqual([Path(f).name for f in self.window.pages['merge'].files], ['foto.png', 'nota.txt'])


if __name__ == '__main__':
    unittest.main()
