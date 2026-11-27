"""Ferramentas novas da 4.0: tarjar, metadados, PDF para texto, escala de cinza, várias por folha e tamanho do papel.

Todos os documentos são fictícios e gerados pelo próprio teste.
"""

import io
import tempfile
import unittest
from pathlib import Path

import _source  # coloca a raiz do projeto no sys.path
import fitz
from PIL import Image
from rdf.pdftools import jobs, ops
from rdf.pdftools.registry import NEW_TOOLS, TOOLS_BY_ID


def make_pdf(path, lines=('Texto',), pages=1, size=(595, 842), color=(0, 0, 0), image=False, rotate=0):
    document = fitz.open()
    for number in range(pages):
        page = document.new_page(width=size[0], height=size[1])
        y = 72
        for line in lines:
            page.insert_text((72, y), f'{line}', fontsize=12, color=color)
            y += 20
        page.insert_text((72, size[1] - 40), f'pagina {number + 1}', fontsize=10)
        if image:
            picture = Image.new('RGB', (60, 60), (220, 30, 30))
            buffer = io.BytesIO()
            picture.save(buffer, 'PNG')
            page.insert_image(fitz.Rect(300, 300, 400, 400), stream=buffer.getvalue())
        if rotate:
            page.set_rotation(rotate)
    document.save(path)
    document.close()
    return Path(path)


def colored_pixels(path):
    with fitz.open(path) as document:
        pix = document[0].get_pixmap(dpi=50)
    picture = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    return sum(1 for red, green, blue in picture.getdata() if max(red, green, blue) - min(red, green, blue) > 12)


class ToolTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)


class RedactTests(ToolTestCase):
    def setUp(self):
        super().setUp()
        self.source = make_pdf(
            self.tmp / 'ficha.pdf',
            (
                'Nome: Maria Fictícia de Teste',
                'CPF: 123.456.789-09',
                'Contato: maria.teste@exemplo.com.br',
                'Telefone: (11) 98765-4321',
                'CNPJ 12.345.678/0001-95',
                'Protocolo 2026/0042',
            ),
            image=True,
        )
        self.dest = self.tmp / 'tarjado.pdf'

    def text(self, path):
        with fitz.open(path) as document:
            return document[0].get_text()

    def test_cpf_is_removed_from_the_file_not_just_covered(self):
        result = ops.redact_pdf(self.source, self.dest)
        text = self.text(self.dest)
        self.assertNotIn('123.456.789-09', text)
        self.assertNotIn('123.456.789-09'.encode(), self.dest.read_bytes())
        self.assertIn('Maria', text)  # o resto continua
        self.assertIn('1 trecho tarjado', result.message)

    def test_every_kind_and_typed_terms_together(self):
        ops.redact_pdf(self.source, self.dest, 'maria fictícia', cpf=True, cnpj=True, email=True, phone=True)
        text = self.text(self.dest)
        for gone in ('123.456.789-09', 'maria.teste@exemplo.com.br', '98765-4321', '12.345.678/0001-95', 'Fictícia'):
            self.assertNotIn(gone, text)
        self.assertIn('Protocolo 2026/0042', text)  # números que não são CPF nem telefone ficam

    def test_nothing_chosen_or_nothing_found_is_an_error(self):
        with self.assertRaisesRegex(ops.PdfToolError, 'Digite o que tarjar'):
            ops.redact_pdf(self.source, self.dest, '', cpf=False)
        with self.assertRaisesRegex(ops.PdfToolError, 'Nada encontrado'):
            ops.redact_pdf(self.source, self.dest, 'inexistente', cpf=False)
        self.assertFalse(self.dest.exists())  # nunca fica arquivo pela metade

    def test_a_scanned_pdf_asks_for_ocr_first(self):
        scanned = self.tmp / 'escaneado.pdf'
        document = fitz.open()
        page = document.new_page()
        picture = Image.new('RGB', (200, 200), 'white')
        buffer = io.BytesIO()
        picture.save(buffer, 'PNG')
        page.insert_image(page.rect, stream=buffer.getvalue())
        document.save(scanned)
        document.close()
        with self.assertRaisesRegex(ops.PdfToolError, 'OCR'):
            ops.redact_pdf(scanned, self.dest)

    def test_image_pixels_under_the_mark_are_blacked_out(self):
        source = make_pdf(self.tmp / 'img.pdf', ('SEGREDO',), image=True)
        with fitz.open(source) as document:
            page = document[0]
            page.insert_text((310, 350), 'SEGREDO2', fontsize=14)  # texto por cima da imagem
            document.saveIncr()
        ops.redact_pdf(source, self.dest, 'SEGREDO2', cpf=False)
        self.assertNotIn('SEGREDO2', self.text(self.dest))


