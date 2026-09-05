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


# --- Виріз пакшота і зафіксована композиція Hero ------------------------------
# Навіщо: модель-редактор із самого лише промпта не гарантує ані логотип, ані
# ракурс, ані місце товару в кадрі - вона все це «перемальовує». Якщо ж товар
# вирізати з пакшота й покласти на полотно самим, а моделі віддати маску, вона
# малює лише середовище. Після генерації оригінальні пікселі товару вклеюються
# назад - ідентичність гарантована байтами, а не проханням.

_CUTOUT_WORK_SIZE = 1024   # заливка тла - чисто пітонівська; на 1024px це секунди
_BG_LIGHT_MIN = 222        # «біле» тло пакшота: усі канали не темніші за це
_BG_UNIFORM_SHARE = 0.85   # частка периметра, що має збігатись із кольором тла
_EDGE_LO, _EDGE_MID, _EDGE_HI = 20, 40, 96  # відстань від тла: <LO тло, <MID ще тінь, >=HI товар
_SOFT_ZONE_MAX_SHARE = 0.18  # м'яка зона більша за 18% товару = сріблястий корпус, не тінь


def _border_pixels(image: Image.Image) -> list:
    width, height = image.size
    px = image.load()
    out = []
    for x in range(width):
        out.append(px[x, 0]); out.append(px[x, height - 1])
    for y in range(1, height - 1):
        out.append(px[0, y]); out.append(px[width - 1, y])
    return out


def cutout_product(image: Image.Image):
    """RGBA-виріз товару з пакшота (обрізаний по межах) або None.

    None означає «це не пакшот» - тло не однорідне світле (лайфстайл-фото,
    інтер'єр) - і виклик має піти звичайним шляхом редагування без маски.
    Готова прозорість у PNG береться як є: магазин уже вирізав товар.
    """
    from PIL import ImageChops, ImageFilter
    if has_alpha(image):
        rgba = image.convert('RGBA')
        bbox = alpha_bbox(rgba)
        if bbox and _plausible_subject(bbox, rgba.size):
            return rgba.crop(bbox)
        return None
    rgb = image.convert('RGB')
    work = rgb.copy()
    work.thumbnail((_CUTOUT_WORK_SIZE, _CUTOUT_WORK_SIZE), Image.Resampling.LANCZOS)
    border = _border_pixels(work)
    if not border:
        return None
    bg = tuple(round(sum(p[i] for p in border) / len(border)) for i in range(3))
    if min(bg) < _BG_LIGHT_MIN:
        return None
    close = sum(1 for p in border if max(abs(p[i] - bg[i]) for i in range(3)) < _EDGE_LO)
    if close < len(border) * _BG_UNIFORM_SHARE:
        return None
    # відстань кожного пікселя від кольору тла (максимум по каналах)
    diff = ImageChops.difference(work, Image.new('RGB', work.size, bg))
    r, g, b = diff.split()
    distance = ImageChops.lighter(ImageChops.lighter(r, g), b)
    # Заливка з периметра лишає тільки ЗВ'ЯЗНЕ з краєм тло: білі деталі всередині
    # товару (кнопки, екран) не сполучені з краєм і лишаються товаром. Два пороги:
    # жорсткий - саме тло; м'який - його продовження у краплю тіні/відблиску під
    # товаром, яку пакшот часто несе з собою. У м'якій зоні альфа йде рампою по
    # відстані від кольору тла, тому світла частина тіні прозоріє, темна лишається
    # напівпрозорою і після зняття білого стає природною тінню на будь-якій сцені.
    tight = _flood_from_border(distance, _EDGE_LO)
    loose = _flood_from_border(distance, _EDGE_MID)
    width, height = work.size
    soft_zone = ImageChops.subtract(loose, tight)
    soft_share = _coverage(soft_zone)
    # Сріблястий або білий товар «тече» у м'яку зону широкою смугою - тоді
    # ключування по кольору ненадійне, і краще лишити старий шлях без маски.
    subject = _coverage(ImageChops.invert(tight))
    if subject <= 0 or soft_share / subject > _SOFT_ZONE_MAX_SHARE:
        return None
    ramp = distance.point(lambda v: 0 if v <= _EDGE_LO else (255 if v >= _EDGE_HI else round((v - _EDGE_LO) * 255 / (_EDGE_HI - _EDGE_LO))))
    edge_zone = loose.filter(ImageFilter.MaxFilter(3))
    alpha_small = Image.composite(ramp, Image.new('L', work.size, 255), edge_zone)
    alpha = alpha_small.resize(rgb.size, Image.Resampling.LANCZOS) if alpha_small.size != rgb.size else alpha_small
    rgba = rgb.convert('RGBA')
    rgba.putalpha(alpha)
    _decontaminate_edge(rgba, bg)
    bbox = alpha_bbox(rgba, threshold=24)
    if not bbox or not _plausible_subject(bbox, rgba.size):
        return None
    return rgba.crop(bbox)


