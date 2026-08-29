"""Растрові нормалізації, спільні для студії та інфографіки.

Модуль навмисно крихітний і без залежностей від config: його потребують і
pipeline, і main, і infographic, а спільного предка в них немає - будь-яке
інше місце дало б цикл імпорту.
"""
from PIL import Image

# Режими, у яких Pillow тримає прозорість. 'P' - лише коли в палітрі є
# прозорий індекс; без нього це звичайна індексована картинка.
_ALPHA_MODES = ('RGBA', 'LA', 'PA')


def has_alpha(image: Image.Image) -> bool:
    """Чи є в кадрі прозорість, яку зітре переведення в RGB."""
    if image.mode in _ALPHA_MODES:
        return True
    return image.mode == 'P' and 'transparency' in image.info


def flatten_to_white(image: Image.Image) -> Image.Image:
    """RGB-копія кадру; прозорість підкладається БІЛИМ, а не чорним.

    Pillow'ів convert('RGB') просто відкидає альфу, лишаючи під нею нуль -
    тобто чорний. Для пакшотів у PNG з прозорим тлом це давало вугільну плашку
    посеред світлої палітри (жива скарга зі скріншотом: акумулятор Deye на
    чорному). Причому одразу в двох місцях: у збереженому WEBP, куди чорне
    запікалось назавжди, і в пробі периметра, яка через це фарбувала слот у
    #000000.

    Біле - те саме тло, на якому кадр товару лежить у всіх стилях студії
    (contain-рамка без відомого кольору теж біла), тож підкладка непомітна.
    """
    if not has_alpha(image):
        return image if image.mode == 'RGB' else image.convert('RGB')
    source = image.convert('RGBA')
    sheet = Image.new('RGBA', source.size, (255, 255, 255, 255))
    return Image.alpha_composite(sheet, source).convert('RGB')


def alpha_bbox(image: Image.Image, threshold: int = 8):
    """Межі непрозорого вмісту або None, якщо прозорості немає / кадр порожній.

    Точніше за пошук однорідної рамки по кольору: альфа вже КАЖЕ, де порожнеча.
    """
    if not has_alpha(image):
        return None
    alpha = image.convert('RGBA').getchannel('A')
    return alpha.point(lambda value: 255 if value > threshold else 0).getbbox()
