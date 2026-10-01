#!/usr/bin/env python3
"""Жодного комерційного твердження, зашитого в код.

Гарантія, підтримка 24/7, «швидка доставка», SLA, наявність на складі можуть
з'явитись у тексті ЛИШЕ з Publishing Profile (VERIFIED COMPANY FACTS). Цей
скрипт - CI-запобіжник: він шукає такі фрази у рядкових літералах серверного
коду, які потрапляють у видимий HTML, і падає, якщо знаходить.

Дозволено: словники детекторів (seo_geo.py), промпти-ЗАБОРОНИ («never write
24/7») і докстрінги - вони не є текстом сторінки.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT / 'apps/api/app/landing.py', ROOT / 'apps/api/app/pipeline.py', ROOT / 'apps/api/app/tasks.py',
         ROOT / 'apps/api/app/main.py', ROOT / 'apps/api/app/text_edit.py', ROOT / 'apps/api/app/infographic.py']

# Фрази, які зустрічались у старому fallback-лендінгу, плюс їхні родичі.
CLAIMS = [
    r'Технічна підтримка 24/7', r'Техническая поддержка 24/7', r'Wsparcie techniczne 24/7', r'24/7 support',
    r'Швидка доставка по Україні', r'Быстрая доставка по Украине', r'Szybka dostawa', r'Fast delivery',
    r'Офіційна гарантія', r'Официальная гарантия', r'Oficjalna gwarancja', r'Official warranty',
    r'Безкоштовна доставка', r'Бесплатная доставка', r'Darmowa dostawa', r'Free shipping',
    r'В наявності', r'В наличии', r'Na stanie', r'In stock',
]
# Рядки, де ці фрази допустимі: заборони в промптах, коментарі, докстрінги.
ALLOWED_CONTEXT = re.compile(r'never|forbidden|заборон|не можна|no invented|do not|тут навмисно|жодних|#|"""', re.I)


def main() -> int:
    problems = []
    for path in FILES:
        if not path.exists():
            continue
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
            for claim in CLAIMS:
                if re.search(claim, line, re.I) and not ALLOWED_CONTEXT.search(line):
                    problems.append(f'{path.relative_to(ROOT)}:{number}: {line.strip()[:120]}')
    if problems:
        print('Hardcoded commercial claims found (move them to Publishing Profile):')
        print('\n'.join(problems))
        return 1
    print('No hardcoded commercial claims in server code')
    return 0


if __name__ == '__main__':
    sys.exit(main())
