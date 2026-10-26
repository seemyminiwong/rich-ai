"""Шаблони AI-тексту за stop-slop (github.com/hardikpandya/stop-slop, коміт 8da1f03).

Аудит 2026-10-26 (docs/audits/styles-vs-stop-slop.md): промпти просили писати без
цих зворотів, але детерміновані перевірки не ловили жодного з 15 прикладів.
Тут - словники для uk/ru/pl/en і кілька структурних ознак. Усі знахідки - warning
або info: це підказка рецензенту, схвалення вони не блокують.

Свідомі відступи від stop-slop для товарного тексту: прислівник із фактом
(«автоматично», «бездротово») лишається, товар як підмет («Інвертор перемикається»)
- нормальний, FAQ складається з питань, а трійки карток - компонент дизайну.
"""
import re

from app.seo_geo import _entity_tokens, finding, norm_lang, parse_fragment, sentences, words

_START = r'(?:^|[.!?]\s+)'

# kind -> (severity, підпис, порада, {мова: шаблон}). Шаблон шукається в тексті поля
# цілком, тож ловить і звороти з двох речень («Не тому, що X. Тому що Y.»).
SLOP_PATTERNS = {
    'throat_clearing': ('warning', 'Вступ-розгін перед суттю («Справа в тому, що…», «Виявляється…»)',
                        'Почати одразу з твердження', {
        'uk': _START + r'(?:справа в тому|річ у тім|виявляється|правда в тому|чесно кажучи|давайте розберемося|ось у чому річ|ось що)\b',
        'ru': _START + r'(?:дело в том|оказывается|правда в том|честно говоря|давайте разбер[её]мся|вот в ч[её]м дело|вот что)\b',
        'pl': _START + r'(?:chodzi o to|okazuje się|prawda jest taka|szczerze mówiąc|oto co|oto dlaczego)\b',
        'en': _START + r"(?:here'?s the thing|here'?s what|here'?s why|it turns out|the truth is|the reality is|let me be clear|let'?s be honest)\b",
    }),
    'emphasis_crutch': ('warning', 'Підпорка для емфази («Ось чому це важливо», «без перебільшення»)',
                        'Прибрати: важливість показує сам факт', {
        'uk': r'(?:ось чому це важливо|це важливо, тому що|і це важливо|без перебільшення|запам.ятайте це)',
        'ru': r'(?:вот почему это важно|это важно, потому что|и это важно|без преувеличения)',
        'pl': r'(?:oto dlaczego to ważne|to ważne, ponieważ|bez przesady)',
        'en': r"(?:here'?s why (?:that|this|it) matters|this matters because|let that sink in|make no mistake|full stop)",
    }),
    'split_contrast': ('warning', 'Контраст-розворот («Не тому, що X. Тому що Y.», «X не проблема. Проблема в Y»)',
                       'Назвати Y прямо, без заперечення перед ним', {
        'uk': (r'\bне тому, що [^.!?]{1,80}[.!?]\s+(?:а\s+)?тому,? що\b|\bне (?:проблема|головне)\.\s+(?:проблема|головне)\b'
               r'|\b(?:питання|справа) не в [^.!?]{1,60}[,.]\s*(?:а\s+)?в\b'),
        'ru': (r'\bне потому, что [^.!?]{1,80}[.!?]\s+(?:а\s+)?потому,? что\b|\bне (?:проблема|главное)\.\s+(?:проблема|главное)\b'
               r'|\b(?:вопрос|дело) не в [^.!?]{1,60}[,.]\s*(?:а\s+)?в\b'),
        'pl': r'\bnie dlatego, że [^.!?]{1,80}[.!?]\s+dlatego, że\b|\bto nie jest problem\b[^.!?]{0,30}\.\s+problem\b',
        'en': (r"\bnot because [^.!?]{1,80}[.!?]\s+because\b|\bisn'?t the problem\.\s"
               r"|\bthe (?:question|answer) isn'?t [^.!?]{1,60}[.,]\s*it'?s\b"),
    }),
    'negative_listing': ('warning', 'Перелік заперечень перед суттю («Не X. Не Y. Це Z.»)',
                         'Сказати, що це, одним реченням', {
        'uk': _START + r'не [^.!?]{1,40}\.\s+не [^.!?]{1,40}\.',
        'ru': _START + r'не [^.!?]{1,40}\.\s+не [^.!?]{1,40}\.',
        'pl': _START + r'nie [^.!?]{1,40}\.\s+nie [^.!?]{1,40}\.',
        'en': _START + r'not [^.!?]{1,40}\.\s+not [^.!?]{1,40}\.',
    }),
    'vague_declarative': ('warning', 'Розмита декларація важливості без конкретики («Різниця відчутна»)',
                          'Назвати конкретне значення або прибрати речення', {
        'uk': r'(?:наслідки (?:цього )?значні|це має значення|різниця (?:відчутна|очевидна|помітна)|ставки високі|це змінює все)',
        'ru': r'(?:последствия (?:этого )?значительны|это имеет значение|разница (?:ощутима|очевидна|заметна)|ставки высоки|это меняет вс[её])',
        'pl': r'(?:różnica jest (?:odczuwalna|oczywista|widoczna)|ma to znaczenie|konsekwencje są znaczące|to zmienia wszystko)',
        'en': (r'(?:the implications are significant|the stakes are high|the difference is (?:noticeable|obvious|clear)'
               r'|the reasons are structural|this changes everything)'),
    }),
    'false_agency': ('info', 'Хибна дієвість: неживе «підказує», «дбає», «розуміє»',
                     'Назвати, хто діє: товар, його частина або покупець', {
        'uk': r'\b(?:дані|технологі[яї]|систем[аи]|алгоритм|інтелект)\s+(?:підказу\w*|дба\w*|піклу\w*|розуміє|знає|відчуває|думає)',
        'ru': r'\b(?:данные|технологи[яи]|систем[аы]|алгоритм|интеллект)\s+(?:подсказыва\w*|забот\w*|понимает|знает|чувствует|думает)',
        'pl': r'\b(?:dane|technologi[ae]|system|algorytm)\s+(?:podpowiada\w*|dba|rozumie|wie|czuje|myśli)\b',
        'en': r'\b(?:data|technology|system|algorithm)s?\s+(?:tells?|cares?|understands?|knows?|feels?|thinks?)\b',
    }),
    'lazy_extreme': ('info', 'Узагальнення-крайність («завжди», «будь-які задачі»)',
                     'Замінити конкретною умовою або значенням', {
        'uk': r'\b(?:завжди|ніколи|будь-як\w*|будь-де|будь-коли|кожному|кожен оцінить)\b',
        'ru': r'\b(?:всегда|никогда|любой|любая|любое|любую|любого|любом|любые|любых|любым|кому угодно|каждому)\b',
        'pl': r'\b(?:zawsze|nigdy|dowoln\w*|każdemu|każdy doceni)\b',
        'en': r'\b(?:always|never|any task|anyone|everyone|every user)\b',
    }),
    'intensifier': ('info', 'Підсилювач без змісту («дуже», «справді»)',
                    'Прибрати або замінити значенням', {
        'uk': r'\b(?:дуже|справді|дійсно|надзвичайно|неймовірно|абсолютно|фактично|по-справжньому)\b',
        'ru': r'\b(?:очень|действительно|по-настоящему|невероятно|абсолютно|фактически|реально)\b',
        'pl': r'\b(?:bardzo|naprawdę|niezwykle|niesamowicie|absolutnie|faktycznie)\b',
        'en': r'\b(?:really|truly|genuinely|literally|actually|simply|incredibly|absolutely|extremely)\b',
    }),
}

