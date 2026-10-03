"""FAQ і все, що схоже на кнопку, не виділяється кліком (рішення власника 2026-10-03)."""
import re

from app.artline_standard import apply_artline_standard
from app.pipeline import _standard_for, finalize_faq_html


def _decl(style: str, prop: str) -> str:
    match = re.search(r'(?<![-\w])' + re.escape(prop) + r'\s*:\s*([^;]+)', style or '')
    return match.group(1).strip() if match else ''


def test_every_managed_style_prompt_asks_for_user_select_none():
    from app.main import MANAGED_STYLES
    assert MANAGED_STYLES
    for spec in MANAGED_STYLES:
        prompt = spec['values']['prompt']
        full = prompt + _standard_for(prompt)
        assert 'user-select:none;-webkit-user-select:none' in full, spec['name']
        assert 'Non-selectable controls' in full, spec['name']
        # Явні специфікації summary в промптах теж містять правило.
        for line in re.findall(r'[^\n]*cursor:pointer[^\n]*', full):
            if 'summary' in line.lower():
                assert 'user-select:none' in line, (spec['name'], line[:120])


def test_faq_summary_gets_user_select_none_and_answers_stay_selectable():
    markup = ('<section><div><details><summary style="padding:20px 2px;font-size:17px">Чи є HDR?</summary>'
              '<p style="margin:0">Так, HDR10.</p></details></div></section>')
    out = finalize_faq_html(markup)
    summary = re.search(r'<summary style="([^"]*)"', out).group(1)
    assert _decl(summary, 'user-select') == 'none' and _decl(summary, '-webkit-user-select') == 'none'
    assert 'user-select' not in re.search(r'<p style="([^"]*)"', out).group(1)
    assert finalize_faq_html(out) == out  # ідемпотентно


def test_badges_and_chips_get_user_select_none_but_text_does_not():
    markup = ('<section style="width:100%"><div style="background:#1A2128;border-radius:14px;padding:40px">'
              '<span style="display:inline-flex;padding:6px 14px;border:1px solid #19BCC9;border-radius:999px">QUBE · Монітор</span>'
              '<h2 style="font-size:30px">QUBE Overlord</h2>'
              '<p style="font-size:16px;color:#D8DDE2">Опис товару.</p>'
              '<span style="display:inline-block;padding:4px 10px;background:#FFFFFF;border-radius:8px;user-select:text">240 Гц</span>'
              '</div></section>')
    out = apply_artline_standard(markup)
    spans = re.findall(r'<span style="([^"]*)"', out)
    assert len(spans) == 2
    for style in spans:
        assert _decl(style, 'user-select') == 'none' and _decl(style, '-webkit-user-select') == 'none'
        assert _decl(style, 'border-radius') == '8px'
    for tag in ('h2', 'p'):
        assert 'user-select' not in re.search(rf'<{tag} style="([^"]*)"', out).group(1)
    assert apply_artline_standard(out) == out  # ідемпотентно


def test_qube_brand_preset_comes_from_qube_ua_and_is_detected():
    """Палітра QUBE за сайтом qube.ua (2026-10-03): акцент #2BC8F1, логотип там білий."""
    from app.brand_detect import detect_brand
    from app.brand_palettes import BRAND_ACCENTS
    from app.main import BUILTIN_PALETTES
    assert dict(BRAND_ACCENTS)['QUBE'] == '#2BC8F1'
    tokens = dict(BUILTIN_PALETTES)['QUBE']
    assert set(tokens) >= {'accent', 'dark', 'dark_soft', 'light_soft'}
    known = [name for name, _ in BUILTIN_PALETTES]
    found = detect_brand(known, name='Монітор QUBE Overlord G25F240S', url='https://artline.ua/uk/product/monitor-qube-overlord-g25f240s')
    assert found['brand'] == 'QUBE' or found.get('preset') == 'QUBE', found
