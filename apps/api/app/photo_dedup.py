"""Той самий кадр під різними адресами: порівняння за пікселями, а не за URL.

Жива скарга (ARTLINE Master, Growatt AURA 5000): сцена «-30° у снігу» стояла на
сторінці двічі - квадратний кадр галереї (2000×2000) і широкий банер з опису
(1015×540). Адреси різні, кадрування різне, тож перевірка за src їх не бачила.
У галереях магазину трапляються й дослівні копії: у Bambu A1 mini і A1 mini Combo
однакові кадри мають різні адреси.

Підпис кадру - мініатюра в сірому висотою SIGNATURE_HEIGHT. Вужчий кадр шукається
всередині ширшого на кількох масштабах (перетин кадрування); фрагмент і шаблон
окремо проходять автоконтраст (обрізаний кадр має інший розподіл яскравості),
міра - найменша середня абсолютна різниця пікселів. Заміри на живих кадрах:
дублікати 0-4, різні ракурси того самого товару на білому тлі 25-33, різні
сцени 47+. Поріг DUPLICATE_MAX_DIFF лежить між ними з запасом в обидва боки.
"""
from collections.abc import Callable

from PIL import Image, ImageChops, ImageOps, ImageStat

SIGNATURE_HEIGHT = 32
DUPLICATE_MAX_DIFF = 16.0
# Масштаби вужчого кадру відносно висоти ширшого: банер із опису часто ширше
# кадрований і дрібніший за той самий кадр у галереї.
_SCALES = tuple(x / 100 for x in range(70, 121, 5))
# Збіг меншого за третину ширини чи 60% висоти фрагмента - випадковий, не дубль.
_MIN_WIDTH_SHARE = 0.35
_MIN_HEIGHT_SHARE = 0.6


def signature(image: Image.Image) -> Image.Image:
    """Мініатюра для порівняння: сірий, висота SIGNATURE_HEIGHT."""
    gray = image.convert('L')
    width, height = gray.size
    return gray.resize((max(1, round(SIGNATURE_HEIGHT * width / max(1, height))), SIGNATURE_HEIGHT), Image.BILINEAR)


def difference(a: Image.Image, b: Image.Image) -> float:
    """Найменша середня різниця (0-255) між вужчим кадром і фрагментом ширшого."""
    if a.width / a.height < b.width / b.height:
        a, b = b, a
    best = 255.0
    for scale in _SCALES:
        height = round(SIGNATURE_HEIGHT * scale)
        width = round(height * b.width / b.height)
        template = b.resize((max(1, width), max(1, height)), Image.BILINEAR)
        if height > a.height:
            cut = (height - a.height) // 2
            template = template.crop((0, cut, width, cut + a.height))
            height = a.height
        if width > a.width:
            cut = (width - a.width) // 2
            template = template.crop((cut, 0, cut + a.width, height))
            width = a.width
        if width < a.width * _MIN_WIDTH_SHARE or height < a.height * _MIN_HEIGHT_SHARE:
            continue
        template = _contrast(template)
        for y in range(a.height - height + 1):
            for x in range(a.width - width + 1):
                window = _contrast(a.crop((x, y, x + width, y + height)))
                best = min(best, ImageStat.Stat(ImageChops.difference(window, template)).mean[0])
    return best


def _contrast(image: Image.Image) -> Image.Image:
    return ImageOps.autocontrast(image, cutoff=2)


def is_duplicate(a: Image.Image | None, b: Image.Image | None) -> bool:
    return a is not None and b is not None and difference(a, b) <= DUPLICATE_MAX_DIFF


def unique_frames(urls: list[str], signature_of: Callable[[str], Image.Image | None]) -> list[str]:
    """Список кадрів без повторів (перший лишається). Кадр без підпису не відкидається."""
    kept: list[tuple[str, Image.Image | None]] = []
    for url in urls:
        sig = signature_of(url)
        if sig is not None and any(is_duplicate(sig, other) for _, other in kept):
            continue
        kept.append((url, sig))
    return [url for url, _ in kept]
