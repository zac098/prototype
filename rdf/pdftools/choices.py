"""Opções das ferramentas (níveis de compressão, tamanhos de papel, posições...), num módulo leve.

O catálogo (registry.py) monta os formulários com estas listas sem carregar o PyMuPDF nem o Pillow; as operações
(ops.py) usam as mesmas listas para traduzir a escolha do usuário em números.
"""

# Compressão: (maior lado das imagens em pixels, qualidade JPEG); None = não reduz as imagens
COMPRESSION_LEVELS = {
    'Baixa (melhor qualidade)': (None, 0),
    'Recomendada': (1600, 70),
    'Extrema (menor tamanho)': (1100, 45),
}

OCR_LANGUAGES = {'Português + Inglês': 'por+eng', 'Português': 'por', 'Inglês': 'eng'}

# Imagens para PDF: tamanho da página (pontos) e margem (pontos)
PAGE_SIZES = {'Ajustar à imagem': None, 'A4': (595, 842), 'Carta': (612, 792)}
MARGINS = {'Nenhuma': 0, 'Pequena': 18, 'Grande': 40}

ROTATIONS = {'90° para a direita': 90, '180°': 180, '90° para a esquerda': 270}

NUMBER_POSITIONS = (
    'Inferior centralizado',
    'Inferior direita',
    'Inferior esquerda',
    'Superior centralizado',
    'Superior direita',
    'Superior esquerda',
)
NUMBER_FORMATS = ('1', 'Página 1', 'Página 1 de N', '1 / N')

WATERMARK_COLORS = {
    'Cinza': (0.5, 0.5, 0.5),
    'Vermelho': (0.8, 0.1, 0.1),
    'Azul': (0.1, 0.3, 0.75),
    'Preto': (0, 0, 0),
}

# Tamanho do papel (pontos, em pé)
PAPER_SIZES = {'A4': (595.0, 842.0), 'Carta': (612.0, 792.0), 'Ofício': (612.0, 1008.0), 'A3': (842.0, 1191.0)}
