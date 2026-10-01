"""SEO / GEO / human-copy контроль як частина виробничого конвеєра.

Три різні об'єкти аудиту, три різні набори правил:

* embedded rich-фрагмент (``<section>`` усередині картки товару) - жодного
  document-level SEO (h1, title, canonical, hreflang, meta, JSON-LD); лише
  корисний текст, ієрархія h2/h3, сутності, alt, answer-first абзаци;
* standalone landing - повноцінний HTML-документ з одним h1, title,
  description, canonical, hreflang, robots, Open Graph, JSON-LD;
* внутрішній інтерфейс студії - не індексується взагалі (X-Robots-Tag).

Кожна перевірка повертає СТРУКТУРОВАНІ findings, а не одну оцінку: код, рівень,
мова, формат, блок, цитата, причина, порада. Оцінка 0-100 рахується з них
(``report_from_findings``), але користувачеві потрібні саме проблема, місце й
виправлення. Детерміновані перевірки безкоштовні і є першою лінією; платний
LLM-рецензент (``pipeline.llm_critic``) їх не замінює.

Частота ключових слів тут - діагностичний сигнал, а не ціль: обов'язкової
keyword density немає і не буде.
"""
from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Comment, NavigableString

# ---------------------------------------------------------------------------
# Мови
# ---------------------------------------------------------------------------

# Внутрішній код мови проєкту -> BCP-47 код для html lang / hreflang / JSON-LD.
LANG_MAP = {
    'ua': 'uk',
    'uk': 'uk',
    'pl': 'pl',
    'en': 'en',
    'ru': 'ru',
}


def norm_lang(code: str) -> str:
    """'ua' -> 'uk'; невідомі коди лишаються як є (у нижньому регістрі)."""
    code = str(code or '').strip().lower()
    return LANG_MAP.get(code, code.split('-', 1)[0] or 'uk')


# ---------------------------------------------------------------------------
# Верифікований профіль публікації (ARTLINE)
# ---------------------------------------------------------------------------

# Єдиний підтверджений комерційний факт: географія постачання. Локалізовані
# формулювання зафіксовані тут, щоб їх не перекладала модель. Строків, безкоштовної
# доставки, монтажу, SLA, гарантійного періоду, підтримки 24/7 і наявності на
# складі в профілі НЕМАЄ - і поки їх не затвердять, вони не потрапляють у текст.
DELIVERY_STATEMENTS = {
    'uk': 'Постачаємо обладнання по Україні та Польщі.',
    'pl': 'Dostarczamy sprzęt na terenie Ukrainy i Polski.',
    'en': 'We deliver equipment across Ukraine and Poland.',
}

DEFAULT_PUBLISHING_PROFILE = {
    'name': 'ARTLINE',
    'domains': ['artline.ua'],
    'organization_name': 'ARTLINE',
    'organization_url': 'https://artline.ua',
    'logo_url': '',
    'primary_site': True,
    'markets': ['UA', 'PL'],
    'languages': ['uk', 'pl', 'en'],
    'verified_facts': {'delivery_regions': ['Ukraine', 'Poland']},
    'statements': {'delivery': dict(DELIVERY_STATEMENTS)},
    'approved_contacts': [],
    'delivery_geography': ['Ukraine', 'Poland'],
    'warranty_text': {},
    'service_text': {},
    'version': 1,
}


def profile_snapshot(profile: dict | None) -> dict:
    """Знімок профілю для збереження в проєкті/лендінгу. Пізніша зміна
    налаштувань не переписує вже затверджений артефакт."""
    base = json.loads(json.dumps(DEFAULT_PUBLISHING_PROFILE))
    if isinstance(profile, dict):
        for key, value in profile.items():
            if value not in (None, ''):
                base[key] = value
    base['snapshot_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    return base


def company_facts(profile: dict | None, language: str) -> list[str]:
    """Локалізовані ПІДТВЕРДЖЕНІ твердження компанії для мови сторінки.
    Порожній список = у тексті не може бути жодного «ми», доставки чи гарантії."""
    profile = profile or {}
    code = norm_lang(language)
    out = []
    statements = profile.get('statements') or {}
    for group in ('delivery', 'warranty', 'service'):
        texts = statements.get(group) or {}
        if isinstance(texts, dict) and texts.get(code):
            out.append(str(texts[code]).strip())
    for key in ('warranty_text', 'service_text'):
        value = profile.get(key)
        if isinstance(value, dict) and value.get(code):
            out.append(str(value[code]).strip())
        elif isinstance(value, str) and value.strip():
            out.append(value.strip())
    for contact in profile.get('approved_contacts') or []:
        if isinstance(contact, str) and contact.strip():
            out.append(contact.strip())
    return list(dict.fromkeys(x for x in out if x))


def company_facts_block(profile: dict | None, language: str) -> str:
    """Розділ VERIFIED COMPANY FACTS для промпту."""
    facts = company_facts(profile, language)
    if not facts:
        return ('VERIFIED COMPANY FACTS: none. Do not write "we", "our service", '
                'delivery, warranty, support, stock or installation claims.')
    return 'VERIFIED COMPANY FACTS (the only allowed company claims; quote them, do not extend them):\n- ' + '\n- '.join(facts)


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

SEVERITIES = ('critical', 'warning', 'info')
FINDING_STATES = ('open', 'resolved', 'accepted')
CRITIC_TYPES_NEW = ('seo', 'geo', 'human', 'language')


def finding(code: str, severity: str, message: str, *, language: str = '', variant: str = '',
            block=None, evidence: str = '', suggestion: str = '', segment: str = '', source: str = '') -> dict:
    if severity not in SEVERITIES:
        severity = 'warning'
    row = {
        'code': code,
        'severity': severity,
        'language': language or '',
        'variant': variant or '',
        'block': block,
        'message': message,
        'evidence': (evidence or '')[:240],
        'suggestion': suggestion or '',
    }
    if segment:
        row['segment'] = segment
    if source:
        row['source'] = source
    row['key'] = finding_key(row)
    return row


def finding_key(row: dict) -> str:
    """Стабільний ключ знахідки між прогонами: тип/код/мова/формат/блок/цитата."""
    raw = '|'.join(str(row.get(k) or '') for k in ('source', 'code', 'language', 'variant', 'block')) + '|' + (row.get('evidence') or '')[:80].lower()
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]


def finding_to_text(row: dict) -> str:
    """Рядок для старого поля issues_json (сумісність із наявним UI)."""
    where = ' / '.join(x for x in (row.get('language'), row.get('variant'),
                                    f'блок {row["block"] + 1}' if isinstance(row.get('block'), int) else '') if x)
    head = f'[{row.get("severity")}]' + (f' [{where}]' if where else '')
    text = f'{head} {row.get("message")}'
    if row.get('evidence'):
        text += f' - «{row["evidence"][:80]}»'
    return text


_PENALTY = {'critical': 25, 'warning': 7, 'info': 2}


def report_from_findings(findings: list[dict], clean_summary: str = 'Зауважень немає') -> tuple:
    """(score, summary, issues[str], suggestions[str]). Оцінка похідна від findings."""
    score = 100.0
    for row in findings:
        score -= _PENALTY.get(row.get('severity'), 5)
    score = max(0.0, min(100.0, score))
    ordered = sorted(findings, key=lambda r: SEVERITIES.index(r.get('severity', 'info')))
    issues = [finding_to_text(r) for r in ordered]
    suggestions = list(dict.fromkeys(r.get('suggestion') for r in ordered if r.get('suggestion')))[:8]
    summary = clean_summary if not ordered else '; '.join(r.get('message', '') for r in ordered[:3])[:300]
    return score, summary, issues, suggestions


def validate_decision(row: dict | None, state: str, comment: str) -> str:
    """Правила стану знахідки. Повертає повідомлення про помилку або ''.

    * critical не можна «прийняти» - його треба виправити;
    * warning/info можна прийняти лише з коментарем;
    * resolved - позначка рецензента, що проблему усунено (або її вже немає).
    """
    if state not in FINDING_STATES:
        return 'Стан знахідки: open, resolved або accepted'
    severity = (row or {}).get('severity', 'warning')
    if state == 'accepted':
        if severity == 'critical':
            return 'Критичну знахідку не можна прийняти - її потрібно виправити'
        if not (comment or '').strip():
            return 'Щоб прийняти зауваження, потрібен коментар: чому це не проблема'
    return ''


def approval_blockers(reports: list[dict], artifacts: list, decisions: dict | None = None) -> list[str]:
    """Що заважає схвалити проєкт. Порожній список = можна.

    Блокують: критичні знахідки детермінованих перевірок (непідтверджена
    характеристика, розбіжність чисел, не той товар, змішання мов, зламаний
    HTML, відсутній alt, критичний дефект верстки) і аварійний шаблон замість
    стилю. SEO/GEO-попередження НЕ блокують: рецензент приймає їх з коментарем.
    """
    decisions = decisions or {}
    reasons = []
    for artifact in artifacts or []:
        if getattr(artifact, 'fallback_reason', '') or (isinstance(artifact, dict) and artifact.get('fallback_reason')):
            language = getattr(artifact, 'language', None) or (artifact.get('language') if isinstance(artifact, dict) else '')
            variant = getattr(artifact, 'variant', None) or (artifact.get('variant') if isinstance(artifact, dict) else '')
            reasons.append(f'{language}/{variant}: аварійний шаблон замість обраного стилю - перегенеруйте')
    for report in reports or []:
        if report.get('type') == 'llm':
            continue  # AI-рецензія - порада, не ворота
        for row in report.get('findings') or []:
            if row.get('severity') != 'critical':
                continue
            state = (decisions.get(row.get('key')) or {}).get('state')
            if state == 'resolved':
                continue
            reasons.append(f'{report.get("type")}: {finding_to_text(row)}')
    return reasons


# ---------------------------------------------------------------------------
# Розбір тексту фрагмента
# ---------------------------------------------------------------------------

_SKIP_TAGS = {'style', 'script', 'noscript', 'template', 'iframe', 'svg'}
_HEADINGS = ('h1', 'h2', 'h3', 'h4')
_SENTENCE_SPLIT = re.compile(r'(?<=[.!?…])\s+(?=[^\s])')
_WORD_RE = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", re.U)
_CYR_RE = re.compile(r'[А-Яа-яЁёІіЇїЄєҐґ]')
_LAT_RE = re.compile(r'[A-Za-zĄąĆćĘęŁłŃńÓóŚśŹźŻż]')
_RU_ONLY_RE = re.compile(r'[ыэъёЫЭЪЁ]')
_UK_ONLY_RE = re.compile(r'[іїєґІЇЄҐ]')
_PL_DIACRITIC_RE = re.compile(r'[ĄąĆćĘęŁłŃńÓóŚśŹźŻż]')


def _clean_text(value: str) -> str:
    return ' '.join(html_lib.unescape(str(value or '')).split())


def sentences(text: str) -> list[str]:
    text = _clean_text(text)
    if not text:
        return []
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def words(text: str) -> list[str]:
    return _WORD_RE.findall(text or '')


def _norm_sentence(text: str) -> str:
    return re.sub(r'[^\w\s]', '', _clean_text(text).lower())


def _hidden_style(style: str) -> str:
    """Чому елемент невидимий (порожньо = видимий)."""
    css = (style or '').lower().replace(' ', '')
    checks = (
        ('display:none', 'display:none'), ('visibility:hidden', 'visibility:hidden'),
        ('font-size:0', 'font-size:0'), ('text-indent:-', 'text-indent за екран'),
        ('left:-9', 'позиція за екраном'), ('clip:rect(0', 'clip:rect(0)'),
        ('height:0;overflow:hidden', 'height:0 + overflow:hidden'),
    )
    for token, why in checks:
        if token in css:
            return why
    if re.search(r'(^|;)opacity:0(;|$)', css):
        return 'opacity:0'
    return ''


def _elements(node) -> list:
    return [c for c in node.children if getattr(c, 'name', None)]


def _blocks_of(root) -> list:
    """Візуальні блоки: діти кореня, або діти єдиної зайвої обгортки."""
    blocks = _elements(root)
    while len(blocks) == 1 and len(_elements(blocks[0])) >= 2:
        blocks = _elements(blocks[0])
    return blocks or [root]


