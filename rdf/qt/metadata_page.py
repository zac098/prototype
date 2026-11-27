"""Tela "Metadados do PDF": a tela padrão, mostrando e preenchendo as informações atuais do arquivo escolhido.

Ao adicionar o arquivo, os campos de título, autor, assunto e palavras-chave já vêm com o que está gravado nele, e um
quadro mostra o que normalmente fica escondido: o programa que criou o PDF e as datas. Assim dá para ver o que vai ser
removido (ou corrigido) antes de salvar.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from rdf.pdftools import ops
from rdf.qt.tool_page import ToolPage

INFO_FIELDS = (
    ('author', 'Autor'),
    ('creator', 'Programa que criou'),
    ('producer', 'Gerado por'),
    ('created', 'Criado em'),
    ('modified', 'Modificado em'),
)


class MetadataPage(ToolPage):
    def build_extra_options(self):
        self.info_box = QFrame()
        self.info_box.setObjectName('card')
        layout = QVBoxLayout(self.info_box)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        title = QLabel('Informações atuais do arquivo')
        title.setObjectName('fieldLabel')
        layout.addWidget(title)
        self.info_label = QLabel('Adicione um PDF para ver o que está gravado nele.')
        self.info_label.setObjectName('hint')
        self.info_label.setWordWrap(True)
        self.info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.info_label)
        return [self.info_box]

    def refresh_files(self):
        super().refresh_files()
        if hasattr(self, 'info_label'):
            self.show_metadata()

    def extra_values(self, values):
        """Campo que tinha valor e foi esvaziado: o usuário quer apagar essa informação (não "deixar como está")."""
        current = getattr(self, 'current', {}) or {}
        clear = [key for key in ('title', 'author', 'subject', 'keywords') if current.get(key) and not values.get(key)]
        return {**values, 'clear': clear}

    def show_metadata(self):
        """Mostra o que o arquivo tem gravado e preenche os campos editáveis com isso."""
        if not self.files:
            self.info_label.setText('Adicione um PDF para ver o que está gravado nele.')
            self.current = {}
            return
        pdf = self.cache.pdf_for(self.files[0])
        self.current = ops.read_metadata(pdf) if pdf else {}
        lines = [f'{label}: {self.current[key]}' for key, label in INFO_FIELDS if self.current.get(key)]
        if not pdf:
            text = 'As informações aparecem depois de processar (documento do Office).'
        elif not self.current:
            text = 'Não foi possível ler as informações (o PDF pode estar protegido por senha).'
        else:
            text = '\n'.join(lines) if lines else 'Nenhuma informação gravada: o arquivo já está limpo.'
        self.info_label.setText(text)
        for key in ('title', 'author', 'subject', 'keywords'):
            widget = self.widgets.get(key)
            if widget is not None:
                widget.setText(self.current.get(key, ''))
