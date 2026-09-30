"""Редагування тексту готової rich-сторінки без дотику до верстки.

Оператор править слова, а не HTML: сторінка розкладається на текстові
фрагменти (заголовки, абзаци, пункти, питання FAQ, alt зображень) з
детермінованими ключами. Збереження підставляє нові слова в ТІ САМІ вузли
того самого артефакту і створює нову версію - сітка, стилі, зображення й
коментарі блоків лишаються байт у байт.

Ключі стабільні, бо обидві сторони (показ і збереження) нумерують вузли
одного й того самого збереженого HTML однією функцією.
"""
import re

from bs4 import BeautifulSoup, Comment, NavigableString

from app.artline_standard import _blocks

_SKIP = {'style', 'script', 'noscript', 'template', 'iframe', 'svg'}
# Роль фрагмента - за найближчим змістовим предком
_KINDS = {'h2': 'heading', 'h3': 'subheading', 'summary': 'question', 'li': 'item', 'p': 'text'}
MAX_SEGMENT = 2000


def _hidden(node) -> bool:
    for parent in node.parents:
        if getattr(parent, 'name', None) in _SKIP:
            return True
        if getattr(parent, 'get', None) and parent.get('aria-hidden') == 'true':
            return True
    return False


def _kind(node) -> str:
    for parent in node.parents:
        name = getattr(parent, 'name', None)
        if name in _KINDS:
            return _KINDS[name]
        if name in ('section', None):
            break
    return 'label'


# Текстовий контейнер редагується ЦІЛИМ, якщо всередині лише жирне виділення:
# «Корпус з <b>430 мм</b> GPU.» - одне поле «Корпус з **430 мм** GPU.», а не три
# уривки. Інші вкладені теги (span-чипи, посилання, <br>) - поле на кожен вузол.
_CONTAINERS = {'p', 'li', 'h2', 'h3', 'h4', 'summary', 'dt', 'dd', 'td', 'th', 'figcaption'}
_BOLD = {'b', 'strong'}


def _container(node):
    for parent in node.parents:
        name = getattr(parent, 'name', None)
        if name in _CONTAINERS:
            tags = parent.find_all(True)
            if all(t.name in _BOLD and not t.find(True) for t in tags):
                return parent
            return None
        if name in ('section', None) or name not in _BOLD:
            return None
    return None


def _unit_text(unit) -> str:
    if isinstance(unit, NavigableString):
        return ' '.join(str(unit).split())
    parts = []
    for child in unit.children:
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            parts.append(str(child))
        else:
            parts.append(f'**{child.get_text()}**')
    return ' '.join(''.join(parts).split())


def _walk(soup):
    """Фрагменти в порядку документа з ключами t0.. (текст) та a0.. (alt)."""
    root = soup.find('section')
    if root is None:
        return [], [], []
    blocks = _blocks(root)
    owner = {id(block): index for index, block in enumerate(blocks)}

    def block_of(node):
        for parent in node.parents:
            if id(parent) in owner:
                return owner[id(parent)]
        return 0

    texts, images, seen = [], [], set()
    for node in root.find_all(string=True):
        if isinstance(node, Comment) or _hidden(node):
            continue
        if not re.search(r'\w', str(node)):
            continue  # розділювачі « · », «+», «–» - частина верстки
        unit = _container(node) or node
        if id(unit) in seen:
            continue
        seen.add(id(unit))
        texts.append((f't{len(texts)}', unit, block_of(node)))
    for img in root.find_all('img'):
        if _hidden(img):
            continue
        images.append((f'a{len(images)}', img, block_of(img)))
    return texts, images, blocks


def _kind_of(unit) -> str:
    if isinstance(unit, NavigableString):
        return _kind(unit)
    return _KINDS.get(unit.name, 'text')


def _block_title(block, index: int) -> str:
    heading = block.find(['h2', 'h3']) if block is not None else None
    title = ' '.join(heading.get_text(' ', strip=True).split()) if heading else ''
    return title[:80] or f'Блок {index + 1}'


def editable_segments(markup: str) -> list:
    """Фрагменти сторінки, згруповані за візуальними блоками."""
    soup = BeautifulSoup(markup or '', 'html.parser')
    texts, images, blocks = _walk(soup)
    if not texts and not images:
        return []
    groups = [{'index': i, 'title': _block_title(b, i), 'items': []} for i, b in enumerate(blocks)] or [{'index': 0, 'title': 'Сторінка', 'items': []}]
    for key, unit, block in texts:
        groups[min(block, len(groups) - 1)]['items'].append({'key': key, 'kind': _kind_of(unit), 'text': _unit_text(unit)})
    for key, img, block in images:
        groups[min(block, len(groups) - 1)]['items'].append({'key': key, 'kind': 'alt', 'text': img.get('alt') or '', 'src': img.get('src') or ''})
    return [g for g in groups if g['items']]


def apply_segments(markup: str, changes: dict) -> tuple[str, int]:
    """Підставити нові тексти за ключами. Повертає (html, скільки змінено).

    Пробіли по краях вузла зберігаються: вони тримають відступи між inline-
    елементами («<b>430</b> мм»). Порожній текст не приймається - щоб
    випадково не лишити порожній заголовок чи бейдж; прибрати блок цілком -
    це правка HTML, а не тексту.
    """
    soup = BeautifulSoup(markup or '', 'html.parser')
    texts, images, _ = _walk(soup)
    by_key = {k: n for k, n, _ in texts}
    imgs = {k: i for k, i, _ in images}
    unknown = [k for k in changes if k not in by_key and k not in imgs]
    if unknown:
        raise ValueError(f'Невідомі фрагменти: {", ".join(sorted(unknown)[:5])} - сторінка змінилась, оновіть редактор')
    changed = 0
    for key, value in changes.items():
        value = ' '.join(str(value or '').split())
        if len(value) > MAX_SEGMENT:
            raise ValueError(f'Фрагмент {key} задовгий (понад {MAX_SEGMENT} символів)')
        if key in imgs:
            if (imgs[key].get('alt') or '') != value:
                imgs[key]['alt'] = value
                changed += 1
            continue
        if not value:
            raise ValueError('Порожній текст не зберігається: щоб прибрати елемент, змініть HTML')
        unit = by_key[key]
        if _unit_text(unit) == value:
            continue
        if isinstance(unit, NavigableString):
            if '**' in value:
                raise ValueError('Виділення **жирним** доступне лише для цілого абзацу, заголовка чи пункту')
            original = str(unit)
            lead = ' ' if original[:1].isspace() else ''
            tail = ' ' if original[-1:].isspace() else ''
            unit.replace_with(NavigableString(f'{lead}{value}{tail}'))
        else:
            _fill_container(soup, unit, value)
        changed += 1
    return (str(soup) if changed else markup), changed


def _fill_container(soup, unit, value: str):
    """Текст із **жирним** -> вміст контейнера. Жирний тег успадковує стиль оригіналу."""
    parts = value.split('**')
    if len(parts) % 2 == 0:
        raise ValueError(f'Непарні ** у тексті: «{value[:60]}»')
    model = unit.find(_BOLD)
    name, attrs = (model.name, dict(model.attrs)) if model is not None else ('strong', {})
    for child in list(unit.contents):
        child.extract()
    for index, part in enumerate(parts):
        if not part:
            continue
        if index % 2:
            tag = soup.new_tag(name, attrs=dict(attrs))
            tag.string = part
            unit.append(tag)
        else:
            unit.append(NavigableString(part))