def parse_fragment(markup: str) -> dict:
    """Структурне представлення rich-фрагмента для всіх аудитів.

    Ключі сегментів (t0.., a0..) збігаються з ``text_edit.editable_segments`` -
    тому знахідка може вести до конкретного текстового поля редактора: обидві
    сторони нумерують видимі текстові вузли того самого HTML в тому самому порядку.
    """
    soup = BeautifulSoup(markup or '', 'html.parser')
    root = soup.find('section') or soup
    blocks = _blocks_of(root)
    owner = {id(b): i for i, b in enumerate(blocks)}

    def block_of(node):
        for parent in node.parents:
            if id(parent) in owner:
                return owner[id(parent)]
        return 0

    def hidden(node) -> bool:
        for parent in node.parents:
            name = getattr(parent, 'name', None)
            if name in _SKIP_TAGS:
                return True
            if getattr(parent, 'get', None) and parent.get('aria-hidden') == 'true':
                return True
        return False

    texts, images = [], []
    seen = set()
    # Ті самі правила контейнера, що в text_edit: абзац із лише <b> усередині - одне поле.
    containers = {'p', 'li', 'h2', 'h3', 'h4', 'summary', 'dt', 'dd', 'td', 'th', 'figcaption'}
    bold = {'b', 'strong'}

    def container(node):
        for parent in node.parents:
            name = getattr(parent, 'name', None)
            if name in containers:
                tags = parent.find_all(True)
                if all(t.name in bold and not t.find(True) for t in tags):
                    return parent
                return None
            if name in ('section', None) or name not in bold:
                return None
        return None

    index = 0
    for node in root.find_all(string=True):
        if isinstance(node, Comment) or hidden(node):
            continue
        if not re.search(r'\w', str(node)):
            continue
        unit = container(node) or node
        if id(unit) in seen:
            continue
        seen.add(id(unit))
        text = _clean_text(unit.get_text(' ') if not isinstance(unit, NavigableString) else str(unit))
        tag = None
        for parent in (unit.parents if isinstance(unit, NavigableString) else [unit] + list(unit.parents)):
            name = getattr(parent, 'name', None)
            if name in ('p', 'li', 'h2', 'h3', 'h4', 'summary', 'span', 'div', 'dt', 'dd', 'td', 'th', 'figcaption', 'h1'):
                tag = name
                break
        style = ''
        for parent in (unit.parents if isinstance(unit, NavigableString) else [unit] + list(unit.parents)):
            if getattr(parent, 'get', None) and parent.get('style'):
                why = _hidden_style(parent.get('style'))
                if why:
                    style = why
                    break
            if getattr(parent, 'name', None) == 'section':
                break
        texts.append({'key': f't{index}', 'tag': tag or 'text', 'text': text, 'block': block_of(node), 'hidden': style})
        index += 1
    for i, img in enumerate(root.find_all('img')):
        if hidden(img):
            continue
        images.append({'key': f'a{i}', 'alt': img.get('alt'), 'src': img.get('src') or '', 'loading': img.get('loading') or '',
                       'block': block_of(img)})
    headings = [t for t in texts if t['tag'] in _HEADINGS]
    paragraphs = [t for t in texts if t['tag'] in ('p', 'li', 'dd', 'td', 'figcaption')]
    return {
        'soup': soup, 'root': root, 'blocks': blocks, 'texts': texts, 'images': images,
        'headings': headings, 'paragraphs': paragraphs,
        'visible_text': ' '.join(t['text'] for t in texts),
        'block_count': len(blocks),
    }


# ---------------------------------------------------------------------------
# Словники за мовами
# ---------------------------------------------------------------------------

GENERIC_PHRASES = {
    'uk': ['інноваційне рішення', 'новий рівень', 'безмежні можливості', 'ідеальний вибір', 'максимальний комфорт',
           'поєднує стиль і продуктивність', 'відкриває нові горизонти', 'для тих, хто цінує якість',
           'неперевершен', 'унікальн', 'найкращий вибір', 'преміальна якість', 'ідеально підходить для будь-яких',
           'справжній прорив', 'на всі випадки життя'],
    'ru': ['инновационное решение', 'новый уровень', 'безграничные возможности', 'идеальный выбор', 'максимальный комфорт',
           'сочетает стиль и производительность', 'открывает новые горизонты', 'для тех, кто ценит качество',
           'непревзойден', 'уникальн', 'лучший выбор', 'премиальное качество'],
    'pl': ['innowacyjne rozwiązanie', 'nowy poziom', 'nieograniczone możliwości', 'idealny wybór', 'maksymalny komfort',
           'łączy styl i wydajność', 'otwiera nowe horyzonty', 'dla tych, którzy cenią jakość', 'niezrównan',
           'unikaln', 'najlepszy wybór', 'najwyższa jakość', 'idealnie sprawdzi się w każdej'],
    'en': ['innovative solution', 'new level', 'limitless possibilities', 'ideal choice', 'maximum comfort',
           'combines style and performance', 'opens new horizons', 'for those who value quality', 'unparalleled',
           'unique', 'best choice', 'premium quality', 'take your', 'to the next level', 'game-changer', 'cutting-edge',
           'state-of-the-art', 'seamless', 'elevate your', 'unleash'],
}

# Канцеляризми та дослівні кальки (ознака машинного перекладу).
CALQUES = {
    'uk': ['приймати участь', 'на протязі', 'у відповідності з', 'в даний час', 'являється', 'на рахунок',
           'з метою забезпечення', 'задача полягає', 'дозволяє забезпечити', 'здійснювати роботу', 'проводити роботу',
           'при допомозі', 'у більшості випадків', 'являє собою', 'наступним чином', 'носить характер',
           'співпадає', 'в залежності від', 'у кінцевому підсумку', 'відноситься до', 'з точки зору', 'на сьогоднішній день'],
    'ru': ['осуществлять работу', 'в целях обеспечения', 'является', 'в настоящее время', 'на сегодняшний день',
           'в большинстве случаев', 'представляет собой', 'носит характер', 'в конечном итоге'],
    'pl': ['na dzień dzisiejszy', 'w chwili obecnej', 'w celu zapewnienia', 'stanowi rozwiązanie', 'pozwala na zapewnienie',
           'realizować pracę', 'jest to możliwe dzięki', 'dedykowany dla', 'w oparciu o', 'posiada możliwość',
           'daje możliwość', 'w każdym przypadku użycia'],
    'en': ['it allows to', 'allows to', 'makes it possible to', 'in order to ensure', 'is characterized by', 'gives the possibility',
           'at the present time', 'has the possibility', 'is intended for', 'in the majority of cases', 'permits to',
           'helps to provide', 'according to the', 'the given', 'this device is', 'thanks to what'],
}

SUPERLATIVES = {
    'uk': r'\b(найкращ\w*|найпотужніш\w*|найшвидш\w*|найнадійніш\w*|найтихіш\w*|номер один|№\s?1|лідер ринку|неперевершен\w*)\b',
    'ru': r'\b(лучш\w*|самый мощн\w*|самый быстр\w*|самый надежн\w*|номер один|№\s?1|лидер рынка)\b',
    'pl': r'\b(najlepsz\w*|najmocniejsz\w*|najszybsz\w*|najbardziej niezawodn\w*|numer jeden|nr\s?1|lider rynku)\b',
    'en': r'\b(the best|most powerful|fastest|most reliable|number one|#1|market leader|world[- ]class|unbeatable)\b',
}

COMPARISONS = {
    'uk': r'(кращ\w* за|кращ\w* ніж|швидш\w* за|у \d+ раз\w* швидш|перевершує|випереджає конкурент)',
    'ru': r'(лучше чем|лучше, чем|быстрее чем|в \d+ раз\w* быстрее|превосходит|опережает конкурент)',
    'pl': r'(lepsz\w* niż|szybsz\w* niż|\d+ razy szybsz|przewyższa|wyprzedza konkurenc)',
    'en': r'(better than|faster than|\d+x faster|\d+ times faster|outperforms|beats the competition|leaves competitors)',
}

PAGE_NARRATION = {
    'uk': r'(на фото|на зображенні|на картинці|на ілюстрації|в цьому блоці|у цьому розділі|нижче ви|нижче наведено|як показано|цей блок)',
    'ru': r'(на фото|на изображении|на картинке|в этом блоке|в этом разделе|ниже вы|ниже приведен|как показано|этот блок)',
    'pl': r'(na zdjęciu|na obrazku|na ilustracji|w tej sekcji|w tym bloku|poniżej znajd|jak pokazano|ten blok)',
    'en': r'(in the photo|the image shows|pictured|in this section|in this block|below you will find|as shown|this block)',
}

SCENE_SETTING = {
    'uk': r'^(уявіть|сьогодні|у сучасному світі|в сучасному світі|в епоху|коли мова йде|коли йдеться|чи знаєте ви|ви коли-небудь)',
    'ru': r'^(представьте|сегодня|в современном мире|в эпоху|когда речь идет|знаете ли вы|вы когда-нибудь)',
    'pl': r'^(wyobraź sobie|w dzisiejszych czasach|we współczesnym świecie|w erze|kiedy mowa o|czy wiesz|czy kiedykolwiek)',
    'en': r'^(imagine|today|in today\'s world|in the modern world|in the era|when it comes to|did you know|have you ever)',
}

URGENCY = {
    'uk': r'(поспішайте|тільки сьогодні|встигніть|не проґавте|обмежена пропозиція|лише зараз)',
    'ru': r'(спешите|только сегодня|успейте|не упустите|ограниченное предложение|только сейчас)',
    'pl': r'(pospiesz się|tylko dziś|nie przegap|oferta ograniczona|tylko teraz)',
    'en': r'(hurry|only today|don\'t miss|limited offer|act now|while supplies last)',
}

# Комерційні твердження, що потребують джерела у VERIFIED COMPANY FACTS.
COMMERCIAL_CLAIMS = [
    ('support_24_7', r'24\s?/\s?7|24×7|цілодобов\w*|круглосуточн\w*|całodobow\w*|around[- ]the[- ]clock', 'critical'),
    ('warranty', r'гаранті\w+|гаранти\w+|gwarancj\w+|warrant(y|ies)', 'critical'),
    ('delivery', r'доставк\w*|доставля\w*|постача\w*|dostaw\w*|dostarcz\w*|deliver\w*|shipping', 'warning'),
    ('support', r'технічн\w+ підтримк\w*|техпідтримк\w*|служб\w+ підтримки|техническ\w+ поддержк\w*|wsparci\w+ techniczn\w*|technical support|customer support', 'critical'),
    ('sla', r'\bSLA\b|рівень обслуговування|uptime', 'critical'),
    ('stock', r'в наявності|є в наявності|на складі|в наличии|на складе|na stanie|w magazynie|in stock|available now', 'critical'),
    ('installation', r'монтаж\w*|встановленн\w* безкоштовн\w*|монтаж\w* безкоштовн\w*|instalacj\w* gratis|free installation|montaż', 'warning'),
    ('free_delivery', r'безкоштовн\w+ доставк\w*|бесплатн\w+ доставк\w*|darmow\w+ dostaw\w*|free (shipping|delivery)', 'critical'),
    ('delivery_time', r'доставк\w* (за|протягом|від) \d|\d+ (дн\w+|годин\w*) доставк|dostawa w \d|w ciągu \d+ dni|delivery (in|within) \d|\d+[- ]day delivery', 'critical'),
]

# Одиниці, з якими число вважається ЗНАЧЕННЯМ характеристики й потребує provenance.
_UNIT_RE = (r'(?:мм|см|м|кг|г|Вт|W|кВт|kW|В|V|А|A|мА·?г|mAh|ГБ|GB|ТБ|TB|МБ|MB|ГГц|GHz|МГц|MHz|Гц|Hz|дюйм\w*|"|″|л|l|мл|ml|'
            r'dpi|ppi|нм|nm|мс|ms|год|h|°C|°|лм|lm|дБ|dB|Мбіт/с|Mbps|Гбіт/с|Gbps|px|Мп|MP|Mpx|fps|Nm|Н·м|об/хв|rpm|'
            r'мм/с|mm/s|бар|bar|PSI|psi|Ач|Ah|кВт·год|kWh|Вт·год|Wh|мкм|µm|mm|cm|kg|g|Гц)')
_VALUE_RE = re.compile(r'(?<![\w.,])(\d{1,3}(?:[  ]\d{3})+|\d+(?:[.,]\d+)?)\s?(' + _UNIT_RE + r')(?![\w])', re.U)
_NUMBER_RE = re.compile(r'(?<![\w.,-])(\d+(?:[.,]\d+)?)(?![\w.,-])')


def _norm_number(value: str) -> str:
    value = value.replace(' ', '').replace(' ', '').replace(',', '.')
    if re.fullmatch(r'\d+\.0+', value):
        value = value.split('.')[0]
    return value


def fact_numbers(product: dict | None, evidence: list | None = None, extra_texts: list | None = None) -> set:
    """Усі числа, які підтверджені даними товару (Product JSON + evidence)."""
    pool = []

    def walk(value):
        if isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
        elif value is not None:
            pool.append(str(value))

    walk(product or {})
    walk(evidence or [])
    for text in extra_texts or []:
        pool.append(str(text))
    numbers = set()
    for text in pool:
        for match in re.findall(r'\d{1,3}(?:[  ]\d{3})+|\d+(?:[.,]\d+)?', text):
            numbers.add(_norm_number(match))
    return numbers


def _phrase_count(text: str, phrase: str) -> int:
    phrase = _clean_text(phrase).lower()
    if not phrase:
        return 0
    return len(re.findall(re.escape(phrase), text.lower()))


def _entities(product: dict | None, brief: dict | None) -> list[str]:
    out = []
    for value in ((product or {}).get('brand'), (product or {}).get('name'), (product or {}).get('sku')):
        if value:
            out.append(str(value))
    for value in (brief or {}).get('entities') or []:
        if value:
            out.append(str(value))
    return out