# Абзац починається зі сполучника-розгону («Тож…», «So…»).
CONNECTIVE_OPENERS = {
    'uk': r'^(?:тож|отже|отож|загалом|словом)\b',
    'ru': r'^(?:итак|так что|таким образом|в общем|словом)\b',
    'pl': r'^(?:więc|zatem|podsumowując|krótko mówiąc)\b',
    'en': r'^(?:so|overall|in short|look|basically)\b',
}
# Тире між словами, що з'єднує частини речення (діапазони «10–20» не чіпаються).
_DASH_CLAUSE = re.compile(r'(?<=[^\d\s])\s[–—]\s(?=[^\d\s])')
FRAGMENT_MAX_WORDS = 2
FRAGMENT_RUN = 3
SLOGAN_MAX_WORDS = 4
RHYTHM_MIN_WORDS = 8
RHYTHM_RUN = 3


def _stacked_fragments(text: str) -> bool:
    run = 0
    for sentence in sentences(text):
        run = run + 1 if 0 < len(words(sentence)) <= FRAGMENT_MAX_WORDS else 0
        if run >= FRAGMENT_RUN:
            return True
    return False


def _metronomic(text: str) -> bool:
    lengths = [len(words(s)) for s in sentences(text)]
    for i in range(len(lengths) - RHYTHM_RUN + 1):
        window = lengths[i:i + RHYTHM_RUN]
        if min(window) >= RHYTHM_MIN_WORDS and max(window) - min(window) <= 1:
            return True
    return False


