"""Preferências do usuário: valores conferidos, gravação segura e nada no disco antes de load()."""

import json
import tempfile
import unittest
from pathlib import Path

import _source  # coloca a raiz do projeto no sys.path
from rdf.core import settings


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.file = Path(self._tmp.name) / 'dados' / 'preferencias.json'
        self.addCleanup(settings.reset)

    def test_without_load_nothing_touches_the_disk(self):
        prefs = settings.reset()
        prefs.set('theme', 'escuro')
        self.assertEqual(prefs.get('theme'), 'escuro')
        self.assertFalse(prefs.save())

    def test_a_change_is_saved_and_read_back(self):
        prefs = settings.load(self.file)
        prefs.set('theme', 'claro')
        prefs.toggle_favorite('merge')
        again = settings.load(self.file)
        self.assertEqual(again.get('theme'), 'claro')
        self.assertEqual(again.get('favorites'), ['merge'])
        self.assertFalse(self.file.with_suffix('.tmp').exists())

    def test_bad_values_fall_back_to_the_default(self):
        self.file.parent.mkdir(parents=True)
        self.file.write_text(
            json.dumps(
                {'theme': 'roxo', 'favorites': 'merge', 'recent': [1, 'split', 'split'], 'open_folder_after': 'sim'}
            ),
            encoding='utf-8',
        )
        prefs = settings.load(self.file)
        self.assertEqual(prefs.get('theme'), 'sistema')
        self.assertEqual(prefs.get('favorites'), [])
        self.assertEqual(prefs.get('recent'), ['split'])
        self.assertFalse(prefs.get('open_folder_after'))

    def test_a_damaged_file_does_not_break_the_app(self):
        self.file.parent.mkdir(parents=True)
        self.file.write_text('{ quebrado', encoding='utf-8')
        prefs = settings.load(self.file)
        self.assertEqual(prefs.as_dict(), settings.DEFAULTS)
        self.assertTrue(prefs.set('theme', 'escuro'))  # e grava por cima, consertando o arquivo
        self.assertEqual(json.loads(self.file.read_text(encoding='utf-8'))['theme'], 'escuro')

    def test_setting_an_invalid_value_keeps_the_default(self):
        prefs = settings.reset()
        self.assertEqual(prefs.set('theme', 'neon'), 'sistema')
        with self.assertRaises(KeyError):
            prefs.set('nao-existe', 1)

    def test_recent_tools_keep_the_newest_first_without_repeats(self):
        prefs = settings.reset()
        for tool in ('merge', 'split', 'merge', *(f't{n}' for n in range(10))):
            prefs.record_use(tool)
        recent = prefs.get('recent')
        self.assertEqual(len(recent), settings.MAX_RECENT)
        self.assertEqual(recent[0], 't9')
        self.assertEqual(len(set(recent)), len(recent))

    def test_favorites_toggle_on_and_off(self):
        prefs = settings.reset()
        self.assertTrue(prefs.toggle_favorite('ocr'))
        self.assertTrue(prefs.is_favorite('ocr'))
        self.assertFalse(prefs.toggle_favorite('ocr'))
        self.assertEqual(prefs.get('favorites'), [])

    def test_tools_that_no_longer_exist_are_forgotten(self):
        prefs = settings.reset({'favorites': ['merge', 'velha'], 'recent': ['velha', 'split']})
        prefs.forget_tools({'merge', 'split'})
        self.assertEqual(prefs.get('favorites'), ['merge'])
        self.assertEqual(prefs.get('recent'), ['split'])

    def test_the_last_folder_never_goes_to_the_file(self):
        prefs = settings.load(self.file)
        prefs.set('last_folder', r'C:\Folhas\Maria Fictícia 12345')
        self.assertNotIn('last_folder', json.loads(self.file.read_text(encoding='utf-8')))
        self.file.write_text(json.dumps({'last_folder': r'C:\outra'}), encoding='utf-8')
        self.assertEqual(settings.load(self.file).get('last_folder'), '')  # nem é lido de um arquivo editado

    def test_lists_returned_are_copies(self):
        prefs = settings.reset()
        prefs.get('favorites').append('x')
        self.assertEqual(prefs.get('favorites'), [])


if __name__ == '__main__':
    unittest.main()