def _entity_tokens(product: dict | None, brief: dict | None) -> set:
    """Слова офіційних назв: їх наявність не вважається змішанням мов."""
    tokens = set()
    for entity in _entities(product, brief):
        for word in re.findall(r'[\w\-]+', str(entity)):
            tokens.add(word.lower())
    for spec in (product or {}).get('specs') or []:
        if isinstance(spec, dict):
            for word in re.findall(r'[A-Za-z][\w\-]+', str(spec.get('value') or '')):
                tokens.add(word.lower())
    for text in ((product or {}).get('features') or []):
        for word in re.findall(r'[A-Z][\w\-]+', str(text)):
            tokens.add(word.lower())
    return tokens


def model_token(product: dict | None) -> str:
    """Код моделі, за яким шукає покупець (з назви товару)."""
    name = str((product or {}).get('name') or '').strip()
    tokens = [t for t in re.split(r'[\s,()]+', name) if re.search(r'\d', t) and len(t) >= 4]
    return max(tokens, key=len) if tokens else ''


# ---------------------------------------------------------------------------
# Аудит: людський текст
# ---------------------------------------------------------------------------

def audit_human_copy(markup: str, language: str, variant: str = '', brief: dict | None = None,
                     product: dict | None = None) -> list[dict]:
    """Детермінована перевірка «чи звучить це як текст людини». М'які пороги, evidence."""
    lang = norm_lang(language)
    doc = parse_fragment(markup)
    findings: list[dict] = []
    src = 'human'
    mk = lambda *a, **k: findings.append(finding(*a, language=lang, variant=variant, source=src, **k))  # noqa: E731

    all_sentences = []
    for item in doc['texts']:
        for s in sentences(item['text']):
            all_sentences.append((s, item))
    text_lower = doc['visible_text'].lower()
    total_words = max(1, len(words(doc['visible_text'])))

    # 1. Повтор однакових речень
    # Речення - це щонайменше 4 змістовні слова. Лейбл «QUBE · G25F240S» (бренд і код)
    # стиль свідомо повторює в Hero і фіналі - це не повтор тексту.
    meaningful = lambda s: len(words(s)) >= 4 and len([w for w in words(s) if len(w) > 2 and not w.isupper()]) >= 2  # noqa: E731
    counts = Counter(_norm_sentence(s) for s, _ in all_sentences if meaningful(s))
    for norm, count in counts.items():
        if count > 1:
            first = next((s, i) for s, i in all_sentences if _norm_sentence(s) == norm)
            mk('duplicate_sentence', 'warning', f'Речення повторено {count} рази', block=first[1]['block'],
               evidence=first[0], segment=first[1]['key'],
               suggestion='Залишити речення в одному блоці, в інших дати новий факт або прибрати повтор')

    # 2. Однаковий початок абзаців
    openings = Counter(' '.join(words(p['text'])[:3]).lower() for p in doc['paragraphs'] if len(words(p['text'])) >= 5)
    for opening, count in openings.items():
        if count >= 3 and opening:
            item = next(p for p in doc['paragraphs'] if ' '.join(words(p['text'])[:3]).lower() == opening)
            mk('repeated_paragraph_opening', 'warning', f'{count} абзаци починаються однаково', block=item['block'],
               evidence=item['text'], segment=item['key'], suggestion='Змінити початок абзаців: одна думка - одна конструкція')

    # 3. Бренд/модель у більшості заголовків
    brand = str((product or {}).get('brand') or '').strip().lower()
    model = model_token(product).lower()
    headings = [h for h in doc['headings'] if h['tag'] in ('h2', 'h3')]
    if len(headings) >= 3 and (brand or model):
        hits = [h for h in headings if (brand and brand in h['text'].lower()) or (model and model in h['text'].lower())]
        if len(hits) * 2 > len(headings):
            mk('brand_in_most_headings', 'warning', f'Бренд або модель у {len(hits)} з {len(headings)} заголовків',
               block=hits[0]['block'], evidence=hits[0]['text'], segment=hits[0]['key'],
               suggestion='Залишити точну назву в Hero та підсумку, в інших заголовках назвати користь або сценарій')

    # 4. Довгі речення (м'який поріг: не кожне довге речення - помилка)
    long = [(s, i) for s, i in all_sentences if len(words(s)) > 32]
    if long:
        s, i = max(long, key=lambda x: len(words(x[0])))
        mk('long_sentence', 'warning' if len(long) >= 3 else 'info',
           f'Задовгих речень: {len(long)} (понад 32 слова)', block=i['block'], evidence=s, segment=i['key'],
           suggestion='Розбити на два речення: одна корисна думка в кожному')

    # 5. Абзаци довші за 4 речення
    for p in doc['paragraphs']:
        if len(sentences(p['text'])) > 4:
            mk('long_paragraph', 'info', f'Абзац із {len(sentences(p["text"]))} речень', block=p['block'],
               evidence=p['text'], segment=p['key'], suggestion='Тримати абзац у межах 2-4 речень')

    # 6. Канцеляризми та кальки
    for phrase in CALQUES.get(lang, []):
        if phrase in text_lower:
            item = next((i for i in doc['texts'] if phrase in i['text'].lower()), None)
            mk('calque', 'warning', f'Канцеляризм або дослівна калька: «{phrase}»', block=item['block'] if item else None,
               evidence=item['text'] if item else phrase, segment=item['key'] if item else '',
               suggestion='Переписати природною мовою: коротше дієслово замість конструкції')

    # 7. Generic AI phrases
    for phrase in GENERIC_PHRASES.get(lang, []):
        if phrase in text_lower:
            item = next((i for i in doc['texts'] if phrase in i['text'].lower()), None)
            mk('generic_phrase', 'warning', f'Порожня фраза-шаблон: «{phrase}»', block=item['block'] if item else None,
               evidence=item['text'] if item else phrase, segment=item['key'] if item else '',
               suggestion='Замінити конкретним фактом товару або прибрати речення')

    # 8. Суперлативи
    pattern = SUPERLATIVES.get(lang)
    if pattern:
        hits = re.findall(pattern, text_lower, flags=re.I)
        if len(hits) > 2:
            item = next((i for i in doc['texts'] if re.search(pattern, i['text'], re.I)), None)
            mk('superlatives', 'warning', f'Надмірні суперлативи: {len(hits)}', block=item['block'] if item else None,
               evidence=item['text'] if item else '', segment=item['key'] if item else '',
               suggestion='Залишити лише те, що можна довести числом; решту сформулювати нейтрально')

    # 9. Знаки оклику
    exclamations = doc['visible_text'].count('!')
    if exclamations > 1:
        item = next((i for i in doc['texts'] if '!' in i['text']), None)
        mk('exclamations', 'info' if exclamations <= 3 else 'warning', f'Знаків оклику: {exclamations}',
           block=item['block'] if item else None, evidence=item['text'] if item else '', segment=item['key'] if item else '',
           suggestion='Прибрати оклики: спокійний тон продавця, а не реклами')

    # 10. Серія однакових конструкцій (3+ поспіль речень з одного слова)
    run = 1
    for (a, _), (b, item) in zip(all_sentences, all_sentences[1:]):
        wa, wb = words(a)[:1], words(b)[:1]
        if wa and wb and wa[0].lower() == wb[0].lower() and len(wa[0]) > 2:
            run += 1
            if run == 3:
                mk('monotonous_construction', 'info', f'Три речення поспіль починаються зі слова «{wb[0]}»',
                   block=item['block'], evidence=b, segment=item['key'], suggestion='Урізноманітнити початок речень')
        else:
            run = 1

    # 11. Keyword stuffing (частота - діагностика, не ціль)
    targets = []
    if brief and brief.get('primary_topic'):
        targets.append(str(brief['primary_topic']))
    if (product or {}).get('name'):
        targets.append(str(product['name']))
    for target in targets:
        count = _phrase_count(doc['visible_text'], target)
        density = count * max(1, len(words(target))) / total_words
        if count >= 5 and density > 0.02:
            item = next((i for i in doc['texts'] if target.lower() in i['text'].lower()), None)
            mk('keyword_repetition', 'warning', f'Фраза повторена {count} разів', block=item['block'] if item else None,
               evidence=target, segment=item['key'] if item else '',
               suggestion='Залишити точну назву в Hero та підсумку, в інших блоках використати природні займенники або категорію')

    # 12. Обривочні заголовки
    for h in headings:
        w = words(h['text'])
        if not w or (len(w) == 1 and len(w[0]) < 4) or h['text'].strip().endswith((':', ',', '-', '–')):
            mk('weak_heading', 'info', 'Заголовок без самостійного змісту', block=h['block'], evidence=h['text'],
               segment=h['key'], suggestion='Заголовок має називати користь або сценарій, а не бути обривком')

    # 13. Текст про сторінку або зображення
    pattern = PAGE_NARRATION.get(lang)
    if pattern:
        for item in doc['texts']:
            if re.search(pattern, item['text'], re.I):
                mk('page_narration', 'warning', 'Текст описує сторінку або зображення, а не товар', block=item['block'],
                   evidence=item['text'], segment=item['key'], suggestion='Писати про товар: текст має бути зрозумілим без картинок')
                break

    # 14. Штучна терміновість
    pattern = URGENCY.get(lang)
    if pattern:
        item = next((i for i in doc['texts'] if re.search(pattern, i['text'], re.I)), None)
        if item:
            mk('artificial_urgency', 'warning', 'Штучна терміновість', block=item['block'], evidence=item['text'],
               segment=item['key'], suggestion='Прибрати заклики поспішати')

    # 15. Неприродна форма ключового запиту: точна фраза у називному відмінку 3+ разів
    #     у різних блоках без жодної відмінюваної форми.
    if brief and brief.get('primary_topic'):
        topic = str(brief['primary_topic']).strip()
        exact = _phrase_count(doc['visible_text'], topic)
        stem_words = [w[:max(4, len(w) - 2)].lower() for w in words(topic) if len(w) > 4]
        inflected = 0
        if stem_words:
            inflected = sum(1 for s, _ in all_sentences
                            if all(sw in s.lower() for sw in stem_words) and topic.lower() not in s.lower())
        if exact >= 3 and inflected == 0 and len(words(topic)) >= 2:
            item = next((i for i in doc['texts'] if topic.lower() in i['text'].lower()), None)
            mk('unnatural_keyword_form', 'warning', 'Ключовий запит вжито лише в точній формі',
               block=item['block'] if item else None, evidence=topic, segment=item['key'] if item else '',
               suggestion='Відмінювати запит за граматикою мови, а не вставляти exact-match')
    return findings


# ---------------------------------------------------------------------------
# Аудит: якість мови (чистота, змішання, кирилиця у латинських версіях)
# ---------------------------------------------------------------------------

def audit_language_quality(markup: str, language: str, variant: str = '', product: dict | None = None,
                           brief: dict | None = None) -> list[dict]:
    lang = norm_lang(language)
    doc = parse_fragment(markup)
    findings: list[dict] = []
    allowed = _entity_tokens(product, brief)
    all_words = []
    for item in doc['texts']:
        for w in words(item['text']):
            all_words.append((w, item))
    total = max(1, len(all_words))

    def flag_words(predicate, code, message, suggestion):
        bad = [(w, i) for w, i in all_words if predicate(w) and w.lower() not in allowed and len(w) > 1]
        if not bad:
            return
        ratio = len(bad) / total
        severity = 'critical' if (len(bad) > 5 or ratio > 0.02) else 'warning'
        sample = ', '.join(dict.fromkeys(w for w, _ in bad[:6]))
        findings.append(finding(code, severity, f'{message}: {len(bad)} слів', language=lang, variant=variant,
                                block=bad[0][1]['block'], evidence=bad[0][1]['text'] + f' [{sample}]', segment=bad[0][1]['key'],
                                suggestion=suggestion, source='language'))

    if lang in ('pl', 'en'):
        flag_words(lambda w: bool(_CYR_RE.search(w)), 'cyrillic_in_latin_page',
                   'Кирилиця у версії латинкою', 'Перекласти слово; офіційні назви лишити як у виробника')
    if lang == 'uk':
        flag_words(lambda w: bool(_RU_ONLY_RE.search(w)), 'russian_letters_in_ukrainian',
                   'Російські літери в українському тексті', 'Переписати українською')
    if lang == 'ru':
        flag_words(lambda w: bool(_UK_ONLY_RE.search(w)), 'ukrainian_letters_in_russian',
                   'Українські літери в російському тексті', 'Переписати російською')
    if lang in ('uk', 'ru'):
        # Латинські слова поза назвами/одиницями - ознака мішанини або необробленої кальки.
        latin = [(w, i) for w, i in all_words if _LAT_RE.fullmatch(w[:1]) and len(w) >= 5
                 and w.lower() not in allowed and not w.isupper()]
        if len(latin) > 8 and len(latin) / total > 0.05:
            findings.append(finding('latin_words_in_cyrillic_page', 'warning', f'Латинських слів поза назвами: {len(latin)}',
                                    language=lang, variant=variant, block=latin[0][1]['block'], evidence=latin[0][1]['text'],
                                    segment=latin[0][1]['key'], suggestion='Перекласти загальні слова, лишити лише бренди, моделі, технології',
                                    source='language'))
    if lang == 'en':
        polish = [(w, i) for w, i in all_words if _PL_DIACRITIC_RE.search(w) and w.lower() not in allowed]
        if polish:
            findings.append(finding('mixed_language', 'warning', f'Слова з польськими діакритиками в англійському тексті: {len(polish)}',
                                    language=lang, variant=variant, block=polish[0][1]['block'], evidence=polish[0][1]['text'],
                                    segment=polish[0][1]['key'], suggestion='Перекласти англійською', source='language'))
    if lang == 'pl':
        # Польський текст без жодного діакритика на 80+ слів - майже напевно не польський.
        if total > 80 and not any(_PL_DIACRITIC_RE.search(w) for w, _ in all_words):
            item = doc['texts'][0] if doc['texts'] else None
            findings.append(finding('language_mismatch', 'critical', 'Текст не схожий на польський: жодного діакритика',
                                    language=lang, variant=variant, block=item['block'] if item else None,
                                    evidence=item['text'] if item else '', segment=item['key'] if item else '',
                                    suggestion='Перекласти сторінку польською', source='language'))
    # Дослівний машинний переклад - через кальки цієї мови (спільний словник із human copy).
    text_lower = doc['visible_text'].lower()
    hits = [p for p in CALQUES.get(lang, []) if p in text_lower]
    if hits:
        item = next((i for i in doc['texts'] if hits[0] in i['text'].lower()), None)
        findings.append(finding('literal_translation', 'warning', f'Ознаки дослівного перекладу: «{hits[0]}»' + (f' та ще {len(hits) - 1}' if len(hits) > 1 else ''),
                                language=lang, variant=variant, block=item['block'] if item else None,
                                evidence=item['text'] if item else hits[0], segment=item['key'] if item else '',
                                suggestion='Переписати так, як сказав би носій мови, а не як перекладач', source='language'))
    # Delivery statement має бути точним, якщо вжитий.
    statements = DELIVERY_STATEMENTS
    for code, statement in statements.items():
        if code != lang and statement.lower() in text_lower:
            item = next((i for i in doc['texts'] if statement.lower() in i['text'].lower()), None)
            findings.append(finding('delivery_statement_wrong_language', 'critical', 'Формулювання доставки іншою мовою',
                                    language=lang, variant=variant, block=item['block'] if item else None,
                                    evidence=item['text'] if item else statement, segment=item['key'] if item else '',
                                    suggestion=f'Використати: «{statements.get(lang, statements["uk"])}»', source='language'))
    return findings


