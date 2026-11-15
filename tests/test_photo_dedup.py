"""Скарга ARTLINE Master (Growatt AURA 5000): той самий кадр двічі й фото не в масштабі.

Сцена «-30° у снігу» стояла двічі (квадрат галереї й широкий банер з опису), а
квадратні кадри в рамках 3:2 з cover втрачали третину висоти: у пакшота зрізало
верх і ніжки. Тести без мережі: синтетичні кадри в tmp_path.
"""
import re
from unittest.mock import patch

from PIL import Image, ImageDraw

from app import pipeline as P
from app.photo_dedup import difference, is_duplicate, signature, unique_frames
from app.photo_slots import drop_empty_photo_slots


def _scene(width=1200, height=640, seed=0):
    """Синтетична «сцена»: градієнт, підлога, корпус товару, табличка зліва."""
    image = Image.new('RGB', (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        shade = 120 + (y * 90) // height + seed
        draw.line([(0, y), (width, y)], fill=(shade, shade, min(255, shade + 20)))
    draw.rectangle([0, int(height * .8), width, height], fill=(220, 200, 170))
    draw.rectangle([int(width * .4), int(height * .4), int(width * .62), int(height * .88)], fill=(150, 155, 160))
    draw.rectangle([int(width * .1), int(height * .45), int(width * .25), int(height * .75)], fill=(235, 235, 240))
    return image


def _packshot(touch_top=True, angle=0):
    """Студійний кадр на білому: корпус торкається верху, поля з боків білі."""
    image = Image.new('RGB', (1000, 1000), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    top = 0 if touch_top else 80
    draw.rounded_rectangle([90 + angle, top, 910 - angle, 960], radius=60, fill=(160, 164, 166))
    draw.rectangle([140 + angle, top + 60, 860 - angle, top + 160], fill=(40, 40, 40))
    return image


def test_same_scene_with_other_crop_and_size_is_a_duplicate():
    wide = _scene()
    square = wide.crop((300, 0, 940, 640)).resize((2000, 2000))
    assert is_duplicate(signature(wide), signature(square))
    assert is_duplicate(signature(wide), signature(wide.copy())), 'дослівна копія під іншою адресою'


def test_different_frames_are_not_duplicates():
    assert not is_duplicate(signature(_scene()), signature(_packshot()))
    # той самий товар з іншого ракурсу на білому тлі - окремий кадр
    assert difference(signature(_packshot(angle=0)), signature(_packshot(angle=300))) > 16


def test_unique_frames_keeps_first_and_frames_without_signature():
    sigs = {'a': signature(_scene()), 'b': signature(_scene().crop((200, 0, 1000, 640))), 'c': signature(_packshot()), 'd': None}
    assert unique_frames(['a', 'b', 'c', 'd'], sigs.get) == ['a', 'c', 'd']


def _media(tmp_path, name, image):
    path = tmp_path / 'p' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return f'/media/p/{name}'


def _clear_caches():
    for cache in (P._surface_color_cache, P._surface_size_cache, P._surface_signature_cache):
        cache.clear()


def test_packshot_touching_the_top_edge_is_a_studio_frame(tmp_path):
    with patch.object(P.settings, 'media_dir', str(tmp_path)):
        _clear_caches()
        src = _media(tmp_path, 'pack.png', _packshot())
        assert P._probe_media_surface(src) == (True, '#FFFFFF')
        assert not P._is_environment_photo(src), 'пакшот не можна різати cover-ом'
        _clear_caches()


def _split(src: str) -> str:
    return ('<div style="padding:40px;border-radius:14px"><div style="display:grid;grid-template-columns:1fr 1fr;gap:36px">'
            f'<div><div style="width:92%;background:#FFFFFF;border-radius:12px;padding:18px"><img src="{src}" alt="x" style="width:100%"></div></div>'
            '<div><h2>Текст</h2><p>Абзац</p></div></div></div>')


def _img_styles(markup: str) -> list[str]:
    return [re.search(r'style="([^"]*)"', tag).group(1) for tag in re.findall(r'<img[^>]+>', markup)]


def test_split_photo_keeps_its_own_proportions(tmp_path):
    with patch.object(P.settings, 'media_dir', str(tmp_path)):
        _clear_caches()
        square_scene = _media(tmp_path, 'scene.png', _scene(1000, 1000))
        pack = _media(tmp_path, 'pack.png', _packshot())
        banner = _media(tmp_path, 'banner.png', _scene(1880, 1000, seed=30))
        out = P._fit_photo_cards('<section>' + _split(square_scene) + _split(pack) + _split(banner) + '</section>', 'desktop')
        scene_style, pack_style, banner_style = _img_styles(out)
        assert 'aspect-ratio:1;' in scene_style and 'object-fit:cover' in scene_style
        assert 'aspect-ratio:1;' in pack_style and 'object-fit:contain' in pack_style
        assert 'aspect-ratio:1.88' in banner_style and 'object-fit:cover' in banner_style
        assert '3/2' not in out
        assert P._fit_photo_cards(out, 'desktop') == out, 'повторний прохід нічого не змінює'
        # стара сторінка: рамка вже без падінгів, на <img> - 3/2 і cover
        old = out.replace('aspect-ratio:1;object-fit:contain', 'aspect-ratio:3/2;object-fit:cover', 1)
        assert P._fit_photo_cards(old, 'desktop') == out, '«Вирівняти оформлення» виправляє стару сторінку'
        _clear_caches()


def test_row_of_cards_keeps_shared_ratio_but_never_crops_a_real_photo_hard(tmp_path):
    with patch.object(P.settings, 'media_dir', str(tmp_path)):
        _clear_caches()
        square_scene = _media(tmp_path, 'scene.png', _scene(1000, 1000))
        wide_scene = _media(tmp_path, 'wide.png', _scene(1500, 1000, seed=20))
        card = '<div style="border-radius:12px;padding:18px"><img src="{}" alt="x" style="width:100%"></div>'
        row = f'<section><div style="display:grid;grid-template-columns:1fr 1fr">{card.format(square_scene)}{card.format(wide_scene)}</div></section>'
        square_style, wide_style = _img_styles(P._fit_photo_cards(row, 'desktop'))
        assert 'aspect-ratio:3/2' in square_style and 'object-fit:contain' in square_style, 'квадрат у 3:2 - третина висоти, не ріжемо'
        assert 'aspect-ratio:3/2' in wide_style and 'object-fit:cover' in wide_style
        _clear_caches()


def test_repeated_frame_under_another_url_is_removed(tmp_path):
    with patch.object(P.settings, 'media_dir', str(tmp_path)):
        _clear_caches()
        wide = _scene()
        gallery = _media(tmp_path, 'gallery.png', wide.crop((300, 0, 940, 640)).resize((1000, 1000)))
        editor = _media(tmp_path, 'editor.png', wide)
        page = '<section>' + _split(gallery) + _split(editor) + '</section>'
        assert len(_img_styles(drop_empty_photo_slots(page))) == 2, 'без порівняння - лише за src'
        out = drop_empty_photo_slots(page, same_photo=P.same_photo)
        assert gallery in out and editor not in out
        _clear_caches()
