"""Markdown-звіт про проблеми проєкту: швидка дефектовка однією кнопкою.

Один файл, який можна вставити в задачу, чат або Git issue: що за проєкт і
версії, чи заблоковано схвалення і чому, оцінки перевірок, і кожна знахідка
окремим дефектом з ідентифікатором D-NN, місцем (мова / формат / блок /
фрагмент редактора), цитатою, причиною, порадою і станом. Плюс свіжий аналіз
радіусів поточних версій, аварійні шаблони і останні помилки з журналу.

Звіт будується з того, що вже збережено (звіти критиків, рішення рецензента,
журнал), і з поточного HTML версій - без AI, без мережі, без витрат.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.seo_geo import SEVERITIES, finding_to_text

CRITIC_LABELS = {
    'facts': 'Фактологія', 'html': 'HTML-структура', 'human': 'Людський текст', 'marketing': 'Маркетинг',
    'seo': 'SEO', 'geo': 'GEO', 'language': 'Мова', 'accessibility': 'Доступність', 'render': 'Верстка у браузері',
    'llm': 'AI-рецензент',
}
SEVERITY_LABELS = {'critical': 'КРИТИЧНО', 'warning': 'увага', 'info': 'інфо'}
STATE_LABELS = {'open': 'відкрито', 'resolved': 'виправлено', 'accepted': 'прийнято'}
LANG_LABELS = {'ua': 'UA', 'uk': 'UA', 'ru': 'RU', 'pl': 'PL', 'en': 'EN'}


def _cell(value) -> str:
    """Безпечний вміст клітинки Markdown-таблиці."""
    text = ' '.join(str(value if value is not None else '').split())
    return text.replace('|', '\\|') or '—'


def _quote(value: str) -> str:
    return ' '.join(str(value or '').split()).replace('`', "'")


def _where(row: dict) -> str:
    parts = []
    if row.get('language'):
        parts.append(LANG_LABELS.get(row['language'], str(row['language']).upper()))
    variants = [v for v in (row.get('_variants') or [row.get('variant')]) if v]
    if variants:
        parts.append(' + '.join({'desktop': 'десктоп', 'mobile': 'мобільна'}.get(v, v) for v in variants))
    if isinstance(row.get('block'), int):
        parts.append(f'блок {row["block"] + 1}')
    return ' · '.join(parts) or 'уся сторінка'


def _rows(critics: list[dict]) -> list[tuple[dict, dict]]:
    """(звіт, знахідка) для всіх критиків; старі звіти без findings - з рядків."""
    out = []
    for report in critics:
        findings = report.get('findings') or []
        if not findings:
            for index, text in enumerate(report.get('issues') or []):
                findings.append({'key': f'legacy:{report.get("type")}:{index}', 'code': f'{report.get("type")}_issue',
                                 'severity': 'info' if report.get('type') == 'marketing' else 'warning',
                                 'message': str(text), 'evidence': '', 'suggestion': '', 'language': '', 'variant': '', 'block': None})
        for row in findings:
            out.append((report, row))
    # Та сама знахідка на десктопі й мобільній - один дефект: виправляється
    # однаково, а подвоєний список лише заважає дефектовці.
    merged: dict = {}
    for report, row in out:
        key = (report.get('type'), row.get('code'), row.get('language'), row.get('block'), row.get('message'), row.get('evidence'))
        if key in merged:
            first = merged[key][1]
            variants = first.setdefault('_variants', [first.get('variant')])
            if row.get('variant') not in variants:
                variants.append(row.get('variant'))
            first.setdefault('_keys', [first.get('key')]).append(row.get('key'))
            continue
        merged[key] = (report, dict(row))
    out = list(merged.values())
    order = {s: i for i, s in enumerate(SEVERITIES)}
    out.sort(key=lambda pair: (order.get(pair[1].get('severity'), 9), pair[0].get('type') or '', pair[1].get('language') or '',
                               pair[1].get('variant') or '', pair[1].get('block') if isinstance(pair[1].get('block'), int) else 99))
    return out


def build_problem_report(project: dict, *, critics: list[dict], decisions: dict, blockers: list[str], artifacts: list,
                         events: list[dict] | None = None, radius: dict | None = None, studio_url: str = '',
                         version: str = '') -> str:
    """Markdown для дефектовки. project - project_dict(full=False); artifacts - свіжі версії."""
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    rows = _rows(critics)
    def state_of(row: dict) -> str:
        # Склеєний дефект відкритий, доки відкрита хоч одна з його копій.
        states = [(decisions.get(k) or {}).get('state') or 'open' for k in (row.get('_keys') or [row.get('key')])]
        return 'open' if 'open' in states else ('accepted' if 'accepted' in states else states[0])
    open_rows = [(r, f) for r, f in rows if state_of(f) == 'open']
    counts = {s: sum(1 for _, f in open_rows if f.get('severity') == s) for s in SEVERITIES}
    lines = [f'# Дефекти: {project.get("name") or "проєкт"}', '']
    link = f'{studio_url.rstrip("/")}/projects/{project.get("id")}' if studio_url else ''
    lines += [
        f'- **Проєкт:** `{project.get("id")}`' + (f' · [відкрити в студії]({link})' if link else ''),
        f'- **Товар:** {project.get("source_url") or "—"}',
        f'- **Статус:** {project.get("status")} · стиль {project.get("style_name") or "—"} · артикул {project.get("sku") or "—"} · категорія {project.get("product_category") or "—"}',
        f'- **Мови / формати:** {", ".join(project.get("languages") or [])} / {", ".join(project.get("variants") or [])} · прогін {project.get("run_index") or 1}',
        '- **Версії:** ' + (', '.join(f'{LANG_LABELS.get(a.language, a.language.upper())} {a.variant} v{a.version}' + (' ⚠ аварійний шаблон' if getattr(a, 'fallback_reason', '') else '')
                                      for a in sorted(artifacts, key=lambda a: (a.language, a.variant))) or '—'),
        f'- **Звіт сформовано:** {now}' + (f' · студія v{version}' if version else ''),
        '',
        '## Підсумок',
        '',
        f'**Схвалення: {"ЗАБЛОКОВАНО" if blockers else "можливе"}.** Відкритих дефектів: критичних {counts["critical"]}, попереджень {counts["warning"]}, інфо {counts["info"]} (усього {len(rows)}; однакові знахідки десктопа й мобільної склеєно).',
        '',
    ]
    if blockers:
        lines += ['### Що блокує схвалення', ''] + [f'- {_quote(b)}' for b in blockers] + ['']
    if critics:
        lines += ['### Оцінки перевірок', '', '| Перевірка | Оцінка | Критичних | Попереджень | Підсумок |', '|---|---:|---:|---:|---|']
        for report in sorted(critics, key=lambda r: r.get('score') or 0):
            findings = [f for r, f in rows if r is report]
            lines.append(f'| {_cell(CRITIC_LABELS.get(report.get("type"), report.get("type")))} | {round(float(report.get("score") or 0))} | '
                         f'{sum(1 for f in findings if f.get("severity") == "critical")} | {sum(1 for f in findings if f.get("severity") == "warning")} | '
                         f'{_cell((report.get("summary") or "")[:140])} |')
        lines.append('')
    if rows:
        lines += ['## Список дефектів', '', '| ID | Рівень | Перевірка | Де | Проблема | Стан |', '|---|---|---|---|---|---|']
        for index, (report, row) in enumerate(rows, start=1):
            lines.append(f'| D-{index:02d} | {SEVERITY_LABELS.get(row.get("severity"), row.get("severity"))} | '
                         f'{_cell(CRITIC_LABELS.get(report.get("type"), report.get("type")))} | {_cell(_where(row))} | '
                         f'{_cell((row.get("message") or "")[:120])} | {STATE_LABELS.get(state_of(row), state_of(row))} |')
        lines += ['', '## Деталі', '']
        for index, (report, row) in enumerate(rows, start=1):
            decision = next((decisions[k] for k in (row.get('_keys') or [row.get('key')]) if k in decisions), {})
            lines.append(f'### D-{index:02d} · {SEVERITY_LABELS.get(row.get("severity"), row.get("severity"))} · '
                         f'{CRITIC_LABELS.get(report.get("type"), report.get("type"))} · {_where(row)}')
            lines.append('')
            lines.append(f'- [{"x" if state_of(row) != "open" else " "}] **{_quote(row.get("message"))}**')
            if row.get('evidence'):
                lines.append(f'- Цитата: «{_quote(row["evidence"])}»')
            if row.get('suggestion'):
                lines.append(f'- Як виправити: {_quote(row["suggestion"])}')
            meta = [f'код `{row.get("code")}`']
            if row.get('segment'):
                meta.append(f'фрагмент редактора `{row["segment"]}` (Текст → Редагування)')
            if row.get('key') and not str(row['key']).startswith('legacy:'):
                meta.append(f'ключ `{row["key"]}`')
            lines.append('- ' + ' · '.join(meta))
            if decision.get('state') and decision.get('state') != 'open':
                lines.append(f'- Рішення: {STATE_LABELS.get(decision["state"], decision["state"])}' + (f' - {_quote(decision.get("comment"))}' if decision.get('comment') else ''))
            lines.append('')
    else:
        lines += ['## Список дефектів', '', 'Знахідок немає - перевірки ще не запускались або все чисто.', '']
    if radius:
        lines += ['## Радіуси поточних версій', '']
        if not any(radius.values()):
            lines.append('Усі радіуси відповідають стандарту ARTLINE (зовнішні 14px, внутрішні 10-12px, лейбли й чипи 8px, з урахуванням масштабу схеми).')
        for label, deviations in radius.items():
            if deviations:
                lines.append(f'**{label}** - поза стандартом: {len(deviations)}')
                lines += [f'- {_quote(d)}' for d in deviations[:20]]
                if len(deviations) > 20:
                    lines.append(f'- …та ще {len(deviations) - 20}')
                lines.append('')
        lines.append('')
    fallbacks = [a for a in artifacts if getattr(a, 'fallback_reason', '')]
    if fallbacks:
        lines += ['## Аварійний шаблон замість стилю', ''] + [
            f'- {LANG_LABELS.get(a.language, a.language)} {a.variant} v{a.version}: {_quote(a.fallback_reason)}' for a in fallbacks] + ['']
    problems = [e for e in (events or []) if e.get('level') in ('error', 'warning')][:15]
    if problems:
        lines += ['## Журнал: попередження й помилки', '', '| Час | Рівень | Етап | Повідомлення |', '|---|---|---|---|']
        for event in problems:
            when = event.get('created_at')
            when = when.strftime('%Y-%m-%d %H:%M') if hasattr(when, 'strftime') else str(when or '')[:16]
            lines.append(f'| {_cell(when)} | {_cell(event.get("level"))} | {_cell(event.get("stage"))} | {_cell((event.get("message") or "")[:200])} |')
        lines.append('')
    lines += ['---', '', '_Детерміновані перевірки підсвічують ризики і не гарантують позицій у пошуку чи цитування в AI-відповідях. '
              'Критичні знахідки блокують схвалення; попередження приймаються з коментарем._', '']
    return '\n'.join(lines)


__all__ = ['build_problem_report', 'finding_to_text']