# ---------------------------------------------------------------------------
# Аудит: SEO rich-фрагмента
# ---------------------------------------------------------------------------

_GENERIC_ALT = re.compile(r'^(image|photo|picture|img|фото|зображення|картинка|изображение|zdjęcie|obraz|obrazek|grafika)\s*\d*$', re.I)
_FILENAME_ALT = re.compile(r'\.(jpe?g|png|webp|gif|svg)$|^(img|dsc|image)[_\-\d]+$', re.I)


def audit_rich_fragment(markup: str, product: dict | None, language: str, variant: str = '',
                        brief: dict | None = None) -> list[dict]:
    """SEO-правила саме для embedded-фрагмента. Document-level SEO тут заборонене."""
    lang = norm_lang(language)
    doc = parse_fragment(markup)
    soup = doc['soup']
    findings: list[dict] = []
    src = 'seo'
    mk = lambda *a, **k: findings.append(finding(*a, language=lang, variant=variant, source=src, **k))  # noqa: E731

    # Document-level елементи у фрагменті
    if soup.find('h1'):
        h1 = soup.find('h1')
        mk('h1_in_fragment', 'critical', 'H1 усередині rich-фрагмента', block=0, evidence=_clean_text(h1.get_text(' ')),
           suggestion='Картка товару вже має H1: замінити на h2')
    for tag_name, attrs, label in (('title', {}, '<title>'), ('meta', {}, 'meta'), ('link', {'rel': 'canonical'}, 'canonical'),
                                   ('link', {'hreflang': True}, 'hreflang'), ('script', {'type': 'application/ld+json'}, 'JSON-LD'),
                                   ('script', {}, 'script'), ('base', {}, '<base>')):
        node = soup.find(tag_name, attrs=attrs) if attrs else soup.find(tag_name)
        if node is not None:
            if tag_name == 'meta':
                names = ' '.join(filter(None, (node.get('name'), node.get('property'))))
                if not re.search(r'description|robots|og:|twitter:|keywords', names, re.I) and node.get('charset') is None:
                    continue
                label = f'meta {names or "charset"}'
            mk('document_seo_in_fragment', 'critical', f'{label} у фрагменті', block=0, evidence=str(node)[:120],
               suggestion='Метадані, canonical, hreflang і schema належать картці товару на artline.ua')

    # Заголовки
    h2s = [h for h in doc['headings'] if h['tag'] == 'h2']
    if not h2s:
        mk('no_h2', 'critical', 'Немає жодного змістовного h2', suggestion='Кожна секція починається з h2, що називає користь')
    for h in doc['headings']:
        if not words(h['text']):
            mk('empty_heading', 'warning', 'Порожній заголовок', block=h['block'], evidence=h['text'], segment=h['key'],
               suggestion='Заповнити або прибрати заголовок')
    for tag in soup.find_all(['h2', 'h3', 'h4']):
        if not _clean_text(tag.get_text(' ')):
            mk('empty_heading', 'warning', f'Порожній {tag.name}', suggestion='Заповнити або прибрати заголовок')
            break
    seen_h2 = False
    for h in doc['headings']:
        if h['tag'] == 'h2':
            seen_h2 = True
        elif h['tag'] == 'h3' and not seen_h2:
            mk('heading_order', 'warning', 'h3 стоїть перед першим h2', block=h['block'], evidence=h['text'], segment=h['key'],
               suggestion='Порядок h2 → h3: спершу заголовок секції')
            break

    # Бренд, модель, категорія в першому блоці; primary purpose у перших 150 словах
    first_words = ' '.join(words(doc['visible_text'])[:150]).lower()
    first_block_text = ' '.join(t['text'] for t in doc['texts'] if t['block'] == 0).lower()
    brand = str((product or {}).get('brand') or '').strip()
    model = model_token(product)
    category = str((product or {}).get('category') or '').strip()
    for label, value in (('бренд', brand), ('модель', model)):
        if value and value.lower() not in first_block_text:
            mk('identity_missing_early', 'warning', f'{label.capitalize()} «{value}» не названо в першому блоці', block=0,
               evidence=value, suggestion='Назвати бренд, модель і категорію в одному з перших речень')
    # Категорія й основна тема записані мовою брифу (українською). На сторінці іншою
    # мовою («Монітори» проти «Мониторы») дослівне порівняння дає хибні знахідки,
    # тому ці дві перевірки робляться лише мовою брифу.
    same_language = lang == norm_lang((brief or {}).get('language') or 'uk')
    if category and same_language:
        stems = [w[:max(4, len(w) - 2)].lower() for w in words(category) if len(w) > 3]
        if stems and not any(stem in first_words for stem in stems):
            mk('category_missing_early', 'warning', f'Категорію «{category}» не названо на початку', block=0, evidence=category,
               suggestion='Категорія товару має прозвучати в Hero або першому абзаці')
    topic = str((brief or {}).get('primary_topic') or '').strip()
    if topic and same_language:
        stems = [w[:max(4, len(w) - 2)].lower() for w in words(topic) if len(w) > 3]
        if stems and not all(stem in first_words for stem in stems):
            mk('primary_topic_late', 'warning', f'Основна тема «{topic}» не розкрита в перших 150 словах', block=0,
               evidence=topic, suggestion='Перше речення відповідає, що це і для чого')
        count = _phrase_count(doc['visible_text'], topic)
        total_words = max(1, len(words(doc['visible_text'])))
        if count >= 5 and count * len(words(topic)) / total_words > 0.015:
            mk('exact_match_repetition', 'warning', f'Точна фраза «{topic}» повторена {count} разів', evidence=topic,
               suggestion='Повторювати exact-match заради щільності не треба: використати синоніми й займенники')

    # Дублікати абзаців і повтор смислу між блоками
    paragraphs = [p for p in doc['paragraphs'] if len(words(p['text'])) >= 6]
    seen: dict = {}
    for p in paragraphs:
        key = _norm_sentence(p['text'])
        if key in seen:
            mk('duplicate_paragraph', 'warning', 'Абзац дублює попередній', block=p['block'], evidence=p['text'], segment=p['key'],
               suggestion='Кожен блок має нести новий зміст')
        seen[key] = p
    by_block: dict = {}
    for p in paragraphs:
        by_block.setdefault(p['block'], set()).update(_norm_sentence(s) for s in sentences(p['text']))
    ordered = sorted(by_block.items())
    for i, (block, sset) in enumerate(ordered):
        for prev_block, prev in ordered[:i]:
            if sset and prev and len(sset & prev) / len(sset) > 0.6:
                mk('block_without_new_meaning', 'warning', f'Блок {block + 1} повторює зміст блоку {prev_block + 1}', block=block,
                   evidence=next(iter(sset & prev)), suggestion='Дати блоку власний факт або прибрати його')
                break

    # Прихований текст
    for t in doc['texts']:
        if t['hidden'] and words(t['text']):
            mk('hidden_text', 'critical', f'Прихований текст ({t["hidden"]})', block=t['block'], evidence=t['text'], segment=t['key'],
               suggestion='Видалити: прихований текст - це маніпуляція, а не контент')
            break

    # Зображення: alt
    alts_seen: dict = {}
    for i, img in enumerate(doc['images']):
        alt = (img['alt'] or '').strip() if img['alt'] is not None else None
        if alt is None or not alt:
            mk('alt_missing', 'critical', 'Зображення без alt', block=img['block'], evidence=img['src'][-60:], segment=img['key'],
               suggestion='Описати, що на фото: товар і ракурс, мовою сторінки')
            continue
        if _GENERIC_ALT.match(alt) or _FILENAME_ALT.search(alt):
            mk('alt_generic', 'warning', f'Неінформативний alt «{alt}»', block=img['block'], evidence=alt, segment=img['key'],
               suggestion='Назвати товар і що показано: «ASUS ESC8000 - передня панель з 8 GPU»')
        elif alt.count(',') >= 3 and len(words(alt)) <= 12:
            mk('alt_keyword_list', 'warning', 'Alt схожий на перелік ключових слів', block=img['block'], evidence=alt, segment=img['key'],
               suggestion='Одне описове речення замість переліку')
        if lang in ('pl', 'en') and _CYR_RE.search(alt):
            mk('alt_language', 'warning', 'Alt іншою мовою', block=img['block'], evidence=alt, segment=img['key'],
               suggestion='Перекласти alt мовою сторінки')
        if alt.lower() in alts_seen:
            mk('alt_duplicate', 'warning', 'Однаковий alt у кількох зображень', block=img['block'], evidence=alt, segment=img['key'],
               suggestion='Кожен alt описує свій кадр')
        alts_seen[alt.lower()] = True
        if i == 0 and img['loading'] == 'lazy':
            mk('hero_lazy', 'info', 'Hero-зображення з loading="lazy"', block=img['block'], evidence=img['src'][-60:],
               suggestion='Перше зображення вантажити одразу')
        if i > 0 and img['loading'] != 'lazy':
            mk('missing_lazy', 'info', 'Зображення поза Hero без loading="lazy"', block=img['block'], evidence=img['src'][-60:],
               suggestion='Додати loading="lazy"')
    return findings


# ---------------------------------------------------------------------------
# Аудит: GEO (generative engine) rich-фрагмента
# ---------------------------------------------------------------------------

