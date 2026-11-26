"""Operações de PDF (rdf.pdftools): resultados reais, sem interface."""

import tempfile
import unittest
from pathlib import Path

import _source  # coloca a raiz do projeto no sys.path
import fitz
from PIL import Image
from rdf.pdftools import ops
from rdf.pdftools.pages import PageRangeError, parse_page_groups, parse_page_ranges
from rdf.pdftools.registry import CATEGORIES, TOOLS, TOOLS_BY_ID, search_tools


def make_pdf(path, pages=3, label='Pagina'):
    document = fitz.open()
    for number in range(1, pages + 1):
        page = document.new_page(width=400, height=300)
        page.insert_text((40, 80), f'{label} {number}', fontsize=20)
    document.save(path)
    document.close()
    return Path(path)


def page_texts(path, password=None):
    with fitz.open(path) as document:
        if password:
            document.authenticate(password)
        return [page.get_text().strip() for page in document]


class PageRangeTests(unittest.TestCase):
    def test_numbers_ranges_and_open_ended_ranges(self):
        self.assertEqual(parse_page_ranges('1-3, 5, 8-', 9), [0, 1, 2, 4, 7, 8])
        self.assertEqual(parse_page_ranges('-2', 9), [0, 1])
        self.assertEqual(parse_page_ranges('2 - 4', 9), [1, 2, 3])

    def test_order_is_kept_and_duplicates_are_dropped_unless_allowed(self):
        self.assertEqual(parse_page_ranges('3, 1, 3', 5), [2, 0])
        self.assertEqual(parse_page_ranges('3, 1, 3', 5, allow_duplicates=True), [2, 0, 2])

    def test_errors_explain_the_problem(self):
        for text, expected in [
            ('', 'Informe'),
            ('abc', 'inválido'),
            ('0', 'começam em 1'),
            ('4-2', 'invertido'),
            ('12', 'não existe'),
        ]:
            with self.assertRaises(PageRangeError) as caught:
                parse_page_ranges(text, 5)
            self.assertIn(expected, str(caught.exception), text)

    def test_groups_split_on_commas(self):
        self.assertEqual(parse_page_groups('1-2, 4, 5-', 6), [[0, 1], [3], [4, 5]])


class OperationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def pdf(self, name, pages=3, label='Pagina'):
        return make_pdf(self.tmp / name, pages, label)

    def test_merge_keeps_the_order_of_the_files(self):
        a, b = self.pdf('a.pdf', 2, 'A'), self.pdf('b.pdf', 1, 'B')
        result = ops.merge_pdfs([b, a], self.tmp / 'm.pdf')
        self.assertEqual(page_texts(result.paths[0]), ['B 1', 'A 1', 'A 2'])

    def test_merge_needs_two_files(self):
        with self.assertRaises(ops.PdfToolError):
            ops.merge_pdfs([self.pdf('a.pdf')], self.tmp / 'm.pdf')
        self.assertFalse((self.tmp / 'm.pdf').exists())

    def test_failed_operation_leaves_no_partial_file(self):
        bad = self.tmp / 'bad.pdf'
        bad.write_bytes(b'isto nao e um pdf')
        with self.assertRaises(ops.PdfToolError):
            ops.merge_pdfs([self.pdf('a.pdf'), bad], self.tmp / 'out' / 'm.pdf')
        self.assertEqual(list((self.tmp / 'out').glob('*')), [])

    def test_can_save_over_the_original(self):
        source = self.pdf('a.pdf', 3)
        ops.select_pages(source, source, '1-2', keep=True)
        self.assertEqual(len(page_texts(source)), 2)

    def test_split_by_ranges(self):
        source = self.pdf('doc.pdf', 6)
        result = ops.split_pdf(source, self.tmp / 'out', 'ranges', '1-2, 4, 5-')
        self.assertEqual(
            [p.name for p in result.paths], ['doc_paginas_1-2.pdf', 'doc_pagina_4.pdf', 'doc_paginas_5-6.pdf']
        )
        self.assertEqual([len(page_texts(p)) for p in result.paths], [2, 1, 2])

    def test_split_every_n_and_each_page(self):
        source = self.pdf('doc.pdf', 5)
        every = ops.split_pdf(source, self.tmp / 'e', 'every', every=2)
        self.assertEqual([len(page_texts(p)) for p in every.paths], [2, 2, 1])
        each = ops.split_pdf(source, self.tmp / 'p', 'each')
        self.assertEqual(len(each.paths), 5)
        self.assertEqual(page_texts(each.paths[3]), ['Pagina 4'])

    def test_split_never_overwrites_existing_files(self):
        source = self.pdf('doc.pdf', 2)
        first = ops.split_pdf(source, self.tmp / 'o', 'each')
        second = ops.split_pdf(source, self.tmp / 'o', 'each')
        self.assertEqual(len(set(first.paths + second.paths)), 4)

    def test_remove_and_extract_pages(self):
        source = self.pdf('a.pdf', 5)
        removed = ops.select_pages(source, self.tmp / 'r.pdf', '2, 4', keep=False)
        self.assertEqual(page_texts(removed.paths[0]), ['Pagina 1', 'Pagina 3', 'Pagina 5'])
        extracted = ops.select_pages(source, self.tmp / 'x.pdf', '5, 1', keep=True)
        self.assertEqual(page_texts(extracted.paths[0]), ['Pagina 5', 'Pagina 1'])

    def test_cannot_remove_every_page(self):
        with self.assertRaises(ops.PdfToolError):
            ops.select_pages(self.pdf('a.pdf', 2), self.tmp / 'r.pdf', '1-2', keep=False)

    def test_reorder_reverse_and_custom(self):
        source = self.pdf('a.pdf', 3)
        reverse = ops.reorder_pages(source, self.tmp / 'rev.pdf', 'reverse')
        self.assertEqual(page_texts(reverse.paths[0]), ['Pagina 3', 'Pagina 2', 'Pagina 1'])
        custom = ops.reorder_pages(source, self.tmp / 'c.pdf', 'custom', '2, 3, 1, 1')
        self.assertEqual(page_texts(custom.paths[0]), ['Pagina 2', 'Pagina 3', 'Pagina 1', 'Pagina 1'])

    def test_rotate_all_or_some_pages(self):
        source = self.pdf('a.pdf', 3)
        ops.rotate_pdf(source, self.tmp / 'r.pdf', '90° para a direita', '2')
        with fitz.open(self.tmp / 'r.pdf') as document:
            self.assertEqual([page.rotation for page in document], [0, 90, 0])
        ops.rotate_pdf(self.tmp / 'r.pdf', self.tmp / 'r2.pdf', '90° para a esquerda')
        with fitz.open(self.tmp / 'r2.pdf') as document:
            self.assertEqual([page.rotation for page in document], [270, 0, 270])

    def test_crop_reduces_the_visible_page_even_when_rotated(self):
        source = self.pdf('a.pdf', 2)
        ops.rotate_pdf(source, self.tmp / 'rot.pdf', '90° para a direita', '2')
        ops.crop_pdf(self.tmp / 'rot.pdf', self.tmp / 'c.pdf', top=10, left=20)
        mm = 72 / 25.4
        with fitz.open(self.tmp / 'c.pdf') as document:
            self.assertAlmostEqual(document[0].rect.width, 400 - 20 * mm, delta=0.5)
            self.assertAlmostEqual(document[0].rect.height, 300 - 10 * mm, delta=0.5)
            self.assertAlmostEqual(document[1].rect.width, 300 - 20 * mm, delta=0.5)
            self.assertAlmostEqual(document[1].rect.height, 400 - 10 * mm, delta=0.5)

    def test_crop_needs_a_margin_and_cannot_exceed_the_page(self):
        source = self.pdf('a.pdf', 1)
        with self.assertRaises(ops.PdfToolError):
            ops.crop_pdf(source, self.tmp / 'c.pdf')
        with self.assertRaises(ops.PdfToolError):
            ops.crop_pdf(source, self.tmp / 'c.pdf', left=100, right=100)

    def test_page_numbers_start_where_asked(self):
        source = self.pdf('a.pdf', 3)
        ops.add_page_numbers(source, self.tmp / 'n.pdf', 'Inferior direita', 'Página 1 de N', first=1, start_page=2)
        texts = page_texts(self.tmp / 'n.pdf')
        self.assertNotIn('Página', texts[0])
        self.assertIn('Página 1 de 2', texts[1])
        self.assertIn('Página 2 de 2', texts[2])

    def test_page_numbers_reject_a_start_page_outside_the_document(self):
        with self.assertRaises(ops.PdfToolError):
            ops.add_page_numbers(self.pdf('a.pdf', 2), self.tmp / 'n.pdf', start_page=5)

    def test_watermark_adds_text_to_every_page(self):
        source = self.pdf('a.pdf', 2)
        ops.add_watermark(source, self.tmp / 'w.pdf', 'RASCUNHO')
        self.assertTrue(all('RASCUNHO' in text for text in page_texts(self.tmp / 'w.pdf')))
        with self.assertRaises(ops.PdfToolError):
            ops.add_watermark(source, self.tmp / 'w2.pdf', '   ')

    def test_protect_then_unlock(self):
        source = self.pdf('a.pdf', 2)
        ops.protect_pdf(source, self.tmp / 'p.pdf', 'segredo')
        with self.assertRaises(ops.PdfToolError) as caught:
            ops.compress_pdf(self.tmp / 'p.pdf', self.tmp / 'c.pdf')
        self.assertIn('senha', str(caught.exception))
        with self.assertRaises(ops.PdfToolError):
            ops.unlock_pdf(self.tmp / 'p.pdf', self.tmp / 'u.pdf', 'errada')
        unlocked = ops.unlock_pdf(self.tmp / 'p.pdf', self.tmp / 'u.pdf', 'segredo')
        self.assertEqual(unlocked.message, 'Proteção removida.')
        self.assertEqual(page_texts(self.tmp / 'u.pdf'), ['Pagina 1', 'Pagina 2'])
        with fitz.open(self.tmp / 'u.pdf') as document:
            self.assertFalse(document.is_encrypted)

    def test_protect_requires_a_password(self):
        with self.assertRaises(ops.PdfToolError):
            ops.protect_pdf(self.pdf('a.pdf'), self.tmp / 'p.pdf', '')

    def test_restrictions_hold_when_no_administrator_password_is_given(self):
        # A mesma senha nas duas funções daria acesso total a quem abre o PDF; sem senha de administrador
        # o app cria uma aleatória, então abrir com a senha de abrir nunca autentica como dono.
        source = self.pdf('a.pdf')
        ops.protect_pdf(source, self.tmp / 'p.pdf', 'segredo', '', True, False, False)
        with fitz.open(self.tmp / 'p.pdf') as document:
            self.assertEqual(document.authenticate('segredo'), 2)  # 2 = só senha de abrir (nunca dona)
        ops.protect_pdf(source, self.tmp / 'q.pdf', 'segredo', 'dono', True, False, False)
        with fitz.open(self.tmp / 'q.pdf') as document:
            self.assertEqual(document.authenticate('dono'), 4)  # 4 = senha de administrador

    def test_compress_shrinks_a_heavy_image_pdf(self):
        picture = Image.effect_noise((1800, 1800), 60).convert('RGB')
        image_path = self.tmp / 'noise.png'
        picture.save(image_path)
        heavy = self.tmp / 'heavy.pdf'
        document = fitz.open()
        page = document.new_page()
        page.insert_image(page.rect, filename=str(image_path))
        document.save(heavy)
        document.close()
        result = ops.compress_pdf(heavy, self.tmp / 'light.pdf', 'Extrema (menor tamanho)')
        self.assertLess((self.tmp / 'light.pdf').stat().st_size, heavy.stat().st_size * 0.6)
        self.assertIn('redução', result.message)
        self.assertEqual(len(page_texts(self.tmp / 'light.pdf')), 1)

    def test_repair_rewrites_a_damaged_file(self):
        good = self.pdf('a.pdf', 2)
        data = good.read_bytes()
        broken = self.tmp / 'broken.pdf'
        broken.write_bytes(data[: data.rindex(b'startxref')])  # sem a tabela de referências
        result = ops.repair_pdf(broken, self.tmp / 'fixed.pdf')
        self.assertEqual(len(page_texts(result.paths[0])), 2)

    def test_images_to_pdf_with_fixed_and_fitted_pages(self):
        wide = self.tmp / 'wide.png'
        Image.new('RGB', (800, 400), 'red').save(wide)
        tall = self.tmp / 'tall.jpg'
        Image.new('RGB', (300, 600), 'blue').save(tall)
        result = ops.images_to_pdf([wide, tall], self.tmp / 'i.pdf', 'A4', 'Automática', 'Pequena')
        with fitz.open(result.paths[0]) as document:
            self.assertEqual(document.page_count, 2)
            self.assertGreater(document[0].rect.width, document[0].rect.height)  # imagem larga: paisagem
            self.assertLess(document[1].rect.width, document[1].rect.height)
        fitted = ops.images_to_pdf([wide], self.tmp / 'f.pdf', 'Ajustar à imagem', margin='Nenhuma')
        with fitz.open(fitted.paths[0]) as document:
            self.assertAlmostEqual(document[0].rect.width / document[0].rect.height, 2.0, places=2)

    def test_images_to_pdf_rejects_a_fake_image(self):
        fake = self.tmp / 'fake.png'
        fake.write_bytes(b'nao sou imagem')
        with self.assertRaises(ops.PdfToolError):
            ops.images_to_pdf([fake], self.tmp / 'i.pdf')

    def test_pdf_to_images_pages_and_selection(self):
        source = self.pdf('doc.pdf', 3)
        result = ops.pdf_to_images(source, self.tmp / 'img', image_format='PNG', dpi=72, spec='2-3')
        self.assertEqual([p.name for p in result.paths], ['doc_pagina_2.png', 'doc_pagina_3.png'])
        with Image.open(result.paths[0]) as picture:
            self.assertEqual(picture.size, (400, 300))
        jpg = ops.pdf_to_images(source, self.tmp / 'jpg', image_format='JPG', dpi=72)
        self.assertTrue(all(p.suffix == '.jpg' for p in jpg.paths))

    def test_extract_embedded_images(self):
        picture = self.tmp / 'p.png'
        Image.new('RGB', (50, 50), 'green').save(picture)
        document = fitz.open()
        document.new_page().insert_image(fitz.Rect(10, 10, 110, 110), filename=str(picture))
        pdf_path = self.tmp / 'with_image.pdf'
        document.save(pdf_path)
        document.close()
        result = ops.pdf_to_images(pdf_path, self.tmp / 'ex', mode='Extrair imagens do PDF')
        self.assertEqual(len(result.paths), 1)
        with self.assertRaises(ops.PdfToolError):
            ops.pdf_to_images(self.pdf('plain.pdf'), self.tmp / 'ex2', mode='Extrair imagens do PDF')

    def test_unique_path_and_human_size(self):
        taken = self.tmp / 'x.pdf'
        taken.write_bytes(b'1')
        self.assertEqual(ops.unique_path(taken).name, 'x (2).pdf')
        self.assertEqual(ops.human_size(512), '512 B')
        self.assertEqual(ops.human_size(1536), '1,5 KB')