class MetadataTests(ToolTestCase):
    def setUp(self):
        super().setUp()
        self.source = self.tmp / 'meta.pdf'
        document = fitz.open()
        document.new_page().insert_text((72, 72), 'conteúdo')
        document.set_metadata({'title': 'Antigo', 'author': 'Fulano Fictício', 'creator': 'Editor X'})
        document.save(self.source)
        document.close()
        self.dest = self.tmp / 'saida.pdf'

    def metadata(self):
        with fitz.open(self.dest) as document:
            return document.metadata, document[0].get_text()

    def test_edit_changes_only_the_filled_fields(self):
        result = ops.edit_metadata(self.source, self.dest, 'Editar', title='Relatório 2026', author='')
        metadata, _text = self.metadata()
        self.assertEqual(metadata['title'], 'Relatório 2026')
        self.assertEqual(metadata['author'], 'Fulano Fictício')
        self.assertIn('título', result.message)

    def test_edit_without_any_field_is_an_error(self):
        with self.assertRaisesRegex(ops.PdfToolError, 'Preencha'):
            ops.edit_metadata(self.source, self.dest, 'Editar')

    def test_remove_clears_author_and_keeps_the_pages(self):
        ops.edit_metadata(self.source, self.dest, 'Remover')
        metadata, text = self.metadata()
        self.assertFalse(metadata.get('author'))
        self.assertFalse(metadata.get('title'))
        self.assertIn('conteúdo', text)
        self.assertNotIn(b'Fulano', self.dest.read_bytes())


class TextTests(ToolTestCase):
    def test_text_is_saved_with_a_separator_per_page(self):
        source = make_pdf(self.tmp / 't.pdf', ('Ação e informação',), pages=2)
        dest = self.tmp / 't.txt'
        result = ops.pdf_to_text(source, dest)
        content = dest.read_text(encoding='utf-8-sig')
        self.assertIn('===== Página 1 =====', content)
        self.assertIn('===== Página 2 =====', content)
        self.assertIn('Ação e informação', content)
        self.assertIn('2 de 2 páginas', result.message)

    def test_a_pdf_without_text_suggests_ocr(self):
        source = self.tmp / 'vazio.pdf'
        document = fitz.open()
        document.new_page()
        document.save(source)
        document.close()
        with self.assertRaisesRegex(ops.PdfToolError, 'OCR'):
            ops.pdf_to_text(source, self.tmp / 'x.txt')

    def test_the_tool_saves_a_txt_and_suggests_that_extension(self):
        tool = TOOLS_BY_ID['pdf-to-text']
        self.assertEqual(tool.output_ext, 'txt')
        self.assertEqual(jobs.suggested_name(tool, Path('C:/docs/relatorio.pdf')), 'relatorio.txt')
        folder_jobs = jobs.jobs_for_folder(tool, [str(self.tmp / 'a.pdf'), str(self.tmp / 'b.pdf')], self.tmp)
        self.assertTrue(all(str(dest).endswith('.txt') for _origin, dest in folder_jobs))


class GrayscaleTests(ToolTestCase):
    def test_colors_turn_gray_and_the_text_stays_searchable(self):
        source = make_pdf(self.tmp / 'cor.pdf', ('Texto vermelho',), color=(0.9, 0.1, 0.1), image=True)
        self.assertGreater(colored_pixels(source), 0)
        dest = self.tmp / 'cinza.pdf'
        ops.grayscale_pdf(source, dest)
        self.assertEqual(colored_pixels(dest), 0)
        with fitz.open(dest) as document:
            self.assertIn('Texto vermelho', document[0].get_text())


