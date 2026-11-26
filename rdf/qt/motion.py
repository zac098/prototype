"""Movimento da interface Qt: respeita a configuração de animações do Windows (acessibilidade)."""

import ctypes
import sys

SPI_GETCLIENTAREAANIMATION = 0x1042

_enabled = None


def animations_enabled():
    """False quando o usuário desligou as animações do Windows. Fora do Windows, True."""
    global _enabled
    if _enabled is None:
        _enabled = True
        if sys.platform == 'win32':
            try:
                flag = ctypes.c_int(1)
                if ctypes.windll.user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(flag), 0):
                    _enabled = bool(flag.value)
            except (AttributeError, OSError):
                pass
    return _enabled
