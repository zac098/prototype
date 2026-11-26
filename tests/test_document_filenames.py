import unittest
import _source  # coloca a raiz do projeto no sys.path
from rdf.core.naming import compose_document_filename

NS = {"compose_document_filename": compose_document_filename}


class Tests(unittest.TestCase):
    def test_atestado_sequence(self):
        self.assertEqual(NS["compose_document_filename"]("79441 - 1.pdf", "Atestado"), "79441 - ATESTADO 1.PDF")

    def test_declaracao_no_duplicate(self):
        self.assertEqual(
            NS["compose_document_filename"]("79441 - DECLARAÇÃO.pdf", "Declaração"), "79441 - DECLARAÇÃO.PDF"
        )

    def test_renamed_document_is_uppercase(self):
        self.assertEqual(
            NS["compose_document_filename"]("Nome Sobrenome.pdf", "Atestado"), "NOME SOBRENOME - ATESTADO.PDF"
        )


if __name__ == "__main__":
    unittest.main()
