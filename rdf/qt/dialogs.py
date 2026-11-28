"""Diálogos do renomeador (Qt): PDF com várias páginas, edição de dados e confirmações de análise e exportação."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from rdf.core.naming import safe_filename
from rdf.core.parsing import MONTH_OPTIONS
from rdf.qt.widgets import SpinBox


def _dialog(parent, title, width=460):
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setModal(True)
    dialog.setMinimumWidth(width)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(10)
    return dialog, layout


def _heading(text, tone=None):
    label = QLabel(text)
    label.setObjectName('pageTitle')
    if tone == 'error':
        label.setObjectName('dialogTitle')
        label.setProperty('tone', 'error')
    return label


def _paragraph(text, wrap=480):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setMaximumWidth(wrap)
    label.setObjectName('pageLead')
    return label


def _button(text, value, dialog, result, variant=None):
    button = QPushButton(text)
    if variant:
        button.setProperty('variant', variant)

    def choose():
        result.append(value)
        dialog.accept()

    button.clicked.connect(choose)
    return button


def multipage_dialog(parent, path, total):
    """PDF com várias páginas: ('split', 0), ('keep', página usada na leitura, base 0) ou ('ignore', 0)."""
    dialog, layout = _dialog(parent, 'PDF com várias páginas', 500)
    layout.addWidget(_heading('PDF com várias páginas detectado'))
    layout.addWidget(_paragraph(f'{Path(path).name} possui {total} páginas.\nEscolha como o arquivo deve ser tratado.'))
    result = []
    layout.addWidget(_button('Separar páginas e renomear todas', 'split', dialog, result, 'primary'))
    group = QFrame()
    group.setObjectName('card')
    inner = QVBoxLayout(group)
    inner.setContentsMargins(14, 12, 14, 12)
    inner.addWidget(QLabel('Manter o PDF completo'))
    row = QHBoxLayout()
    row.addWidget(QLabel('Página usada para identificar os dados:'))
    spin = SpinBox()
    spin.setRange(1, total)
    row.addWidget(spin)
    row.addStretch(1)
    inner.addLayout(row)
    keep = _button('Manter completo', 'keep', dialog, result)
    inner.addWidget(keep)
    layout.addWidget(group)
    layout.addWidget(_button('Ignorar este arquivo', 'ignore', dialog, result, 'quiet'))
    dialog.exec()
    choice = result[0] if result else 'ignore'
    return choice, (spin.value() - 1 if choice == 'keep' else 0)


def edit_dialog(parent, row):
    """Corrigir matrícula, nome e mês. Devolve {'chapa', 'nome', 'mes'} ou None se cancelou."""
    dialog, layout = _dialog(parent, 'Corrigir dados', 460)
    form = QFormLayout()
    form.setLabelAlignment(Qt.AlignLeft)
    form.setHorizontalSpacing(14)
    form.setVerticalSpacing(10)
    chapa = QLineEdit(row.get('chapa') or '')
    chapa.setObjectName('editChapa')
    nome = QLineEdit(row.get('nome') or '')
    nome.setObjectName('editNome')
    mes = QComboBox()
    mes.setObjectName('editMes')
    mes.addItems(['', *MONTH_OPTIONS])
    current = str(row.get('mes') or '').strip().upper()
    if current and mes.findText(current) < 0:
        # Mês fora da lista (sessão antiga, "MARCO" sem cedilha...): fica como opção, para salvar não apagá-lo.
        mes.addItem(current)
    mes.setCurrentText(current)
    form.addRow('Matrícula/Chapa:', chapa)
    form.addRow('Nome:', nome)
    form.addRow('Mês da folha:', mes)
    layout.addLayout(form)
    note = QLabel('Preencha ao menos um dos campos.')
    note.setObjectName('hint')
    layout.addWidget(note)
    buttons = QDialogButtonBox()
    save = buttons.addButton('Salvar correção', QDialogButtonBox.AcceptRole)
    save.setProperty('variant', 'primary')
    save.setObjectName('saveCorrection')
    cancel = buttons.addButton('Cancelar', QDialogButtonBox.RejectRole)
    save.clicked.connect(dialog.accept)
    cancel.clicked.connect(dialog.reject)
    layout.addWidget(buttons)

    def update_save():
        filled = any(text.strip() for text in (chapa.text(), nome.text(), mes.currentText()))
        save.setEnabled(filled)  # uma correção sem nada viraria "CORRIGIDO" com o nome original
        note.setVisible(not filled)

    for signal in (chapa.textChanged, nome.textChanged, mes.currentTextChanged):
        signal.connect(update_save)
    update_save()
    chapa.setFocus()
    if dialog.exec() != QDialog.Accepted:
        return None
    return {
        'chapa': safe_filename(chapa.text()),
        'nome': safe_filename(nome.text()),
        'mes': safe_filename(mes.currentText()),
    }


def cancel_analysis_dialog(parent):
    """'keep' (manter os resultados e parar), 'discard' (descartar) ou 'continue'."""
    dialog, layout = _dialog(parent, 'Cancelar análise', 500)
    layout.addWidget(_heading('Cancelar a análise em andamento?'))
    layout.addWidget(
        _paragraph(
            'Os arquivos que já estão sendo lidos serão finalizados com segurança.\n'
            'Nenhum novo arquivo será iniciado depois do cancelamento.'
        )
    )
    result = []
    layout.addWidget(_button('Manter resultados e parar', 'keep', dialog, result, 'primary'))
    layout.addWidget(_button('Descartar resultados desta análise', 'discard', dialog, result))
    layout.addWidget(_button('Continuar análise', 'continue', dialog, result, 'quiet'))
    dialog.exec()
    return result[0] if result else 'continue'


def review_export_dialog(parent, review_items):
    """'review' (revisar os arquivos), 'proceed' (exportar mesmo assim) ou 'cancel'."""
    dialog, layout = _dialog(parent, 'Arquivos precisam de revisão', 500)
    layout.addWidget(_heading('Arquivos precisam de revisão'))
    layout.addWidget(
        _paragraph(
            f'Foram encontrados {len(review_items)} arquivo(s) marcado(s) como REVISAR.\n'
            'Os nomes podem estar incompletos ou ter baixa confiança.\n\n'
            'Escolha revisar os arquivos ou prosseguir com os nomes atuais.'
        )
    )
    names = '\n'.join(f'- {Path(path).name}' for path in review_items[:6])
    if len(review_items) > 6:
        names += f'\n... e mais {len(review_items) - 6} arquivo(s).'
    listing = QLabel(names)
    listing.setProperty('tone', 'review')
    layout.addWidget(listing)
    result = []
    row = QHBoxLayout()
    row.addStretch(1)
    row.addWidget(_button('Cancelar', 'cancel', dialog, result, 'quiet'))
    row.addWidget(_button('Prosseguir mesmo assim', 'proceed', dialog, result, 'success'))
    row.addWidget(_button('Revisar arquivos', 'review', dialog, result, 'primary'))
    layout.addLayout(row)
    dialog.exec()
    return result[0] if result else 'cancel'


def blocking_export_dialog(parent, problems):
    """'show' (mostrar os arquivos bloqueados) ou 'close'."""
    dialog, layout = _dialog(parent, 'Exportação bloqueada', 540)
    layout.addWidget(_heading('Não é possível exportar', 'error'))
    layout.addWidget(
        _paragraph(
            f'Foram encontrados {len(problems)} arquivo(s) com problemas que bloqueiam a exportação.\n'
            'Corrija ou remova esses itens antes de tentar novamente.'
        )
    )
    details = [f'- {Path(path).name}: {reason}' for path, reason in problems[:8]]
    if len(problems) > 8:
        details.append(f'... e mais {len(problems) - 8} arquivo(s).')
    listing = QLabel('\n'.join(details))
    listing.setWordWrap(True)
    listing.setProperty('tone', 'blocked')
    layout.addWidget(listing)
    result = []
    row = QHBoxLayout()
    row.addStretch(1)
    row.addWidget(_button('Fechar', 'close', dialog, result, 'quiet'))
    row.addWidget(_button('Mostrar bloqueados', 'show', dialog, result, 'primary'))
    layout.addLayout(row)
    dialog.exec()
    return result[0] if result else 'close'
