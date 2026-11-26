"""O menu do botão direito do instalador tem uma entrada "Imprimir com o RDF" para cada formato que o app aceita."""

import re
import unittest

import _source  # coloca a raiz do projeto no sys.path
from rdf.pdftools import sources

ISS = (_source.ROOT / 'packaging' / 'installer.iss').read_text(encoding='utf-8')
KEY = r'Software\Classes\SystemFileAssociations\{ext}\shell\RDFImprimir'


def lines_for(extension):
    key = KEY.format(ext=extension)
    return [line for line in ISS.splitlines() if f'Subkey: "{key}' in line]


class ContextMenuEntriesTests(unittest.TestCase):
    def test_every_supported_extension_has_the_three_entries(self):
        for extension in sorted(sources.ALL_EXTENSIONS):
            with self.subTest(extension=extension):
                lines = lines_for(extension)
                self.assertEqual(len(lines), 3, lines)
                name, icon, command = lines
                self.assertIn('ValueData: "Imprimir com o RDF"', name)
                self.assertIn('Flags: uninsdeletekey', name)  # o desinstalador apaga a entrada
                self.assertIn('ValueName: "Icon"', icon)
                self.assertIn('RDFImprimir\\command"', command)
                self.assertIn('--imprimir ""%1""', command)  # o arquivo clicado, entre aspas
                for line in lines:
                    self.assertIn('Tasks: contextmenu', line)

    def test_the_installer_adds_nothing_for_formats_the_app_does_not_accept(self):
        found = set(re.findall(r'SystemFileAssociations\\(\.[a-z0-9]+)\\shell\\RDFImprimir', ISS))
        self.assertEqual(found, set(sources.ALL_EXTENSIONS))

    def test_the_entries_are_per_user_so_no_administrator_is_needed(self):
        self.assertIn('PrivilegesRequired=lowest', ISS)
        for line in ISS.splitlines():
            if 'SystemFileAssociations' in line:
                self.assertTrue(line.startswith('Root: HKA;'), line)  # HKA vira HKCU com PrivilegesRequired=lowest

    def test_send_to_takes_any_amount_of_files_of_any_supported_format(self):
        self.assertIn('{sendto}\\RDF - Imprimir arquivos', ISS)
        self.assertIn('Parameters: "--imprimir"', ISS)


if __name__ == '__main__':
    unittest.main()