def audit_geo_copy(markup: str, product: dict | None, language: str, variant: str = '', brief: dict | None = None,
                   evidence: list | None = None, profile: dict | None = None) -> list[dict]:
    """Придатність для generative engines: сутність, answer-first, provenance значень,
    відсутність непідтверджених тверджень, самодостатній FAQ.

    llms.txt, robots і доступ AI-краулерів тут НЕ перевіряються - це властивості
    опублікованого домену, а не HTML-фрагмента."""
    lang = norm_lang(language)
    doc = parse_fragment(markup)
    findings: list[dict] = []
    src = 'geo'
    mk = lambda *a, **k: findings.append(finding(*a, language=lang, variant=variant, source=src, **k))  # noqa: E731
    product = product or {}
    evidence = evidence if evidence is not None else product.get('evidence') or []

    # 1. Сутність в одному ранньому реченні: бренд + модель + категорія
    brand = str(product.get('brand') or '').strip().lower()
    model = model_token(product).lower()
    category = str(product.get('category') or '').strip()
    cat_stems = [w[:max(4, len(w) - 2)].lower() for w in words(category) if len(w) > 3]
    early = [(s, t) for t in doc['texts'][:12] for s in sentences(t['text'])]
    if brand and model:
        entity_sentence = next((s for s, _ in early if brand in s.lower() and model in s.lower()), '')
        if not entity_sentence:
            mk('entity_not_linked_early', 'warning', 'Бренд і модель не зв\'язані в одному ранньому реченні', block=0,
               evidence=f'{product.get("brand")} {model_token(product)}',
               suggestion='Перше речення: «<Бренд> <Модель> - це <категорія> для <кого/чого>»')
        elif cat_stems and not any(stem in entity_sentence.lower() for stem in cat_stems) \
                and not any(stem in ' '.join(t['text'] for t in doc['texts'] if t['block'] == 0).lower() for stem in cat_stems):
            # Категорію в першому блоці вже несе лейбл («QUBE · МОНІТОР») - це не дефект.
            mk('entity_without_category', 'info', 'У реченні з брендом і моделлю не названо категорію', block=0,
               evidence=entity_sentence, suggestion='Додати категорію до речення-визначення')

    # 2. Answer-first: абзац не починається зі сцени чи риторичного питання
    pattern = SCENE_SETTING.get(lang)
    for p in doc['paragraphs']:
        first = sentences(p['text'])[:1]
        if not first:
            continue
        if (pattern and re.match(pattern, first[0].strip(), re.I)) or (first[0].strip().endswith('?') and p['tag'] == 'p'):
            mk('not_answer_first', 'warning', 'Абзац починається зі вступу або питання, а не з відповіді', block=p['block'],
               evidence=first[0], segment=p['key'], suggestion='Перше речення - висновок, далі - підтверджений факт')
            break

    # 3. Значення з одиницями мають provenance
    known = fact_numbers(product, evidence, company_facts(profile, lang))
    unsupported = []
    for t in doc['texts']:
        for match in _VALUE_RE.finditer(t['text']):
            number = _norm_number(match.group(1))
            if number not in known:
                unsupported.append((match.group(0), t))
    if unsupported:
        value, t = unsupported[0]
        mk('number_without_provenance', 'critical', f'Значень без джерела в даних товару: {len(unsupported)}', block=t['block'],
           evidence=f'{value} · {t["text"]}', segment=t['key'],
           suggestion='Кожне число має походити з Product JSON або evidence; прибрати або замінити підтвердженим')
    if not any(_VALUE_RE.search(t['text']) for t in doc['texts']) and (product.get('specs') or []):
        mk('no_concrete_values', 'warning', 'У тексті немає конкретних значень, хоча характеристики є', block=0,
           suggestion='Назвати 2-4 підтверджені значення з одиницями')

    # 4. Непідтверджені комерційні твердження
    facts = [f.lower() for f in company_facts(profile, lang)]
    profile = profile or {}
    allowed_groups = set()
    if (profile.get('verified_facts') or {}).get('delivery_regions'):
        allowed_groups.add('delivery')
    if company_facts({'warranty_text': profile.get('warranty_text')}, lang):
        allowed_groups.add('warranty')
    if company_facts({'service_text': profile.get('service_text')}, lang):
        allowed_groups.update({'support', 'support_24_7'})
    # Те, що є в характеристиках самого товару (гарантія виробника 36 міс.,
    # комплект поставки), - факт товару, а не обіцянка магазину: його підтверджує
    # Product JSON, а не Publishing Profile.
    product_text = json.dumps({k: product.get(k) for k in ('specs', 'features', 'description', 'external_facts')}, ensure_ascii=False).lower()
    for code, pattern, severity in COMMERCIAL_CLAIMS:
        if re.search(pattern, product_text, re.I):
            continue
        for t in doc['texts']:
            if not re.search(pattern, t['text'], re.I):
                continue
            low = t['text'].lower()
            if any(fact and fact in low for fact in facts):
                continue  # дослівне підтверджене твердження
            if code == 'delivery' and 'delivery' in allowed_groups:
                # Регіон з профілю можна згадувати; строки, «швидко» і «безкоштовно» - ні.
                if not re.search(r'швидк|быстр|szybk|fast|express|безкоштовн|бесплатн|darmow|free|\d', low):
                    continue
            if code in allowed_groups:
                continue
            mk('unsupported_commercial_claim', severity, f'Комерційне твердження без джерела ({code})', block=t['block'],
               evidence=t['text'], segment=t['key'],
               suggestion='Прибрати або взяти дослівно з VERIFIED COMPANY FACTS (Publishing Profile)')
            break

    # 5. Фальшиві порівняння і «найкращий» без comparison dataset
    for label, table, code in (('порівняння', COMPARISONS, 'unsupported_comparison'), ('суперлатив', SUPERLATIVES, 'unsupported_superlative')):
        pattern = table.get(lang)
        if not pattern:
            continue
        t = next((t for t in doc['texts'] if re.search(pattern, t['text'], re.I)), None)
        if t:
            mk(code, 'warning', f'Непідтверджене {label}', block=t['block'], evidence=t['text'], segment=t['key'],
               suggestion='Без датасету порівнянь - лише факти цього товару')

    # 6. FAQ: природні питання, самодостатні відповіді
    root = doc['root']
    for details in root.find_all('details'):
        summary = details.find('summary')
        question = _clean_text(summary.get_text(' ')) if summary else ''
        answer = _clean_text(' '.join(p.get_text(' ') for p in details.find_all(['p', 'li'])))
        qkey = next((t['key'] for t in doc['texts'] if t['text'] == question), '')
        if question and (not question.rstrip().endswith('?') or len(words(question)) < 3):
            mk('faq_question_unnatural', 'warning', 'Питання FAQ сформульовано неприродно', evidence=question, segment=qkey,
               suggestion='Питання так, як його ставить покупець, зі знаком питання')
        # Самодостатня відповідь - це конкретне значення або повне речення. Коротка
        # відповідь із числом («Яскравість 350 cd/m², контраст 1 000:1») - добра.
        has_value = bool(_VALUE_RE.search(answer) or re.search(r'\d', answer))
        if question and (len(words(answer)) < 4 or (len(words(answer)) < 8 and not has_value)):
            mk('faq_answer_thin', 'warning', 'Відповідь FAQ не самодостатня', evidence=f'{question} → {answer}', segment=qkey,
               suggestion='Відповідь має бути зрозумілою окремо від сторінки: сутність + значення')

    # 7. Той самий факт у 4+ блоках
    values_by_block: dict = {}
    for t in doc['texts']:
        if t['tag'] in ('span', 'text', 'label') and len(words(t['text'])) <= 4:
            continue  # чипи й лейбли - навігація по значеннях, а не повтор тексту
        for match in _VALUE_RE.finditer(t['text']):
            values_by_block.setdefault(_norm_number(match.group(1)) + match.group(2).lower(), set()).add(t['block'])
    for value, blocks in values_by_block.items():
        if len(blocks) >= max(4, (doc['block_count'] + 1) // 2 + 1):
            mk('fact_repeated_across_blocks', 'info', f'Значення {value} повторюється у {len(blocks)} блоках',
               evidence=value, suggestion='Залишити в Hero і там, де воно пояснює користь')
            break

    # 8. Доступність без JS і без зображень
    if root.find('script') or any(a.startswith('on') for tag in root.find_all(True) for a in tag.attrs):
        mk('js_required', 'critical', 'Фрагмент містить script або on*-обробники', suggestion='Контент має читатись без JavaScript')
    if len(words(doc['visible_text'])) < 80 and doc['images']:
        mk('image_only_content', 'warning', 'Майже весь зміст - у зображеннях', suggestion='Основні факти мають бути текстом')
    return findings


# ---------------------------------------------------------------------------
# Аудит: узгодженість desktop/mobile
# ---------------------------------------------------------------------------

def audit_variant_consistency(artifacts: list) -> list[dict]:
    """Десктоп і мобільна версія однієї мови мають нести той самий зміст.

    Різні цифри - попередження (одна з версій каже інше). Інше формулювання тих
    самих речень - інфо: це не помилка факту і не блокує схвалення."""
    findings: list[dict] = []
    by_lang: dict = {}
    for a in artifacts:
        html = getattr(a, 'html', None) if not isinstance(a, dict) else a.get('html')
        lang = getattr(a, 'language', None) if not isinstance(a, dict) else a.get('language')
        variant = getattr(a, 'variant', None) if not isinstance(a, dict) else a.get('variant')
        by_lang.setdefault(lang, {})[variant] = html or ''
    for lang, variants in by_lang.items():
        if 'desktop' not in variants or 'mobile' not in variants:
            continue
        desk_doc, mob_doc = parse_fragment(variants['desktop']), parse_fragment(variants['mobile'])
        desk_values = {_norm_number(m.group(1)) + m.group(2).lower() for t in desk_doc['texts'] for m in _VALUE_RE.finditer(t['text'])}
        mob_values = {_norm_number(m.group(1)) + m.group(2).lower() for t in mob_doc['texts'] for m in _VALUE_RE.finditer(t['text'])}
        if desk_values != mob_values:
            only = sorted(desk_values ^ mob_values)
            findings.append(finding('variant_values_mismatch', 'warning',
                                    f'Десктоп і мобільна називають різні значення: {", ".join(only[:6])}',
                                    language=norm_lang(lang), variant='mobile', evidence=', '.join(only[:6]), source='seo',
                                    suggestion='Обидві версії мають називати ті самі підтверджені значення'))
        desk = {_norm_sentence(s) for t in desk_doc['texts'] for s in sentences(t['text']) if len(words(s)) >= 4}
        mob = {_norm_sentence(s) for t in mob_doc['texts'] for s in sentences(t['text']) if len(words(s)) >= 4}
        if desk and mob and (desk - mob or mob - desk):
            sample = next(iter((desk - mob) or (mob - desk)))
            findings.append(finding('variant_text_mismatch', 'info',
                                    f'Десктоп і мобільна сформульовані по-різному: {len(desk - mob)} речень лише на десктопі, {len(mob - desk)} лише на мобільній',
                                    language=norm_lang(lang), variant='mobile', evidence=sample, source='seo',
                                    suggestion='Перегенерувати переклад: мобільна бере переклад десктопа дослівно'))
    return findings


# ---------------------------------------------------------------------------
# Зведений прогін для проєкту
# ---------------------------------------------------------------------------

def run_rich_audits(artifacts: list, product: dict | None, brief: dict | None = None, profile: dict | None = None) -> list[dict]:
    """Усі детерміновані SEO/GEO/human/language перевірки для набору артефактів.
    Повертає список звітів {type, score, summary, issues, suggestions, findings}."""
    evidence = (product or {}).get('evidence') or []
    grouped: dict = {kind: [] for kind in CRITIC_TYPES_NEW}
    for a in artifacts:
        html = getattr(a, 'html', None) if not isinstance(a, dict) else a.get('html')
        lang = getattr(a, 'language', None) if not isinstance(a, dict) else a.get('language')
        variant = getattr(a, 'variant', None) if not isinstance(a, dict) else a.get('variant')
        grouped['seo'].extend(audit_rich_fragment(html, product, lang, variant, brief))
        grouped['geo'].extend(audit_geo_copy(html, product, lang, variant, brief, evidence, profile))
        grouped['human'].extend(audit_human_copy(html, lang, variant, brief, product))
        grouped['language'].extend(audit_language_quality(html, lang, variant, product, brief))
    grouped['seo'].extend(audit_variant_consistency(artifacts))
    reports = []
    for kind, rows in grouped.items():
        # Однакова знахідка в desktop і mobile однієї мови - одна позиція.
        unique: dict = {}
        for row in rows:
            unique.setdefault(row['key'], row)
        rows = list(unique.values())
        # Оцінка - за проблемами, а не за копіями: та сама знахідка на десктопі й
        # мобільній одної мови рахується один раз (у звіті вони вже склеєні).
        scored: dict = {}
        for row in rows:
            scored.setdefault((row['code'], row['language'], row.get('block'), row['message'], row['evidence']), row)
        score, _summary, _issues, _suggestions = report_from_findings(list(scored.values()))
        _score, summary, issues, suggestions = report_from_findings(rows)
        reports.append({'type': kind, 'score': score, 'summary': summary, 'issues': issues,
                        'suggestions': suggestions, 'findings': rows})
    return reports


def legacy_findings(kind: str, issues: list[str], language: str = '', variant: str = '') -> list[dict]:
    """Структурні знахідки для старих критиків (html/facts/accessibility/marketing/render):
    вони віддають рядки, а ворота схвалення читають severity."""
    rows = []
    for text in issues or []:
        low = str(text).lower()
        severity = 'warning'
        code = f'{kind}_issue'
        if kind == 'html' and ('h1' in low or 'script' in low or 'missing complete section' in low):
            severity, code = 'critical', 'broken_html' if 'section' in low else ('h1_in_fragment' if 'h1' in low else 'script_in_fragment')
        elif kind == 'facts' and 'identifiers missing' in low:
            severity, code = 'critical', 'product_identity_mismatch'
        elif kind == 'accessibility' and 'no alt' in low:
            severity, code = 'critical', 'alt_missing'
        elif kind == 'render' and re.search(r'обрізан|перекрит|clipped|covered|overflow|горизонтальн', low):
            severity, code = 'critical', 'render_defect'
        elif kind == 'render':
            code = 'render_issue'
        elif kind == 'marketing':
            severity = 'info'
        rows.append(finding(code, severity, str(text), language=language, variant=variant, source=kind))
    return rows


# ---------------------------------------------------------------------------
# SEO-бриф
# ---------------------------------------------------------------------------

INTENTS = ('informational', 'commercial_investigation', 'transactional', 'navigational')

BUYER_QUESTION_TEMPLATES = {
    'uk': ['Для чого підходить {name}?', 'Які ключові характеристики {name}?', 'Що врахувати перед вибором {category}?'],
    'pl': ['Do czego nadaje się {name}?', 'Jakie są kluczowe parametry {name}?', 'Na co zwrócić uwagę przy wyborze: {category}?'],
    'en': ['What is {name} used for?', 'What are the key specifications of {name}?', 'What to consider before choosing {category}?'],
    'ru': ['Для чего подходит {name}?', 'Какие ключевые характеристики {name}?', 'Что учесть при выборе: {category}?'],
}


def empty_brief() -> dict:
    return {
        'market': [], 'language': 'uk', 'audience': '', 'search_intent': 'commercial_investigation',
        'primary_topic': '', 'secondary_topics': [], 'entities': [], 'buyer_questions': [],
        'forbidden_claims': [], 'source': 'manual', 'collected_at': '', 'keywords': [],
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def build_seo_brief(product: dict | None, *, language: str = 'uk', market: list | None = None,
                    manual: dict | None = None, source: str = 'auto', profile: dict | None = None) -> dict:
    """Бриф з товару (режим «Автоматично»), або нормалізований ручний/імпортований.

    Автоматичний режим визначає категорію, сутності й питання покупця - і НЕ
    вигадує search volume. Бриф не розширює Product JSON: ключовий запит не є
    фактом, і ніщо звідси не потрапляє у характеристики.
    """
    product = product or {}
    brief = empty_brief()
    lang = norm_lang(language)
    brief['language'] = lang
    brief['market'] = [str(m).upper() for m in (market or (profile or {}).get('markets') or ['UA'])]
    name = str(product.get('name') or '').strip()
    brand = str(product.get('brand') or '').strip()
    category = str(product.get('category') or '').strip()
    brief['primary_topic'] = category or name
    entities = [x for x in (brand, name, (profile or {}).get('organization_name') or '') if x]
    for spec in product.get('specs') or []:
        if isinstance(spec, dict):
            for word in re.findall(r'\b(?:NVIDIA|AMD|Intel|ASUS|Bambu Lab|Creality|Prusa|Wi-?Fi \d|USB-?C|Thunderbolt \d|HDMI|DisplayPort|PCIe \d(?:\.\d)?|DDR\d|NVMe)\b', str(spec.get('value') or ''), re.I):
                entities.append(word)
    brief['entities'] = list(dict.fromkeys(entities))[:12]
    templates = BUYER_QUESTION_TEMPLATES.get(lang, BUYER_QUESTION_TEMPLATES['en'])
    if name:
        brief['buyer_questions'] = [t.format(name=name, category=category or name) for t in templates]
    brief['secondary_topics'] = [f'{brand} {category}'.strip()] if brand and category else []
    brief['source'] = source
    brief['collected_at'] = _now_iso()
    if manual:
        for key in ('market', 'language', 'audience', 'search_intent', 'primary_topic', 'secondary_topics', 'entities',
                    'buyer_questions', 'forbidden_claims', 'source', 'collected_at', 'keywords', 'publishing_profile_id'):
            if key in manual and manual[key] not in (None, ''):
                brief[key] = manual[key]
        brief['source'] = manual.get('source') or 'manual'
        brief['collected_at'] = manual.get('collected_at') or _now_iso()
    return normalize_brief(brief)


def normalize_brief(brief: dict | None) -> dict:
    out = empty_brief()
    brief = brief or {}
    for key in out:
        if key in brief and brief[key] is not None:
            out[key] = brief[key]
    if 'publishing_profile_id' in brief:
        out['publishing_profile_id'] = brief['publishing_profile_id']
    out['language'] = norm_lang(out.get('language') or 'uk')
    if isinstance(out['market'], str):
        out['market'] = [m.strip().upper() for m in re.split(r'[,\s]+', out['market']) if m.strip()]
    out['market'] = [str(m).upper()[:8] for m in out['market']][:10]
    if out['search_intent'] not in INTENTS:
        out['search_intent'] = 'commercial_investigation'
    for key in ('secondary_topics', 'entities', 'buyer_questions', 'forbidden_claims'):
        value = out.get(key)
        if isinstance(value, str):
            value = [x.strip() for x in re.split(r'[\n;]+', value) if x.strip()]
        out[key] = [str(x).strip()[:200] for x in (value or []) if str(x).strip()][:40]
    out['primary_topic'] = str(out.get('primary_topic') or '')[:200]
    out['audience'] = str(out.get('audience') or '')[:300]
    keywords = []
    for row in out.get('keywords') or []:
        if isinstance(row, dict) and row.get('query'):
            keywords.append({k: row.get(k) for k in ('query', 'country', 'language', 'impressions', 'clicks', 'position',
                                                      'search_volume', 'cpc', 'competition', 'intent', 'date', 'source') if row.get(k) is not None})
    out['keywords'] = keywords[:200]
    out['source'] = str(out.get('source') or 'manual')[:40]
    out['collected_at'] = str(out.get('collected_at') or '')[:40]
    return out


_CSV_ALIASES = {
    'query': ('query', 'keyword', 'search term', 'top queries', 'запит', 'запрос', 'keywords', 'top query'),
    'country': ('country', 'country code', 'location', 'країна', 'location_code', 'geo'),
    'language': ('language', 'language code', 'мова', 'lang'),
    'impressions': ('impressions', 'покази', 'показы', 'impr'),
    'clicks': ('clicks', 'кліки', 'клики'),
    'position': ('position', 'average position', 'avg. position', 'середня позиція', 'avg position', 'rank'),
    'search_volume': ('search volume', 'volume', 'avg. monthly searches', 'monthly searches', 'search_volume', 'частота'),
    'cpc': ('cpc', 'top of page bid (low range)', 'cost per click'),
    'competition': ('competition', 'competition (indexed value)', 'конкуренція', 'competition_index'),
    'intent': ('intent', 'serp intent', 'search intent', 'main_intent'),
    'date': ('date', 'дата', 'period', 'month'),
}


def _num(value):
    if value in (None, ''):
        return None
    text = str(value).strip().replace(' ', '').replace(' ', '').replace('%', '')
    if re.fullmatch(r'-?\d+(?:[.,]\d+)?', text):
        return float(text.replace(',', '.'))
    return None


def import_keyword_data(payload: str, fmt: str = 'csv', source: str = 'import') -> list[dict]:
    """CSV/JSON вивантаження GSC, Keyword Planner або DataForSEO -> уніфіковані рядки.
    Датований snapshot: результат відтворюваний, live-дані при генерації не запитуються."""
    rows: list[dict] = []
    if fmt == 'json':
        data = json.loads(payload or '[]')
        if isinstance(data, dict):
            for key in ('rows', 'items', 'result', 'tasks', 'data', 'keywords'):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if isinstance(data, dict):
            data = [data]
        records = []
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict):
                continue
            # DataForSEO: tasks[].result[].items[] / keyword_info
            if isinstance(item.get('result'), list):
                for res in item['result']:
                    for sub in (res.get('items') or [res]) if isinstance(res, dict) else []:
                        records.append(sub)
                continue
            if isinstance(item.get('keys'), list):  # GSC API row: keys=[query], clicks, impressions, position
                records.append({'query': item['keys'][0], **{k: item.get(k) for k in ('clicks', 'impressions', 'position')}})
                continue
            records.append(item)
        for rec in records:
            info = rec.get('keyword_info') if isinstance(rec.get('keyword_info'), dict) else {}
            intent = rec.get('search_intent_info') if isinstance(rec.get('search_intent_info'), dict) else {}
            query = rec.get('query') or rec.get('keyword')
            if not query and isinstance(rec.get('keys'), list) and rec['keys']:
                query = rec['keys'][0]
            row = {
                'query': query,
                'country': rec.get('country') or rec.get('location_code') or rec.get('location'),
                'language': rec.get('language') or rec.get('language_code'),
                'impressions': _num(rec.get('impressions')),
                'clicks': _num(rec.get('clicks')),
                'position': _num(rec.get('position')),
                'search_volume': _num(rec.get('search_volume') if rec.get('search_volume') is not None else info.get('search_volume')),
                'cpc': _num(rec.get('cpc') if rec.get('cpc') is not None else info.get('cpc')),
                'competition': _num(rec.get('competition') if rec.get('competition') is not None else info.get('competition')),
                'intent': rec.get('intent') or intent.get('main_intent'),
                'date': rec.get('date') or info.get('last_updated_time'),
            }
            if row['query']:
                rows.append(row)
    else:
        import csv
        import io
        text = (payload or '').lstrip('﻿')
        sample = text[:2048]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        header_map = {}
        for column in reader.fieldnames or []:
            low = (column or '').strip().lower()
            for key, aliases in _CSV_ALIASES.items():
                if low in aliases and key not in header_map:
                    header_map[key] = column
        if 'query' not in header_map:
            raise ValueError('Не знайдено колонку запиту (query / keyword / search term)')
        for record in reader:
            row = {key: record.get(column) for key, column in header_map.items()}
            for key in ('impressions', 'clicks', 'position', 'search_volume', 'cpc', 'competition'):
                row[key] = _num(row.get(key))
            if (row.get('query') or '').strip():
                row['query'] = row['query'].strip()
                rows.append(row)
    for row in rows:
        row['source'] = source
        row['query'] = str(row['query']).strip()[:200]
        for key in list(row):
            if row[key] is None:
                del row[key]
    return rows[:500]


def brief_from_keywords(rows: list[dict], product: dict | None, language: str, source: str, market: list | None = None,
                        profile: dict | None = None) -> dict:
    """Бриф з імпортованих запитів: primary = найсильніший запит, secondary = наступні.
    Показує джерело і дату даних; volume береться лише з даних, не вигадується."""
    def weight(row):
        return (row.get('clicks') or 0) * 5 + (row.get('impressions') or 0) / 100 + (row.get('search_volume') or 0) / 10
    ordered = sorted(rows, key=weight, reverse=True)
    brief = build_seo_brief(product, language=language, market=market, source=source, profile=profile)
    if ordered:
        brief['primary_topic'] = ordered[0]['query']
        brief['secondary_topics'] = [r['query'] for r in ordered[1:9]]
        intents = Counter(str(r.get('intent') or '').lower() for r in ordered if r.get('intent'))
        if intents:
            top = intents.most_common(1)[0][0]
            brief['search_intent'] = {'commercial': 'commercial_investigation', 'transactional': 'transactional',
                                      'informational': 'informational', 'navigational': 'navigational'}.get(top, brief['search_intent'])
        dates = sorted({str(r.get('date')) for r in ordered if r.get('date')})
        brief['collected_at'] = dates[-1] if dates else _now_iso()
    brief['keywords'] = ordered[:200]
    brief['source'] = source
    return normalize_brief(brief)


def seo_brief_block(brief: dict | None) -> str:
    """Розділ SEO BRIEF для промпту. Бриф - не список слів для вставки."""
    brief = normalize_brief(brief) if brief else None
    if not brief or not (brief.get('primary_topic') or brief.get('secondary_topics') or brief.get('buyer_questions')):
        return 'SEO BRIEF: none. Write for the buyer; name the category and purpose early.'
    lines = ['SEO BRIEF (search context only - NOT product facts; it cannot add, change or confirm any characteristic):']
    lines.append(f'- primary topic (the meaning of the page, used naturally, never forced): {brief["primary_topic"]}')
    if brief.get('secondary_topics'):
        lines.append('- secondary topics (only where they match the facts): ' + '; '.join(brief['secondary_topics'][:8]))
    if brief.get('entities'):
        lines.append('- entities to name precisely: ' + ', '.join(brief['entities'][:12]))
    if brief.get('audience'):
        lines.append(f'- audience: {brief["audience"]}')
    lines.append(f'- search intent: {brief.get("search_intent")}')
    if brief.get('buyer_questions'):
        lines.append('- buyer questions to answer inside existing sections (only with confirmed facts): ' + ' | '.join(brief['buyer_questions'][:6]))
    if brief.get('forbidden_claims'):
        lines.append('- forbidden claims: ' + '; '.join(brief['forbidden_claims'][:10]))
    lines.append(f'- source: {brief.get("source")} · collected: {brief.get("collected_at") or "n/a"}')
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Standalone landing: metadata, JSON-LD, finalize, audit
# ---------------------------------------------------------------------------

LANDING_I18N = {
    'uk': {'buy': 'Купити', 'categories': 'Категорії акційних товарів', 'products': 'Товари акції', 'price': 'Ціна',
           'advantages': 'Чому ARTLINE', 'fallback_lead': 'Акційні товари з актуальними цінами.',
           'language_name': 'українська', 'items': 'товарів'},
    'ru': {'buy': 'Купить', 'categories': 'Категории акционных товаров', 'products': 'Товары акции', 'price': 'Цена',
           'advantages': 'Почему ARTLINE', 'fallback_lead': 'Акционные товары с актуальными ценами.',
           'language_name': 'русский', 'items': 'товаров'},
    'pl': {'buy': 'Kup', 'categories': 'Kategorie produktów promocyjnych', 'products': 'Produkty w promocji', 'price': 'Cena',
           'advantages': 'Dlaczego ARTLINE', 'fallback_lead': 'Produkty promocyjne z aktualnymi cenami.',
           'language_name': 'polski', 'items': 'produktów'},
    'en': {'buy': 'Buy', 'categories': 'Sale categories', 'products': 'Products on sale', 'price': 'Price',
           'advantages': 'Why ARTLINE', 'fallback_lead': 'Sale products with current prices.',
           'language_name': 'English', 'items': 'products'},
}


def landing_i18n(language: str) -> dict:
    return LANDING_I18N.get(norm_lang(language), LANDING_I18N['uk'])


def _trim(text: str, limit: int) -> str:
    text = _clean_text(text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(' ', 1)[0]
    return cut.rstrip(' ,;:-–') + '…'


def build_landing_metadata(campaign: dict, products: list[dict], profile: dict | None, language: str,
                           canonical: str = '', alternates: dict | None = None, published: bool = False,
                           image: str = '') -> dict:
    """Детермінований SEO-head для лендінгу. Модель його не пише."""
    lang = norm_lang(language)
    profile = profile or {}
    org = str(profile.get('organization_name') or 'ARTLINE')
    title_core = _clean_text(campaign.get('campaign_title') or campaign.get('name') or '')
    subtitle = _clean_text(campaign.get('campaign_subtitle') or '')
    title = _trim(f'{title_core} · {org}' if title_core else org, 65)
    i18n = landing_i18n(lang)
    parts = [subtitle or title_core]
    if products:
        parts.append(f'{len(products)} {i18n["items"]}')
    delivery = ((profile.get('statements') or {}).get('delivery') or {}).get(lang)
    if delivery:
        parts.append(delivery)
    description = _trim('. '.join(p.rstrip('.') for p in parts if p) + '.', 158)
    canonical = str(canonical or '').strip()
    robots = 'index,follow,max-image-preview:large' if (published and canonical) else 'noindex,nofollow'
    alternates = {('x-default' if str(k).lower() == 'x-default' else norm_lang(k)): str(v).strip()
                  for k, v in (alternates or {}).items() if str(v or '').strip()}
    if canonical and lang not in alternates and alternates:
        alternates[lang] = canonical
    og_image = image or next((p.get('image') for p in products if p.get('image')), '')
    return {
        'lang': lang, 'title': title, 'description': description, 'canonical': canonical, 'robots': robots,
        'alternates': alternates, 'published': bool(published and canonical),
        'og': {'og:type': 'website', 'og:title': title, 'og:description': description, 'og:url': canonical,
               'og:site_name': org, 'og:locale': {'uk': 'uk_UA', 'pl': 'pl_PL', 'en': 'en_US', 'ru': 'ru_RU'}.get(lang, lang),
               'og:image': og_image},
        'twitter': {'twitter:card': 'summary_large_image' if og_image else 'summary', 'twitter:title': title,
                    'twitter:description': description, 'twitter:image': og_image},
    }


_FORBIDDEN_PRODUCT_KEYS = ('aggregateRating', 'review', 'availability', 'priceValidUntil', 'shippingDetails',
                           'hasMerchantReturnPolicy', 'returnPolicy', 'sku', 'gtin', 'gtin13', 'gtin8', 'gtin12', 'gtin14', 'mpn', 'brand')


def _same_site(url: str, profile: dict | None) -> bool:
    host = urlparse(url or '').netloc.lower()
    for domain in (profile or {}).get('domains') or []:
        domain = str(domain).lower()
        if host == domain or host.endswith('.' + domain):
            return True
    return False


def build_landing_jsonld(campaign: dict, products: list[dict], profile: dict | None, language: str, canonical: str = '',
                         faq: list[dict] | None = None, breadcrumbs: list[dict] | None = None, description: str = '') -> list[dict]:
    """JSON-LD лише з перевірених даних. Нічого не вигадується: Offer - тільки з
    ціною, валютою і URL; brand/sku/gtin/рейтинги/наявність у Product заборонені."""
    lang = norm_lang(language)
    profile = profile or {}
    org_url = str(profile.get('organization_url') or '').strip()
    org_name = str(profile.get('organization_name') or 'ARTLINE')
    graph: list[dict] = []
    organization = {'@type': 'Organization', 'name': org_name}
    if org_url:
        organization['@id'] = org_url.rstrip('/') + '/#organization'
        organization['url'] = org_url
    if profile.get('logo_url'):
        organization['logo'] = str(profile['logo_url'])
    graph.append(organization)
    if profile.get('primary_site') and org_url and canonical and _same_site(canonical, profile):
        graph.append({'@type': 'WebSite', '@id': org_url.rstrip('/') + '/#website', 'url': org_url, 'name': org_name,
                      'inLanguage': lang, 'publisher': {'@id': organization.get('@id')} if organization.get('@id') else None})
    page = {'@type': 'CollectionPage', 'name': _clean_text(campaign.get('campaign_title') or campaign.get('name') or ''),
            'inLanguage': lang}
    if canonical:
        page['url'] = canonical
        page['@id'] = canonical + '#webpage'
    if description:
        page['description'] = description
    if organization.get('@id'):
        page['publisher'] = {'@id': organization['@id']}
    graph.append(page)
    items = []
    for index, product in enumerate(products or [], start=1):
        name = _clean_text(product.get('name') or '')
        url = str(product.get('url') or '').strip()
        if not name or not url:
            continue
        node = {'@type': 'Product', 'name': name, 'url': url}
        if product.get('image'):
            node['image'] = str(product['image'])
        price = str(product.get('price') or '').strip()
        currency = str(product.get('currency') or ('UAH' if price else '')).strip()
        if price and currency and url:
            node['offers'] = {'@type': 'Offer', 'price': price, 'priceCurrency': currency, 'url': url}
        for key in _FORBIDDEN_PRODUCT_KEYS:
            node.pop(key, None)
        items.append({'@type': 'ListItem', 'position': index, 'item': node})
    if items:
        graph.append({'@type': 'ItemList', 'itemListElement': items})
    if breadcrumbs:
        crumbs = [{'@type': 'ListItem', 'position': i, 'name': _clean_text(c.get('name') or ''), 'item': c.get('url')}
                  for i, c in enumerate(breadcrumbs, start=1) if c.get('name') and c.get('url')]
        if crumbs:
            graph.append({'@type': 'BreadcrumbList', 'itemListElement': crumbs})
    if faq:
        entries = [{'@type': 'Question', 'name': _clean_text(q.get('question') or ''),
                    'acceptedAnswer': {'@type': 'Answer', 'text': _clean_text(q.get('answer') or '')}}
                   for q in faq if q.get('question') and q.get('answer')]
        if entries:
            graph.append({'@type': 'FAQPage', 'mainEntity': entries})
    for node in graph:
        for key in [k for k, v in node.items() if v is None]:
            node.pop(key)
    return [{'@context': 'https://schema.org', '@graph': graph}]


def visible_faq(soup) -> list[dict]:
    """Питання/відповіді, які РЕАЛЬНО видно на сторінці (details/summary або h3+p у FAQ-блоці)."""
    out = []
    for details in soup.find_all('details'):
        summary = details.find('summary')
        if not summary:
            continue
        question = _clean_text(summary.get_text(' '))
        answer = _clean_text(' '.join(p.get_text(' ') for p in details.find_all(['p', 'li'])))
        if question and answer:
            out.append({'question': question, 'answer': answer})
    return out


_MANAGED_META = re.compile(r'^(description|robots|twitter:.*|og:.*|viewport)$', re.I)


def finalize_landing_seo(markup: str, *, campaign: dict, products: list[dict], profile: dict | None, language: str,
                         canonical: str = '', alternates: dict | None = None, published: bool = False,
                         breadcrumbs: list[dict] | None = None) -> str:
    """Після санітизації: сервер сам ставить title, description, canonical, robots,
    OG, Twitter, html lang, hreflang і JSON-LD. Ідемпотентно - керовані теги
    замінюються, а не дублюються. Чернетка/превʼю завжди noindex; canonical - лише
    фактичний опублікований URL, ніколи не тимчасовий токен."""
    soup = BeautifulSoup(markup or '', 'html.parser')
    html_tag = soup.find('html')
    if html_tag is None:
        return markup
    head = soup.find('head')
    if head is None:
        head = soup.new_tag('head')
        html_tag.insert(0, head)
    meta = build_landing_metadata(campaign, products, profile, language, canonical, alternates, published)
    html_tag['lang'] = meta['lang']
    # Прибрати все, чим керує сервер (включно з тим, що могла написати модель).
    for node in head.find_all('title'):
        node.decompose()
    for node in head.find_all('meta'):
        name = node.get('name') or node.get('property') or ''
        if _MANAGED_META.match(name) and name.lower() != 'viewport':
            node.decompose()
    for node in head.find_all('link'):
        if (node.get('rel') and 'canonical' in node.get('rel')) or node.get('hreflang') or (node.get('rel') and 'alternate' in node.get('rel')):
            node.decompose()
    for node in soup.find_all('script', attrs={'type': 'application/ld+json'}):
        node.decompose()
    if head.find('meta', attrs={'charset': True}) is None:
        charset = soup.new_tag('meta')
        charset['charset'] = 'utf-8'
        head.insert(0, charset)
    if head.find('meta', attrs={'name': 'viewport'}) is None:
        viewport = soup.new_tag('meta')
        viewport['name'] = 'viewport'
        viewport['content'] = 'width=device-width,initial-scale=1'
        head.append(viewport)
    title = soup.new_tag('title')
    title.string = meta['title']
    head.append(title)

    def add_meta(attr, key, value):
        if not value:
            return
        tag = soup.new_tag('meta')
        tag[attr] = key
        tag['content'] = value
        head.append(tag)

    add_meta('name', 'description', meta['description'])
    add_meta('name', 'robots', meta['robots'])
    if meta['canonical']:
        link = soup.new_tag('link')
        link['rel'] = 'canonical'
        link['href'] = meta['canonical']
        head.append(link)
        for code, url in sorted(meta['alternates'].items()):
            alt = soup.new_tag('link')
            alt['rel'] = 'alternate'
            alt['hreflang'] = 'x-default' if code == 'x-default' else code
            alt['href'] = url
            head.append(alt)
    for key, value in meta['og'].items():
        add_meta('property', key, value)
    for key, value in meta['twitter'].items():
        add_meta('name', key, value)
    faq = visible_faq(soup)
    for node in graph_nodes(build_landing_jsonld(campaign, products, profile, language, meta['canonical'], faq, breadcrumbs, meta['description'])):
        script = soup.new_tag('script')
        script['type'] = 'application/ld+json'
        script.string = json.dumps(node, ensure_ascii=False).replace('</', '<\\/')
        head.append(script)
    return str(soup)


def graph_nodes(jsonld: list[dict]) -> list[dict]:
    return jsonld


def audit_landing_document(markup: str, *, language: str, expected_canonical: str = '', expected_alternates: dict | None = None,
                           published: bool = False, products: list[dict] | None = None, categories: list[dict] | None = None,
                           profile: dict | None = None) -> list[dict]:
    """Перевірка standalone-документа: один h1, lang, title/description, canonical,
    hreflang, robots за станом публікації, OG/Twitter, JSON-LD, посилання,
    відсутність непідтверджених комерційних тверджень, базові CWV-сигнали."""
    lang = norm_lang(language)
    soup = BeautifulSoup(markup or '', 'html.parser')
    findings: list[dict] = []
    src = 'landing'
    mk = lambda *a, **k: findings.append(finding(*a, language=lang, source=src, **k))  # noqa: E731
    html_tag = soup.find('html')
    head = soup.find('head')
    if html_tag is None or head is None:
        mk('not_a_document', 'critical', 'Не повноцінний HTML-документ (немає html/head)', suggestion='Лендінг - standalone-документ')
        return findings
    h1s = soup.find_all('h1')
    if len(h1s) != 1:
        mk('h1_count', 'critical', f'h1 на сторінці: {len(h1s)} (має бути рівно один)',
           evidence=_clean_text(h1s[0].get_text(' ')) if h1s else '', suggestion='Один h1 - назва кампанії')
    if (html_tag.get('lang') or '').lower() != lang:
        mk('html_lang', 'critical', f'html lang="{html_tag.get("lang") or ""}" не відповідає мові {lang}', suggestion=f'Поставити lang="{lang}"')
    title = head.find('title')
    title_text = _clean_text(title.get_text()) if title else ''
    if not title_text:
        mk('title_missing', 'critical', 'Немає <title>', suggestion='Заголовок сторінки формує сервер (finalize_landing_seo)')
    elif len(title_text) > 70:
        mk('title_long', 'warning', f'Title задовгий: {len(title_text)} символів', evidence=title_text, suggestion='До 65 символів')
    desc = head.find('meta', attrs={'name': 'description'})
    desc_text = _clean_text(desc.get('content')) if desc else ''
    if not desc_text:
        mk('description_missing', 'critical', 'Немає meta description', suggestion='Опис формує сервер')
    elif not 50 <= len(desc_text) <= 165:
        mk('description_length', 'warning', f'Meta description: {len(desc_text)} символів', evidence=desc_text, suggestion='50-160 символів')
    canonical = head.find('link', attrs={'rel': 'canonical'})
    canonical_href = (canonical.get('href') or '').strip() if canonical else ''
    if published:
        if not canonical_href:
            mk('canonical_missing', 'critical', 'Опублікована сторінка без canonical', suggestion='Canonical = фактичний публічний URL')
        elif expected_canonical and canonical_href != expected_canonical:
            mk('canonical_mismatch', 'critical', 'Canonical не збігається з опублікованим URL', evidence=canonical_href, suggestion=f'Очікується {expected_canonical}')
        if canonical_href and re.search(r'/p/[A-Za-z0-9_-]{16,}', canonical_href):
            mk('canonical_preview_token', 'critical', 'Canonical вказує на тимчасове превʼю-посилання', evidence=canonical_href, suggestion='Canonical лише на публічний URL')
    robots = head.find('meta', attrs={'name': 'robots'})
    robots_text = (robots.get('content') or '').lower() if robots else ''
    if published and 'noindex' in robots_text:
        mk('robots_noindex_published', 'critical', 'Опублікована сторінка має noindex', evidence=robots_text, suggestion='index,follow,max-image-preview:large')
    if not published and 'noindex' not in robots_text:
        mk('robots_draft_indexable', 'critical', 'Чернетка/превʼю без noindex', evidence=robots_text or '(немає meta robots)', suggestion='noindex,nofollow для чернетки')
    hreflangs = {(l.get('hreflang') or '').lower(): (l.get('href') or '') for l in head.find_all('link', attrs={'rel': 'alternate'}) if l.get('hreflang')}
    for code, url in (expected_alternates or {}).items():
        key = 'x-default' if code == 'x-default' else norm_lang(code)
        if key not in hreflangs:
            mk('hreflang_missing', 'critical' if published else 'warning', f'Немає hreflang {key}', suggestion=f'<link rel="alternate" hreflang="{key}" href="{url}">')
        elif hreflangs[key] != url:
            mk('hreflang_mismatch', 'warning', f'hreflang {key} вказує не туди', evidence=hreflangs[key], suggestion=f'Очікується {url}')
    if hreflangs and lang not in hreflangs and 'x-default' not in hreflangs:
        mk('hreflang_self_missing', 'warning', 'hreflang без посилання на саму сторінку', suggestion='Кожна мовна версія посилається і на себе')
    for prop in ('og:title', 'og:description', 'og:type', 'og:url'):
        if head.find('meta', attrs={'property': prop}) is None:
            mk('og_missing', 'warning', f'Немає {prop}', suggestion='Open Graph формує сервер')
            break
    if head.find('meta', attrs={'property': 'og:image'}) is None:
        mk('og_image_missing', 'info', 'Немає og:image', suggestion='Перше фото товару або hero')
    if head.find('meta', attrs={'name': 'twitter:card'}) is None:
        mk('twitter_card_missing', 'warning', 'Немає twitter:card', suggestion='summary_large_image')
    # JSON-LD
    scripts = soup.find_all('script', attrs={'type': 'application/ld+json'})
    if not scripts:
        mk('jsonld_missing', 'warning', 'Немає JSON-LD', suggestion='Organization + CollectionPage + ItemList формує сервер')
    for script in scripts:
        try:
            data = json.loads(script.string or '')
        except Exception:
            mk('jsonld_invalid', 'critical', 'JSON-LD не парситься', evidence=(script.string or '')[:80], suggestion='Генерувати лише сервером')
            continue
        nodes = data.get('@graph') if isinstance(data, dict) and isinstance(data.get('@graph'), list) else [data]
        page_faq = visible_faq(soup)
        page_text = _clean_text(soup.get_text(' ')).lower()
        for node in nodes:
            if not isinstance(node, dict):
                continue
            types = node.get('@type')
            types = types if isinstance(types, list) else [types]
            if 'ItemList' in types:
                for item in node.get('itemListElement') or []:
                    product = item.get('item') if isinstance(item, dict) else None
                    if isinstance(product, dict):
                        bad = [k for k in _FORBIDDEN_PRODUCT_KEYS if k in product]
                        if bad:
                            mk('jsonld_forbidden_field', 'critical', f'Product містить непідтверджені поля: {", ".join(bad)}', evidence=product.get('name', ''),
                               suggestion='Лише name/url/image і Offer з ціною, валютою, URL')
                        offer = product.get('offers')
                        if isinstance(offer, dict) and not all(offer.get(k) for k in ('price', 'priceCurrency', 'url')):
                            mk('jsonld_offer_incomplete', 'critical', 'Offer без price/priceCurrency/url', evidence=product.get('name', ''),
                               suggestion='Offer лише за наявності всіх трьох полів')
                        if products and product.get('url') and product['url'] not in {p.get('url') for p in products}:
                            mk('jsonld_unknown_url', 'critical', 'URL товару в JSON-LD не з проб', evidence=product['url'], suggestion='Лише URL реальних товарів')
            if 'FAQPage' in types:
                for entry in node.get('mainEntity') or []:
                    q = _clean_text((entry or {}).get('name') or '')
                    a = _clean_text(((entry or {}).get('acceptedAnswer') or {}).get('text') or '')
                    if not any(q == f['question'] and a == f['answer'] for f in page_faq):
                        mk('faq_schema_mismatch', 'critical', 'FAQPage не відповідає видимому FAQ', evidence=q, suggestion='Schema лише з видимих і підтверджених питань')
                        break
            if 'Product' in types and node.get('name') and str(node['name']).lower() not in page_text:
                mk('jsonld_product_invisible', 'critical', 'Product у schema не показаний на сторінці', evidence=str(node['name']), suggestion='Product лише для реально показаних товарів')
    # Посилання
    allowed = {p.get('url') for p in (products or [])} | {p.get('image') for p in (products or [])} | \
              {c.get('url') for c in (categories or [])} | {c.get('image') for c in (categories or [])}
    org_url = str((profile or {}).get('organization_url') or '')
    for a in soup.find_all('a', href=True):
        href = a['href'].strip()
        if href.startswith(('#', '/', 'mailto:', 'tel:')):
            continue
        if not href.startswith(('http://', 'https://')):
            mk('link_scheme', 'critical', 'Посилання з недопустимою схемою', evidence=href, suggestion='Лише http(s) або відносні')
            continue
        if href in allowed or (org_url and href.rstrip('/') == org_url.rstrip('/')) or _same_site(href, profile):
            continue
        mk('unknown_link', 'critical', 'Посилання на невідому адресу (не з проб і не з профілю)', evidence=href,
           suggestion='Лише URL товарів, категорій і домени з Publishing Profile')
    # Непідтверджені комерційні твердження
    facts = [f.lower() for f in company_facts(profile, lang)]
    profile_dict = profile or {}
    allowed_groups = set()
    if (profile_dict.get('verified_facts') or {}).get('delivery_regions'):
        allowed_groups.add('delivery')
    if company_facts({'warranty_text': profile_dict.get('warranty_text')}, lang):
        allowed_groups.add('warranty')
    if company_facts({'service_text': profile_dict.get('service_text')}, lang):
        allowed_groups.update({'support', 'support_24_7'})
    body_texts = [_clean_text(t) for t in soup.body.stripped_strings] if soup.body else []
    for code, pattern, severity in COMMERCIAL_CLAIMS:
        for text in body_texts:
            if not re.search(pattern, text, re.I):
                continue
            low = text.lower()
            if any(f and f in low for f in facts):
                continue
            if code == 'delivery' and 'delivery' in allowed_groups and not re.search(r'швидк|быстр|szybk|fast|express|безкоштовн|бесплатн|darmow|free|\d', low):
                continue
            if code in allowed_groups:
                continue
            mk('unverified_claim', 'critical', f'Комерційне твердження без джерела ({code})', evidence=text,
               suggestion='Лише VERIFIED COMPANY FACTS з Publishing Profile')
            break
    # CWV-сигнали (статичні проксі; справжні LCP/CLS/INP міряє Lighthouse)
    images = soup.find_all('img')
    for index, img in enumerate(images):
        if index > 0 and img.get('loading') != 'lazy':
            mk('cwv_lazy', 'info', 'Зображення поза першим екраном без loading="lazy"', evidence=(img.get('src') or '')[-60:], suggestion='Додати loading="lazy"')
            break
    if images and images[0].get('loading') == 'lazy':
        mk('cwv_hero_lazy', 'warning', 'Перше зображення з loading="lazy" (шкодить LCP)', evidence=(images[0].get('src') or '')[-60:], suggestion='Прибрати lazy з hero')
    if len(markup or '') > 600_000:
        mk('cwv_page_size', 'warning', f'Сторінка важка: {len(markup) // 1024} КБ', suggestion='Інлайнити менше, стиснути фон hero')
    for img in images:
        if not (img.get('alt') or '').strip() and not (img.get('alt') == '' and 'position:absolute' in (img.get('style') or '')):
            mk('landing_alt_missing', 'warning', 'Зображення без alt', evidence=(img.get('src') or '')[-60:], suggestion='Назва товару або категорії')
            break
    return findings


# ---------------------------------------------------------------------------
# Provenance підтверджених фактів
# ---------------------------------------------------------------------------

SOURCE_PRIORITY = ('jsonld', 'spec_table', 'spec_block', 'manual', 'page_text')


def _slug(text: str) -> str:
    text = re.sub(r'[^\w]+', '_', str(text or '').lower(), flags=re.U).strip('_')
    return text[:48] or 'fact'


def build_evidence(product: dict, *, jsonld_specs: list | None = None, table_specs: list | None = None,
                   page_text: str = '', source_url: str = '', manual: list | None = None,
                   jsonld_keys: set | None = None) -> list[dict]:
    """Provenance для кожного значущого факту картки товару.

    Пріоритет джерел: JSON-LD → таблиця характеристик → явний spec-блок →
    підтверджений оператором факт → текст сторінки. Значення, якого немає в
    жодному з них (AI-витяг), позначається ``derived`` - це не підтверджений факт.
    """
    jsonld_map = {str(s.get('name') or '').strip().lower(): str(s.get('value') or '') for s in (jsonld_specs or []) if isinstance(s, dict)}
    table_map = {str(s.get('name') or '').strip().lower(): str(s.get('value') or '') for s in (table_specs or []) if isinstance(s, dict)}
    manual_map = {str(s.get('name') or '').strip().lower(): str(s.get('value') or '') for s in (manual or []) if isinstance(s, dict)}
    text_low = (page_text or '').lower()
    evidence = []
    seen = set()

    def add(fact_id, label, value, source_type, snippet, confidence):
        if fact_id in seen or not str(value).strip():
            return
        seen.add(fact_id)
        evidence.append({'id': fact_id, 'label': label, 'value': str(value), 'source_url': source_url,
                         'source_type': source_type, 'evidence': str(snippet)[:200], 'confidence': confidence})

    for key, label in (('name', 'Назва'), ('brand', 'Бренд'), ('category', 'Категорія'), ('sku', 'Артикул')):
        value = product.get(key)
        if value:
            source = 'jsonld' if key in (jsonld_keys or set()) else 'page_text'
            confirmed = source == 'jsonld' or str(value).lower() in text_low
            add(f'identity_{key}', label, value, source, value, 'confirmed' if confirmed else 'derived')
    for spec in product.get('specs') or []:
        if not isinstance(spec, dict) or not spec.get('name'):
            continue
        name = str(spec['name']).strip()
        value = str(spec.get('value') or '').strip()
        key = name.lower()
        if key in jsonld_map and jsonld_map[key] == value:
            source, snippet, confidence = 'jsonld', f'{name}: {value}', 'confirmed'
        elif key in table_map and table_map[key] == value:
            source, snippet, confidence = 'spec_table', f'{name}: {value}', 'confirmed'
        elif key in manual_map and manual_map[key] == value:
            source, snippet, confidence = 'manual', f'{name}: {value}', 'confirmed'
        elif value.lower() in text_low:
            start = text_low.find(value.lower())
            source, snippet, confidence = 'page_text', (page_text or '')[max(0, start - 60):start + len(value) + 40], 'confirmed'
        else:
            source, snippet, confidence = 'page_text', f'{name}: {value}', 'derived'
        add(f'spec_{_slug(name)}', name, value, source, snippet, confidence)
    for index, feature in enumerate(product.get('features') or []):
        text = str(feature or '').strip()
        if not text:
            continue
        confirmed = text.lower()[:60] in text_low
        add(f'feature_{index + 1}', 'Особливість', text, 'page_text', text, 'confirmed' if confirmed else 'derived')
    return evidence


def confirmed_only(product: dict) -> dict:
    """Product JSON без derived-значень і без розділу evidence - те, що йде в промпт."""
    product = dict(product or {})
    evidence = product.pop('evidence', None) or []
    derived_specs = {e['label'].lower() for e in evidence if e.get('confidence') == 'derived' and e.get('id', '').startswith('spec_')}
    if derived_specs:
        product['specs'] = [s for s in product.get('specs') or [] if not (isinstance(s, dict) and str(s.get('name') or '').lower() in derived_specs)]
    product.pop('_jsonld_keys', None)
    return product


def public_facts_summary(product: dict) -> dict:
    """Скільки фактів підтверджено / виведено - для UI."""
    evidence = (product or {}).get('evidence') or []
    counter = Counter(e.get('confidence') for e in evidence)
    return {'confirmed': counter.get('confirmed', 0), 'derived': counter.get('derived', 0), 'total': len(evidence)}