class RegistryTests(unittest.TestCase):
    def test_every_tool_is_consistent(self):
        ids = [tool.id for tool in TOOLS]
        self.assertEqual(len(ids), len(set(ids)))
        for tool in TOOLS:
            self.assertIn(tool.category, CATEGORIES)
            self.assertIn(tool.mode, ('combine', 'each', 'multi'))
            self.assertIn(tool.inputs, ('pdf', 'image'))
            if not tool.special:
                self.assertTrue(callable(tool.run), tool.id)
                self.assertTrue(tool.action, tool.id)
            keys = [option.key for option in tool.options]
            self.assertEqual(len(keys), len(set(keys)), tool.id)
            for option in tool.options:
                if option.visible_if:
                    self.assertIn(option.visible_if[0], keys, f'{tool.id}.{option.key}')
                if option.kind == 'choice':
                    self.assertIn(option.default, option.choices, f'{tool.id}.{option.key}')

    def test_default_options_run_every_tool_end_to_end(self):
        """Cada ferramenta roda com as opções padrão (quando elas bastam) e gera arquivos reais."""
        needs_input = {'remove', 'extract', 'organize', 'protect', 'ocr'}
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            pdf = make_pdf(tmp / 'a.pdf', 6)  # os intervalos padrão de Dividir vão até a página 6
            second = make_pdf(tmp / 'b.pdf', 2)
            image = tmp / 'i.png'
            Image.new('RGB', (200, 100), 'orange').save(image)
            for tool in TOOLS:
                if tool.special or tool.id in needs_input:
                    continue
                values = {option.key: option.default for option in tool.options}
                if tool.inputs == 'image':
                    source = [image]
                elif tool.mode == 'combine':
                    source = [pdf, second]
                else:
                    source = pdf
                dest = tmp / f'out_{tool.id}' if tool.mode == 'multi' else tmp / f'out_{tool.id}.pdf'
                result = tool.run(source, dest, values, lambda f, m='': None)
                self.assertTrue(result.paths, tool.id)
                self.assertTrue(all(Path(p).exists() for p in result.paths), tool.id)

    def test_search_by_text(self):
        self.assertEqual([t.id for t in search_tools('juntar')], ['merge'])
        self.assertIn('rotate', [t.id for t in search_tools('girar')])
        self.assertEqual({t.id for t in search_tools('senha')}, {'protect', 'unlock'})
        self.assertEqual(search_tools('zzzz'), [])
        self.assertEqual(len(search_tools('')), len(TOOLS))

    def test_the_renamer_is_a_special_tool(self):
        self.assertTrue(TOOLS_BY_ID['renamer'].special)

    def test_there_is_no_separate_print_tool_printing_lives_in_merge(self):
        self.assertNotIn('print', TOOLS_BY_ID)
        self.assertEqual([t.id for t in search_tools('imprimir')], ['merge'])
        self.assertIn('imprima', TOOLS_BY_ID['merge'].description)


if __name__ == '__main__':
    unittest.main()
