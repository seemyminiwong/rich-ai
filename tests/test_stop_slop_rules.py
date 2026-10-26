"""Правила stop-slop (github.com/hardikpandya/stop-slop), аудит 2026-10-26.

Звіт: docs/audits/styles-vs-stop-slop.md. До цієї версії перевірки студії не ловили
жодного з 15 типових зворотів; тут кожен закріплено, а чистий текст лишається чистим.
"""
import pytest

from app.landing import build_landing_prompt
from app.pipeline import SLOP_REVISE_BELOW, _slop_scores
from app.prompts import HUMAN_COPY_CONTRACT
from app.stop_slop import audit_stop_slop

PRODUCT = {'name': 'Bambu Lab A1 mini', 'brand': 'Bambu Lab', 'model': 'A1 mini', 'category': '3D-принтери'}


def _codes(text: str, lang: str = 'uk') -> set:
    page = ('<section><div><h2>Bambu Lab A1 mini</h2><p>Принтер Bambu Lab A1 mini друкує деталі до 180 мм.</p></div>'
            f'<div><h2>Друк</h2><p>{text}</p></div></section>')
    return {f['code'] for f in audit_stop_slop(page, lang, product=PRODUCT)}


@pytest.mark.parametrize('code, text', [
    ('slop_throat_clearing', 'Справа в тому, що принтер друкує на швидкості 500 мм/с.'),
    ('slop_emphasis_crutch', 'Принтер калібрує стіл сам. Ось чому це важливо для новачка.'),
    ('slop_intensifier', 'Принтер дуже тихий і справді надійний у роботі щодня.'),
    ('slop_split_contrast', 'Принтер тихий. Не тому, що повільний. Тому що має активне придушення шуму.'),
    ('slop_split_contrast', 'Швидкість принтера не проблема. Проблема в якості пластику.'),
    ('slop_negative_listing', 'Не офісна іграшка. Не конструктор. Це готовий принтер.'),
    ('slop_stacked_fragments', 'Тихо. Швидко. Точно. Принтер працює на столі поруч з вами.'),
    ('slop_false_agency', 'Принтер друкує без налаштувань, а дані підказують температуру.'),
    ('slop_connective_opener', 'Тож принтер підійде для першого знайомства з 3D-друком.'),
    ('slop_lazy_extreme', 'Принтер завжди готовий до роботи і підходить для будь-яких задач.'),
    ('slop_vague_declarative', 'Принтер друкує 500 мм/с. Різниця відчутна.'),
    ('slop_slogan_ending', 'Принтер друкує 500 мм/с на столі 180 мм. Друк без компромісів.'),
    ('slop_dash_clause', 'Принтер друкує 500 мм/с – це помітно швидше за попередню модель.'),
    ('slop_metronomic_rhythm', 'Принтер має робочу зону для невеликих домашніх деталей щодня. '
                               'Датчик вимірює тиск пластику у соплі під час друку. '
                               'Сопло знімається рукою за кілька секунд без жодних інструментів.'),
])
def test_ukrainian_slop_is_flagged(code, text):
    assert code in _codes(text), text


@pytest.mark.parametrize('lang, code, text', [
    ('ru', 'slop_throat_clearing', 'Дело в том, что принтер печатает на скорости 500 мм/с.'),
    ('ru', 'slop_split_contrast', 'Принтер тихий. Не потому, что медленный. Потому что двигатели гасят шум.'),
    ('pl', 'slop_lazy_extreme', 'Drukarka zawsze jest gotowa do pracy i pasuje do dowolnych zadań.'),
    ('en', 'slop_throat_clearing', "Here's the thing: the printer prints at 500 mm/s."),
    ('en', 'slop_intensifier', 'The printer is really quiet and truly reliable every day.'),
])
def test_other_languages(lang, code, text):
    assert code in _codes(text, lang), text


def test_clean_product_copy_is_not_flagged():
    page = ('<section><div><h2>Bambu Lab A1 mini</h2><p>Bambu Lab A1 mini - компактний 3D-принтер для дому з робочою зоною 180 × 180 × 180 мм.</p></div>'
            '<div><h2>Тихий друк уночі</h2><p>Принтер працює з рівнем шуму до 48 дБ у тихому режимі. Двигуни мають активне '
            'придушення шуму, тому друк можна залишити на ніч у кімнаті.</p></div>'
            '<div><h2>Сопло без інструментів</h2><p>Сопло 0,4 мм знімається рукою за кілька секунд. Кожен порт підписано на корпусі. '
            'Стіл покрито PEI.</p></div>'
            '<div><h3>Чи потрібне калібрування?</h3><p>Калібрування столу автоматичне: датчик вимірює висоту в 49 точках перед друком. '
            'Температура сопла - 180–300 °C.</p></div></section>')
    assert audit_stop_slop(page, 'uk', product=PRODUCT) == []


def test_copy_contract_carries_stop_slop_rules():
    for rule in ('No throat-clearing', 'No split contrasts', 'No lazy extremes', 'No vague declaratives',
                 'human verbs only to people', 'connective filler', 'No stacked fragments', 'never with a dash',
                 'three sentences in a row of the same length', 'hunting AI tells'):
        assert rule in HUMAN_COPY_CONTRACT, rule


def test_landing_prompt_gets_the_copy_contract():
    prompt = build_landing_prompt({'name': 'Тиждень SSD', 'language': 'ua'}, [{'name': 'SSD', 'url': 'https://artline.ua/p/1'}])
    assert 'HUMAN COPY CONTRACT' in prompt and 'No lazy extremes' in prompt


def test_llm_slop_scores():
    assert _slop_scores({'directness': 8, 'rhythm': 7, 'trust': 9, 'authenticity': 8, 'density': 7})['total'] == 39
    low = _slop_scores({'directness': 5, 'rhythm': 6, 'trust': 7, 'authenticity': 6, 'density': 5})
    assert low['total'] == 29 and low['total'] < SLOP_REVISE_BELOW
    assert _slop_scores({'directness': 8}) is None and _slop_scores('n/a') is None, 'неповна шкала - без вигаданих балів'
    assert _slop_scores({k: 15 for k in ('directness', 'rhythm', 'trust', 'authenticity', 'density')})['total'] == 50
