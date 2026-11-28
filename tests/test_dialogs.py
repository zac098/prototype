"""Diálogos do renomeador (rdf/qt/dialogs.py): corrigir dados, PDF com várias páginas, cancelar e exportar.

Cada diálogo é modal: o teste agenda a "mão do usuário" (preencher, clicar) para logo depois de ele abrir.
"""

import importlib.util
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import _source  # coloca a raiz do projeto no sys.path

HAS_QT = importlib.util.find_spec('PySide6') is not None

if HAS_QT:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QLineEdit, QPushButton, QSpinBox

    from rdf.qt import dialogs
    from rdf.qt.__main__ import create_app


HAND_ERRORS = []  # falhas da "mão do usuário": reaparecem no tearDown do teste


def when_open(action, seconds=5):
    """Roda action(diálogo) assim que o diálogo modal estiver aberto.

    O teste nunca fica preso: se a ação falhar, ou se o diálogo continuar aberto depois de alguns segundos, ele é
    fechado e o erro é acusado no fim do teste."""
    attempts = {'left': 200}

    def close_if_still_open(dialog):
        if dialog.isVisible():
            HAND_ERRORS.append(AssertionError('o diálogo continuou aberto depois da ação'))
            dialog.reject()

    def check():
        dialog = QApplication.activeModalWidget()
        if dialog is not None and dialog.isVisible():
            try:
                action(dialog)
            except Exception as exc:
                HAND_ERRORS.append(exc)
                dialog.reject()
                return
            QTimer.singleShot(int(seconds * 1000), lambda: close_if_still_open(dialog))
        elif attempts['left'] > 0:
            attempts['left'] -= 1
            QTimer.singleShot(10, check)
        else:
            HAND_ERRORS.append(AssertionError('o diálogo não abriu'))

    QTimer.singleShot(0, check)


def click(dialog, text):
    button = next(b for b in dialog.findChildren(QPushButton) if b.text() == text)
    button.click()


@unittest.skipUnless(HAS_QT, 'PySide6 não instalado')
class DialogCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app([])

    def setUp(self):
        HAND_ERRORS.clear()

    def tearDown(self):
        if HAND_ERRORS:
            raise HAND_ERRORS[0]


class EditDialogTests(DialogCase):
    def fields(self, dialog):
        return (
            dialog.findChild(QLineEdit, 'editChapa'),
            dialog.findChild(QLineEdit, 'editNome'),
            dialog.findChild(QComboBox, 'editMes'),
            dialog.findChild(QPushButton, 'saveCorrection'),
        )

    def test_the_correction_comes_back_cleaned(self):
        def fill(dialog):
            chapa, nome, mes, save = self.fields(dialog)
            chapa.setText(' 101838 ')
            nome.setText('Maria Fictícia: Teste/Ok')
            mes.setCurrentText('ABRIL')
            save.click()

        when_open(fill)
        data = dialogs.edit_dialog(None, {'chapa': '1', 'nome': '', 'mes': ''})
        self.assertEqual(data['chapa'], '101838')
        self.assertEqual(data['mes'], 'ABRIL')
        self.assertNotIn(':', data['nome'])  # nunca um caractere proibido em nome de arquivo
        self.assertNotIn('/', data['nome'])

    def test_cancel_returns_nothing(self):
        when_open(lambda dialog: click(dialog, 'Cancelar'))
        self.assertIsNone(dialogs.edit_dialog(None, {'chapa': '123', 'nome': 'ANA', 'mes': 'maio'}))

    def test_the_month_already_read_is_selected(self):
        seen = {}

        def look(dialog):
            _chapa, _nome, mes, _save = self.fields(dialog)
            seen['mes'] = mes.currentText()
            click(dialog, 'Cancelar')

        when_open(look)
        dialogs.edit_dialog(None, {'chapa': '123', 'nome': 'ANA', 'mes': 'março'})  # como o OCR devolve
        self.assertEqual(seen['mes'], 'MARÇO')

    def test_a_month_outside_the_list_is_not_lost_when_saving(self):
        """Regressão: um mês fora da lista ("MARCO" sem cedilha, de uma sessão antiga) aparecia em branco, e salvar a
        correção do nome apagava o mês."""

        def fix_name(dialog):
            _chapa, nome, mes, save = self.fields(dialog)
            self.assertEqual(mes.currentText(), 'MARCO')
            nome.setText('ANA SOUZA')
            save.click()

        when_open(fix_name)
        data = dialogs.edit_dialog(None, {'chapa': '123', 'nome': 'ANA', 'mes': 'Marco'})
        self.assertEqual(data['mes'], 'MARCO')
        self.assertEqual(data['nome'], 'ANA SOUZA')

    def test_an_empty_correction_cannot_be_saved(self):
        """Uma correção sem nada viraria "CORRIGIDO" exportada com o nome original."""
        seen = {}

        def clear(dialog):
            chapa, nome, mes, save = self.fields(dialog)
            chapa.clear()
            nome.clear()
            mes.setCurrentIndex(0)
            seen['empty'] = save.isEnabled()
            nome.setText('ANA')
            seen['filled'] = save.isEnabled()
            click(dialog, 'Cancelar')

        when_open(clear)
        dialogs.edit_dialog(None, {'chapa': '123', 'nome': 'ANA', 'mes': ''})
        self.assertFalse(seen['empty'])
        self.assertTrue(seen['filled'])


