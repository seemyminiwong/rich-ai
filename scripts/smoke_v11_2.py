from pathlib import Path

root = Path(__file__).resolve().parents[1]
pipeline = (root / 'apps/api/app/pipeline.py').read_text(encoding='utf-8')
tasks = (root / 'apps/api/app/tasks.py').read_text(encoding='utf-8')
main = (root / 'apps/api/app/main.py').read_text(encoding='utf-8')
web = (root / 'apps/web/app.js').read_text(encoding='utf-8')
css = (root / 'apps/web/styles.css').read_text(encoding='utf-8')

checks = {
    'reference image edit': 'client.images.edit' in pipeline,
    'no unconstrained image generate in generate_image': 'client.images.generate' not in pipeline[pipeline.index('def generate_image'):pipeline.index('def _html_only')],
    'reference selector': 'choose_product_reference(images)' in tasks,
    'reference metadata': "'reference_url':fallback" in tasks,
    'ARTLINE logo': 'logo-main-header.svg' in web,
    'preview separate window': 'function openPreview' in web and 'URL.createObjectURL' in web,
    'preview auto height': 'function resizePreview' in web and 'onload="resizePreview(this)"' in web,
    'project asset dialog': 'function projectAssets' in web and '<dialog id="assetDetails"></dialog>' in web,
    'review detailed error': 'Не вдалося зберегти рішення перевірки' in main,
    'artifact max version': 'func.max(Artifact.version)' in main,
    'save click guard': 'pendingSave' in web,
    'Ukrainian UI': 'Проєкти' in web and 'Налаштування' in web and 'Користувачі' in web,
    'preview scroll CSS': 'scrollbar-gutter:stable' in css,
}
failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"{'OK' if ok else 'FAIL'}: {name}")
if failed:
    raise SystemExit('Smoke checks failed: ' + ', '.join(failed))
print('Smoke checks OK')
