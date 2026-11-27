"""Preferências do usuário: tema, ferramentas favoritas e recentes, tamanho da janela e outras escolhas.

Ficam num JSON pequeno na pasta de dados do RDF (config.SETTINGS_FILE). Como o resto do projeto, importar este módulo
não toca no disco: até alguém chamar load(), as preferências vivem só na memória (é assim nos testes). O arquivo é
gravado por cima do anterior sem nunca ficar pela metade, e um arquivo danificado ou editado à mão nunca derruba o
app: cada valor é conferido e, se não servir, volta ao padrão.

Nada aqui guarda dados de documentos (nomes, matrículas): só escolhas de uso do próprio app.
"""

import json
import logging
import os
from pathlib import Path

LOGGER = logging.getLogger('rdf')

THEMES = ('sistema', 'claro', 'escuro')
MAX_RECENT = 6
MAX_TEXT_LENGTH = 8192  # o maior texto guardado é o tamanho da janela (algumas centenas de caracteres)

DEFAULTS = {
    'theme': 'sistema',
    'favorites': [],  # ids das ferramentas marcadas com estrela, na ordem em que foram marcadas
    'recent': [],  # ids das ferramentas usadas, da mais recente para a mais antiga
    'open_folder_after': False,  # abrir a pasta do resultado ao terminar uma ferramenta
    'window_geometry': '',  # tamanho e posição da janela (base64 do Qt)
    'last_folder': '',  # a última pasta usada nas janelas de escolher arquivos (só na memória: ver TRANSIENT)
}
# Só na memória, nunca no arquivo: o nome de uma pasta pode ter o nome ou a matrícula de alguém.
TRANSIENT = frozenset({'last_folder'})


def _valid_ids(value, limit=None):
    if not isinstance(value, list):
        return None
    ids = []
    for item in value:
        if isinstance(item, str) and item and len(item) <= 64 and item not in ids:
            ids.append(item)
    return ids[:limit] if limit else ids


def _clean(key, value):
    """O valor conferido, ou None se não serve para esta chave (aí vale o padrão)."""
    default = DEFAULTS[key]
    if key == 'theme':
        return value if value in THEMES else None
    if key == 'favorites':
        return _valid_ids(value)
    if key == 'recent':
        return _valid_ids(value, MAX_RECENT)
    if isinstance(default, bool):
        return value if isinstance(value, bool) else None
    if isinstance(default, str):
        return value if isinstance(value, str) and len(value) <= MAX_TEXT_LENGTH else None
    return None


class Settings:
    """As preferências em memória; com path, cada mudança é gravada no disco."""

    def __init__(self, path=None, data=None):
        self.path = Path(path) if path else None
        self._data = {key: (list(value) if isinstance(value, list) else value) for key, value in DEFAULTS.items()}
        for key, value in (data or {}).items():
            if key in DEFAULTS and not (path and key in TRANSIENT):  # do arquivo, nunca o que é só da sessão
                cleaned = _clean(key, value)
                if cleaned is not None:
                    self._data[key] = cleaned

    @classmethod
    def from_file(cls, path):
        """Lê as preferências do arquivo. Ausente, danificado ou de outro formato: começa do padrão."""
        path = Path(path)
        data = {}
        try:
            if path.is_file():
                loaded = json.loads(path.read_text(encoding='utf-8'))
                data = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            LOGGER.warning('Preferências danificadas em %s; usando o padrão', path)
        return cls(path, data)

    # ---- leitura e escrita ---------------------------------------------------------------
    def get(self, key):
        value = self._data[key]
        return list(value) if isinstance(value, list) else value

    def set(self, key, value):
        """Troca um valor (conferido) e grava. Devolve o valor que ficou valendo."""
        if key not in DEFAULTS:
            raise KeyError(key)
        cleaned = _clean(key, value)
        if cleaned is None:
            cleaned = DEFAULTS[key]
        if self._data[key] != cleaned:
            self._data[key] = list(cleaned) if isinstance(cleaned, list) else cleaned
            self.save()
        return self.get(key)

    def as_dict(self):
        return {key: self.get(key) for key in DEFAULTS}

    def persisted(self):
        """O que vai para o arquivo: tudo menos o que é só da sessão (TRANSIENT)."""
        return {key: value for key, value in self.as_dict().items() if key not in TRANSIENT}

    def save(self):
        """Grava sem nunca deixar o arquivo pela metade. True se gravou (sem caminho, não grava)."""
        if self.path is None:
            return False
        temp = self.path.with_suffix('.tmp')
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(json.dumps({'version': 1, **self.persisted()}, ensure_ascii=False, indent=2), 'utf-8')
            os.replace(temp, self.path)
            return True
        except OSError:
            LOGGER.warning('Não foi possível gravar as preferências em %s', self.path, exc_info=True)
            temp.unlink(missing_ok=True)
            return False

    # ---- atalhos para as listas ----------------------------------------------------------
    def is_favorite(self, tool_id):
        return tool_id in self._data['favorites']

    def toggle_favorite(self, tool_id):
        """Marca ou desmarca a ferramenta como favorita. Devolve True se ela ficou favorita."""
        favorites = self.get('favorites')
        if tool_id in favorites:
            favorites.remove(tool_id)
        else:
            favorites.append(tool_id)
        self.set('favorites', favorites)
        return tool_id in favorites

    def record_use(self, tool_id):
        """Põe a ferramenta no topo das recentes."""
        recent = [item for item in self.get('recent') if item != tool_id]
        self.set('recent', [tool_id, *recent][:MAX_RECENT])

    def forget_tools(self, valid_ids):
        """Tira das listas as ferramentas que não existem mais (removidas numa versão nova)."""
        valid = set(valid_ids)
        for key in ('favorites', 'recent'):
            kept = [item for item in self.get(key) if item in valid]
            if kept != self._data[key]:
                self.set(key, kept)


_current = Settings()


def current():
    """As preferências em uso pelo app (em memória até load ser chamado)."""
    return _current


def load(path):
    """Passa a ler e gravar as preferências no arquivo (chamado uma vez, ao abrir o app)."""
    global _current
    _current = Settings.from_file(path)
    return _current


def reset(data=None):
    """Volta às preferências padrão, só em memória (usado pelos testes)."""
    global _current
    _current = Settings(data=data)
    return _current