class MultipageDialogTests(DialogCase):
    def test_each_choice(self):
        when_open(lambda dialog: click(dialog, 'Separar páginas e renomear todas'))
        self.assertEqual(dialogs.multipage_dialog(None, 'C:/lote/folhas.pdf', 4), ('split', 0))
        when_open(lambda dialog: click(dialog, 'Ignorar este arquivo'))
        self.assertEqual(dialogs.multipage_dialog(None, 'C:/lote/folhas.pdf', 4), ('ignore', 0))

    def test_keep_uses_the_chosen_page_counting_from_zero(self):
        def keep_page_three(dialog):
            spin = dialog.findChild(QSpinBox)
            self.assertEqual((spin.minimum(), spin.maximum()), (1, 4))
            spin.setValue(3)
            click(dialog, 'Manter completo')

        when_open(keep_page_three)
        self.assertEqual(dialogs.multipage_dialog(None, 'C:/lote/folhas.pdf', 4), ('keep', 2))

    def test_closing_the_window_ignores_the_file(self):
        when_open(lambda dialog: dialog.reject())
        self.assertEqual(dialogs.multipage_dialog(None, 'C:/lote/folhas.pdf', 4), ('ignore', 0))


class AnalysisAndExportDialogTests(DialogCase):
    def test_cancel_analysis_choices(self):
        for text, value in (
            ('Manter resultados e parar', 'keep'),
            ('Descartar resultados desta análise', 'discard'),
            ('Continuar análise', 'continue'),
        ):
            with self.subTest(choice=value):
                when_open(lambda dialog, text=text: click(dialog, text))
                self.assertEqual(dialogs.cancel_analysis_dialog(None), value)
        when_open(lambda dialog: dialog.reject())
        self.assertEqual(dialogs.cancel_analysis_dialog(None), 'continue')  # fechar a janela não cancela nada

    def test_review_dialog_lists_at_most_six_files(self):
        files = [f'C:/lote/folha{number}.pdf' for number in range(9)]
        seen = {}

        def look(dialog):
            seen['texts'] = '\n'.join(label.text() for label in dialog.findChildren(QLabel))
            click(dialog, 'Revisar arquivos')

        when_open(look)
        self.assertEqual(dialogs.review_export_dialog(None, files), 'review')
        self.assertIn('9 arquivo(s)', seen['texts'])
        self.assertIn('folha5.pdf', seen['texts'])
        self.assertNotIn('folha6.pdf', seen['texts'])
        self.assertIn('e mais 3 arquivo(s)', seen['texts'])
        when_open(lambda dialog: click(dialog, 'Prosseguir mesmo assim'))
        self.assertEqual(dialogs.review_export_dialog(None, files[:1]), 'proceed')
        when_open(lambda dialog: dialog.reject())
        self.assertEqual(dialogs.review_export_dialog(None, files[:1]), 'cancel')

    def test_blocking_dialog_shows_the_reasons(self):
        problems = [(f'C:/lote/f{number}.pdf', 'sem matrícula') for number in range(10)]
        seen = {}

        def look(dialog):
            seen['texts'] = '\n'.join(label.text() for label in dialog.findChildren(QLabel))
            click(dialog, 'Mostrar bloqueados')

        when_open(look)
        self.assertEqual(dialogs.blocking_export_dialog(None, problems), 'show')
        self.assertIn('f0.pdf: sem matrícula', seen['texts'])
        self.assertIn('e mais 2 arquivo(s)', seen['texts'])
        when_open(lambda dialog: click(dialog, 'Fechar'))
        self.assertEqual(dialogs.blocking_export_dialog(None, problems[:1]), 'close')


if __name__ == '__main__':
    unittest.main()
