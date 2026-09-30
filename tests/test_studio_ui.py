"""Інваріанти інтерфейсу студії: дизайн-токени, рух, доступність, ізоляція превʼю.

Це статичні перевірки файлів фронтенду - швидкі й без браузера. Поведінку в
справжньому Chromium перевіряє tests/e2e/test_studio_flow.py.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'apps' / 'web'


def _css():
    return (WEB / 'styles.css').read_text(encoding='utf-8')


def _js():
    return (WEB / 'app.js').read_text(encoding='utf-8')


def _ui():
    return (WEB / 'ui.js').read_text(encoding='utf-8')


def _body(js, name):
    """Текст функції від оголошення до наступного оголошення верхнього рівня."""
    start = js.index(f'function {name}(')
    ends = [i for i in (js.find('\nfunction ', start + 1), js.find('\nasync function ', start + 1)) if i > 0]
    return js[start:min(ends)]


def test_design_tokens_are_defined_once_and_used():
    css = _css()
    root = css.split(':root{', 1)[1].split('}', 1)[0]
    for token in ('--color-brand:#19BCC9', '--color-ink:#101010', '--color-bg:', '--color-surface:',
                  '--color-text:', '--color-text-secondary:', '--color-border:', '--color-success:',
                  '--color-warning:', '--color-danger:', '--color-info:', '--radius-control:',
                  '--radius-card:8px', '--radius-dialog:', '--radius-pill:999px', '--shadow-panel:',
                  '--shadow-dialog:', '--motion-fast:', '--motion-base:', '--motion-slow:'):
        assert token in root, token
    assert css.count('--color-brand:') == 1 and css.count('--radius-card:') == 1, 'один набір токенів'
    # Montserrat - фірмова основа і для самого інтерфейсу
    assert "--font-sans:'Montserrat'" in root
    assert 'href="/fonts/montserrat.css"' in (WEB / 'index.html').read_text(encoding='utf-8')


def test_radii_come_from_the_token_scale():
    css = _css()
    # поза токенами допустимі лише дрібні технічні радіуси (<=6px) і коло 50%
    stray = [v for v in re.findall(r'border-radius:\s*(\d+)px', css) if int(v) > 6]
    assert not stray, f'радіуси поза токенами: {sorted(set(stray))}'
    # звичайні кнопки не бувають «пігулками»
    btn = css.split('\n.btn{', 1)[1].split('}', 1)[0]
    assert 'var(--radius-control)' in btn and '999' not in btn


def test_one_colour_per_meaning_no_second_blue_accent():
    css = _css()
    assert '#0000EE' not in css and 'var(--blue)' not in css, 'синій як другий фірмовий акцент'
    # основна кнопка - фірмовий циан, небезпечна - червоний контур
    primary = css.split('.btn.primary{', 1)[1].split('}', 1)[0]
    assert 'var(--color-brand)' in primary
    danger = css.split('.btn.danger{', 1)[1].split('}', 1)[0]
    assert 'var(--color-danger' in danger


def test_motion_explains_state_and_respects_reduced_motion():
    css = _css()
    rm = css.split('@media (prefers-reduced-motion: reduce){', 1)[1]
    assert 'animation-duration:.01ms!important' in rm and 'transition-duration:.01ms!important' in rm
    assert 'animation-iteration-count:1!important' in rm
    # нескінченні анімації - лише для активного стану (генерація, завантаження)
    infinite = re.findall(r'([^{}]+)\{[^{}]*animation:[^;{}]*infinite', css)
    allowed = ('.progress.run', '.badge.processing', '.live-card.run', '.boot-spinner')
    for selector in infinite:
        assert any(a in selector for a in allowed), f'декоративний цикл: {selector.strip()}'
    assert 'tlScroll' not in css, 'бігучий рядок технологій прибрано'
    # піксельне поле - тільки на екрані входу
    js = _js()
    assert js.count('startPixelField(document.querySelector') == 1
    assert "startPixelField(document.querySelector('.auth .pixel-bg'))" in js


def test_generated_content_stays_isolated_from_studio_css():
    js = _js()
    # кожне превʼю - iframe srcdoc без скриптів: стилі панелі туди не потрапляють
    frames = re.findall(r'<iframe [^>]*>', js)
    assert frames and all('srcdoc=' in f for f in frames)
    assert all('sandbox="allow-same-origin"' in f for f in frames)
    assert 'allow-scripts' not in js
    css = _css()
    # жодних правил, що стилізують вміст iframe або глобальні теги поза панеллю
    assert 'iframe *' not in css
    # документ превʼю має власний скидання стилів і шрифт сайту
    doc = _body(js, 'previewDocument')
    assert '<style>html,body{margin:0' in doc and 'SITE_FONT_LINK()' in doc


def test_dialogs_menus_and_icons_are_accessible():
    js, ui = _js(), _ui()
    # закриття кожного діалогу підписане
    assert js.count('aria-label="Закрити"') + js.count('aria-label="Прибрати') == js.count('>×</button>')
    # фокус повертається до кнопки, що відкрила діалог, навіть після перемальовки
    assert 'proto.showModal=function' in ui and 'restoreFocus' in ui
    # меню «⋯»: підпис, стан, клавіатура
    assert 'aria-haspopup="menu"' in ui and "aria-expanded" in ui and "e.key==='ArrowDown'" in ui
    # іконки декоративні, якщо не мають власного підпису
    assert 'aria-hidden="true" focusable="false"' in ui
    # статуси генерації оголошуються один раз
    assert 'function announce(' in ui and "setAttribute('aria-live','polite')" in ui
    assert 'function announceProject' in js
    # прогрес доступний
    assert 'role="progressbar"' in js and 'aria-valuenow' in js
    # таблиці мають заголовки колонок і підпис
    assert js.count('scope="col"') >= 20 and '<caption class="sr-only">' in js
    # фокус видно
    assert ':focus-visible{' in _css()


def test_status_is_never_colour_only():
    css = _css()
    # кожен статус має текст і свою форму маркера
    for s in ('processing', 'queued', 'review', 'error', 'changes_requested', 'paused', 'draft'):
        assert f'.badge.{s}' in css, s
    js = _js()
    assert "function badge(s){return `<span class=\"badge ${s}\">${STATUS[s]||s}</span>`}" in js
    # оцінки критиків - словом і значком, а не лише кольором
    assert "['ok','Добре','ok']" in js and "['warn','Увага','alert']" in js and "['bad','Проблема','bad']" in js


def test_navigation_is_grouped_and_collapsible():
    js, ui = _js(), _ui()
    assert "const NAV_GROUPS=[['Робота'" in js and "['Бібліотека'" in js and "['Управління'" in js
    assert "localStorage.setItem('sidebarCollapsed'" in ui
    assert 'function openDrawer' in ui and 'function closeDrawer' in ui
    assert 'aria-current="page"' in js


def test_one_primary_action_per_workspace_screen():
    js = _js()
    ws = _body(js, 'workspace')
    # кнопка наступного кроку стає вторинною на вкладках із власною головною дією
    assert 'TABS_WITH_PRIMARY.has(state.tab)' in ws
    assert "const TABS_WITH_PRIMARY=new Set(['html','text','links','info','review'])" in js
    # рішення рев'ю оформлені по-різному: схвалити - primary, запит змін - danger
    review = _body(js, 'reviewTab')
    assert 'id="reviewApproveBtn" class="btn primary"' in review
    assert 'id="reviewChangesBtn" class="btn danger"' in review
    # у рядку таблиці проєктів одна кнопка, решта - у меню
    row = _body(js, 'projectRow')
    assert row.count('class="btn ') == 1 and 'projectRowMenu(p)' in row


def test_new_project_is_a_wizard_that_keeps_the_same_form():
    js = _js()
    dialog = _body(js, 'projectDialog')
    for step in range(1, 5):
        assert f'sec({step})' in dialog
    assert "WIZ_STEPS=['Джерело','Товар і медіа','Результат','Перевірка і запуск']" in js
    # одна форма: createProject читає ту саму FormData
    assert 'onsubmit="wizardSubmit(event)"' in dialog and 'createProject(e)' in _body(js, 'wizardSubmit')
    # режими Простий/Розширений лишаються на кроці «Результат»
    assert "wizardGo(state.wizStep||3,false)" in js
    # на мобільному майстер - повноекранний
    assert 'dialog,dialog.wizard' in _css() and 'height:100dvh' in _css()


def test_managed_styles_are_protected_in_the_ui():
    js = _js()
    assert 'function styleLocked(s)' in js and "fieldset class=\"form-lock\" ${locked?'disabled':''}" in js
    unlock = _body(js, 'unlockStyle')
    assert "can('style.manage')" in unlock and 'confirm(' in unlock


def test_frontend_files_ship_in_the_image_in_order():
    index = (WEB / 'index.html').read_text(encoding='utf-8')
    assert index.index('/ui.js?b=') < index.index('/app.js?b=')
    b = set(re.findall(r'/(?:styles\.css|ui\.js|app\.js)\?b=(\d+)', index))
    assert len(b) == 1, 'ui.js, app.js і styles.css мають спільний cache-buster'
    docker = (WEB / 'Dockerfile').read_text(encoding='utf-8')
    for name in ('ui.js', 'app.js', 'styles.css', 'artline-logo.svg'):
        assert f'COPY {name} ' in docker, name


def test_project_cards_keep_actions_inside_and_rows_aligned():
    css, js = _css(), _js()
    card = _body(js, 'projectCard')
    # властивості - сітка «підпис / значення» в один рядок, а не потік тегів
    assert '<dl class="project-props">' in card and 'project-style' not in card
    assert '.project-props dd{' in css and 'text-overflow:ellipsis' in css.split('.project-props dd{', 1)[1].split('}', 1)[0]
    # власник поступається місцем: вартість і дії завжди видно повністю
    assert '.project-meta .project-who{flex:1 1 auto;min-width:0' in css
    assert '.project-meta .row-actions{flex:none}' in css and '.project-meta .project-cost{flex:none' in css
    # етап завершеного проєкту - за статусом, а не «Опрацювання»
    assert 'stageLabel(p)' in card


def test_style_demo_and_ab_are_fitted_canvases():
    js = _js()
    editor = _body(js, 'styleEditor')
    assert 'data-zoom="fit"' in editor and 'data-w="${state.stylePreviewVariant===' in editor
    assert _body(js, 'abPanel').count('data-zoom="fit"') == 2
    assert "const mode=c.dataset.zoom||state.previewZoom" in _body(js, 'applyPreviewZoom')


def test_text_tab_edits_the_rich_page():
    js = _js()
    editor = _body(js, 'textEditor')
    assert 'saveSegments(this)' in editor and editor.count('class="btn primary"') == 1
    save = _body(js, 'saveSegments')
    assert "/segments`,{method:'PUT'" in save and 'refreshSelected()' in save
    # незбережені правки не губляться мовчки при перемиканні версії
    assert 'Незбережені правки тексту' in _body(js, 'selectArtifact')