def _flood_from_border(distance: Image.Image, threshold: int) -> Image.Image:
    """Маска (L, 255) пікселів з відстанню < threshold, ЗВ'ЯЗНИХ із периметром."""
    from PIL import ImageDraw
    like = distance.point(lambda v: 255 if v < threshold else 0)
    width, height = like.size
    px = like.load()
    seeds = [(x, y) for x in range(width) for y in (0, height - 1)] + \
            [(x, y) for y in range(height) for x in (0, width - 1)]
    for seed in seeds:
        if px[seed] == 255:
            ImageDraw.floodfill(like, seed, 128)
    return like.point(lambda v: 255 if v == 128 else 0)


def _coverage(mask: Image.Image) -> float:
    """Частка пікселів маски зі значенням 255."""
    histogram = mask.histogram()
    return histogram[255] / max(1, mask.width * mask.height)


def _decontaminate_edge(rgba: Image.Image, bg: tuple) -> None:
    """Зняти колір тла з напівпрозорого краю (in place).

    Піксель краю пакшота - суміш товару з білим тлом. Покладений на темну сцену
    як є, він дає світлий ореол по контуру. Розмішуємо назад: c = (c - bg·(1-a)) / a.
    Обходимо лише напівпрозорі пікселі - їх тисячі, а не мільйони.
    """
    alpha_values = rgba.getchannel('A').tobytes()
    px = rgba.load()
    width = rgba.width
    for index, a in enumerate(alpha_values):
        if a == 0 or a == 255:
            continue
        x, y = index % width, index // width
        r, g, b, _ = px[x, y]
        share = a / 255
        rest = 1 - share
        px[x, y] = (
            max(0, min(255, round((r - bg[0] * rest) / share))),
            max(0, min(255, round((g - bg[1] * rest) / share))),
            max(0, min(255, round((b - bg[2] * rest) / share))),
            a,
        )


def _plausible_subject(bbox, size) -> bool:
    """Виріз схожий на товар: не дрібничка і не весь кадр без тла."""
    (x0, y0, x1, y1), (width, height) = bbox, size
    share = ((x1 - x0) * (y1 - y0)) / max(1, width * height)
    return 0.04 <= share <= 0.96


# Зона товару на полотні Hero, частками ширини/висоти. Збігається з промптами:
# десктоп - товар праворуч на 38-46% полотна, ліворуч спокійне місце під текст;
# мобайл - товар у верхній половині, під ним місце під текст.
HERO_ZONES = {
    'desktop': (0.53, 0.08, 0.96, 0.92),
    'mobile': (0.08, 0.06, 0.92, 0.52),
}
HERO_CANVAS_FILL = (26, 33, 40, 255)  # #1A2128 - темна поверхня студії


def compose_hero_canvas(cutout: Image.Image, size: tuple[int, int], variant: str):
    """Полотно з товаром на його місці, маска для редактора і рамка вставки.

    Повертає (canvas RGB, mask RGBA, (x, y, w, h), scaled RGBA). Маска у форматі
    OpenAI: прозоре = можна малювати, непрозоре = не чіпати (товар).
    """
    width, height = size
    zx0, zy0, zx1, zy1 = HERO_ZONES.get(variant, HERO_ZONES['desktop'])
    zone_w, zone_h = int(width * (zx1 - zx0)), int(height * (zy1 - zy0))
    scale = min(zone_w / cutout.width, zone_h / cutout.height)
    new_w, new_h = max(1, round(cutout.width * scale)), max(1, round(cutout.height * scale))
    scaled = cutout.resize((new_w, new_h), Image.Resampling.LANCZOS)
    x = int(width * zx0) + (zone_w - new_w) // 2
    y = int(height * zy0) + (zone_h - new_h) // 2
    canvas = Image.new('RGBA', size, HERO_CANVAS_FILL)
    canvas.alpha_composite(scaled, (x, y))
    # Полотно непрозоре за побудовою (заливка з альфою 255), тож RGB тут не
    # ховає чорного під прозорістю - це просто формат для редактора.
    canvas = canvas.convert('RGB')
    hard = scaled.getchannel('A').point(lambda v: 255 if v > 127 else 0)
    mask = Image.new('RGBA', size, (0, 0, 0, 0))
    keep = Image.new('RGBA', scaled.size, (0, 0, 0, 255))
    keep.putalpha(hard)
    mask.alpha_composite(keep, (x, y))
    return canvas, mask, (x, y, new_w, new_h), scaled


def paste_product_back(result: Image.Image, scaled: Image.Image, box, size: tuple[int, int]) -> Image.Image:
    """Оригінальні пікселі товару поверх згенерованого кадру - остаточна гарантія."""
    frame = result.convert('RGBA')
    if frame.size != tuple(size):
        frame = frame.resize(size, Image.Resampling.LANCZOS)
    x, y, _, _ = box
    frame.alpha_composite(scaled, (x, y))
    return frame.convert('RGB')