def audit_stop_slop(markup: str, language: str, variant: str = '', product: dict | None = None,
                    brief: dict | None = None) -> list[dict]:
    """Звороти зі stop-slop, яких не ловлять AI_PATTERNS і словники «води» в seo_geo."""
    lang = norm_lang(language)
    doc = parse_fragment(markup)
    findings: list[dict] = []

    def mk(kind: str, severity: str, message: str, item: dict, evidence: str, suggestion: str) -> None:
        findings.append(finding(f'slop_{kind}', severity, message, language=lang, variant=variant, block=item['block'],
                                evidence=evidence, segment=item['key'], suggestion=suggestion, source='human'))

    for kind, (severity, label, suggestion, by_lang) in SLOP_PATTERNS.items():
        pattern = by_lang.get(lang)
        if not pattern:
            continue
        hits = [(m, item) for item in doc['texts'] for m in [re.search(pattern, item['text'], re.I)] if m]
        if hits:
            count = f' ({len(hits)})' if len(hits) > 1 else ''
            mk(kind, severity, label + count, hits[0][1], hits[0][1]['text'], suggestion)

    opener = CONNECTIVE_OPENERS.get(lang)
    item = next((p for p in doc['paragraphs'] if opener and re.search(opener, p['text'], re.I)), None)
    if item:
        mk('connective_opener', 'info', 'Абзац починається зі сполучника-розгону («Тож…», «Отже…»)', item, item['text'],
           'Почати з предмета абзацу')

    item = next((t for t in doc['texts'] if t['tag'] in ('p', 'h2', 'h3', 'li') and _stacked_fragments(t['text'])), None)
    if item:
        mk('stacked_fragments', 'warning', 'Ланцюжок фрагментів («Тихо. Швидко. Точно.»)', item, item['text'],
           'Одне повне речення з конкретним значенням')

    dashed = [p for p in doc['paragraphs'] if _DASH_CLAUSE.search(p['text'])]
    if dashed:
        mk('dash_clause', 'info', f'Тире з\'єднує частини речення ({len(dashed)})', dashed[0], dashed[0]['text'],
           'Кома або крапка замість тире')

    item = next((p for p in doc['paragraphs'] if _metronomic(p['text'])), None)
    if item:
        mk('metronomic_rhythm', 'info', 'Три речення поспіль однакової довжини', item, item['text'],
           'Скоротити одне речення або об\'єднати два')

    entities = _entity_tokens(product, brief)
    faq_blocks = {t['block'] for t in doc['texts'] if t['tag'] == 'summary'}
    last_paragraph: dict = {}
    for p in doc['paragraphs']:
        if p['block'] not in faq_blocks:
            last_paragraph[p['block']] = p
    for p in last_paragraph.values():
        ending = (sentences(p['text']) or [''])[-1]
        tokens = words(ending)
        # Цифра або латиниця (PEI, USB-C) - це факт, а не гасло: «Стіл покрито PEI.»
        if (0 < len(tokens) <= SLOGAN_MAX_WORDS and len(sentences(p['text'])) > 1 and not re.search(r'[\dA-Za-z]', ending)
                and not any(t.lower() in entities for t in tokens)):
            mk('slogan_ending', 'info', 'Блок закінчується короткою фразою-гаслом', p, ending,
               'Закінчити блок останнім конкретним фактом')
            break
    return findings