class SheetTests(ToolTestCase):
    def test_two_portrait_pages_fit_side_by_side_on_a_landscape_sheet(self):
        source = make_pdf(self.tmp / 'n.pdf', pages=5)
        dest = self.tmp / 'n2.pdf'
        result = ops.n_up_pdf(source, dest, '2 por folha', 'A4')
        with fitz.open(dest) as document:
            self.assertEqual(document.page_count, 3)
            sheet = document[0].rect
            self.assertGreater(sheet.width, sheet.height)
            text = document[0].get_text()
        self.assertIn('pagina 1', text)
        self.assertIn('pagina 2', text)
        self.assertIn('5 páginas em 3 folhas', result.message)

    def test_four_per_sheet_keeps_a_portrait_sheet(self):
        source = make_pdf(self.tmp / 'n.pdf', pages=8)
        dest = self.tmp / 'n4.pdf'
        ops.n_up_pdf(source, dest, '4 por folha', 'Carta', border=True)
        with fitz.open(dest) as document:
            self.assertEqual(document.page_count, 2)
            self.assertEqual((round(document[0].rect.width), round(document[0].rect.height)), (612, 792))

    def test_landscape_pages_stack_on_a_portrait_sheet(self):
        source = make_pdf(self.tmp / 'deitada.pdf', pages=2, size=(842, 595))
        dest = self.tmp / 'n.pdf'
        ops.n_up_pdf(source, dest, '2 por folha', 'A4')
        with fitz.open(dest) as document:
            self.assertEqual(document.page_count, 1)
            self.assertLess(document[0].rect.width, document[0].rect.height)

    def test_every_page_ends_up_on_the_chosen_paper_keeping_orientation(self):
        source = self.tmp / 'mistura.pdf'
        document = fitz.open()
        document.new_page(width=300, height=400).insert_text((20, 30), 'pequena')
        document.new_page(width=1200, height=800).insert_text((20, 30), 'deitada')
        document.save(source)
        document.close()
        dest = self.tmp / 'a4.pdf'
        ops.fit_to_paper(source, dest, 'A4')
        with fitz.open(dest) as output:
            sizes = [(round(page.rect.width), round(page.rect.height)) for page in output]
            self.assertIn('pequena', output[0].get_text())
        self.assertEqual(sizes, [(595, 842), (842, 595)])

    def test_a_rotated_page_keeps_how_it_looks(self):
        source = make_pdf(self.tmp / 'girada.pdf', size=(595, 842), rotate=90)
        dest = self.tmp / 'saida.pdf'
        ops.fit_to_paper(source, dest, 'A4')
        with fitz.open(dest) as output:
            self.assertGreater(output[0].rect.width, output[0].rect.height)  # girada, ela aparece deitada


class CatalogTests(unittest.TestCase):
    def test_new_tools_are_in_the_catalog_with_an_icon(self):
        for tool_id in NEW_TOOLS:
            with self.subTest(tool=tool_id):
                tool = TOOLS_BY_ID[tool_id]
                self.assertTrue(tool.icon)
                self.assertTrue(tool.glyph)
                self.assertTrue(tool.run)

    def test_redaction_is_found_by_lgpd_words(self):
        from rdf.pdftools.registry import search_tools

        for word in ('lgpd', 'cpf', 'tarjar', 'anonimizar'):
            self.assertEqual(search_tools(word)[0].id, 'redact', word)
        self.assertEqual(search_tools('metadados')[0].id, 'metadata')


if __name__ == '__main__':
    unittest.main()


class MetadataReadTests(ToolTestCase):
    def test_dates_are_shown_the_brazilian_way(self):
        self.assertEqual(ops.format_pdf_date("D:20261127083015-03'00'"), '27/11/2026 08:30')
        self.assertEqual(ops.format_pdf_date('D:20260102'), '02/01/2026')
        self.assertEqual(ops.format_pdf_date('lixo'), '')

    def test_reading_never_raises(self):
        self.assertEqual(ops.read_metadata(self.tmp / 'nao-existe.pdf'), {})
        source = self.tmp / 'm.pdf'
        document = fitz.open()
        document.new_page()
        document.set_metadata({'author': 'Autor Fictício', 'creationDate': 'D:20250101120000'})
        document.save(source)
        document.close()
        info = ops.read_metadata(source)
        self.assertEqual(info['author'], 'Autor Fictício')
        self.assertEqual(info['created'], '01/01/2025 12:00')
        self.assertEqual(info['pages'], 1)
