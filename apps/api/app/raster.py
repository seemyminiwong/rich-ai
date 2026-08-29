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


def hex_rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def mix(value: str, target: str, ratio: float) -> str:
    """value -> target на ratio (0..1). Для похідних відтінків палітри."""
    a, b = hex_rgb(value), hex_rgb(target)
    return '#%02X%02X%02X' % tuple(round(a[i] + (b[i] - a[i]) * ratio) for i in range(3))


def relative_luminance(color: str) -> float:
    """Відносна яскравість за WCAG - основа розрахунку контрасту."""
    def channel(value: int) -> float:
        v = value / 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in hex_rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(one: str, two: str) -> float:
    """Коефіцієнт контрасту WCAG: 1 - однакові, 21 - чорне на білому."""
    a, b = relative_luminance(one), relative_luminance(two)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def readable_on(color: str, background: str, target: float = 4.5) -> str:
    """Підсунути колір до читабельності на цьому тлі, зберігши відтінок.

    Живе тут, а не в pipeline: цим користується і студія (кольори сторінки),
    і інфографіка (колір іконок на полотні), а спільного предка в них немає.

    Рухаємось до білого на темному тлі і до чорного на світлому: відтінок
    лишається, міняється світлота. 50 кроків завжди досягають межі, бо
    крайня точка - чистий білий або чорний - дає максимум можливого.
    """
    if contrast_ratio(color, background) >= target:
        return color
    goal = '#FFFFFF' if relative_luminance(background) < 0.18 else '#000000'
    candidate = color
    for step in range(1, 51):
        candidate = mix(color, goal, step / 50)
        if contrast_ratio(candidate, background) >= target:
            break
    return candidate
