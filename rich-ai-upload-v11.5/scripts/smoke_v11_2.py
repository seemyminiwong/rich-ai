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
    'reference selector': 'inspect_product_references(images, raw_primary)' in tasks,
    'no fragile 20KB cutoff': '20_000' not in pipeline,
    'local verified reference': 'materialize_product_reference' in tasks and 'product-reference.png' in pipeline,
    'reference passed to image edit': 'reference_path=reference_path' in tasks,
    'reference metadata': "'reference_url':original_reference_url" in tasks,
    'ARTLINE logo': 'logo-main-header.svg' in web,
    'preview separate window': "window.open('about:blank','_blank')" in web,
    'preview internal scroll': 'scrolling="yes"' in web,
    'polling preserves preview': "['preview','html'].includes(state.tab)" in web,
    'sorting handles compound fields': "lastIndexOf('_')" in web,
    'project asset dialog': 'function projectAssets' in web and '<dialog id="assetDetails"></dialog>' in web,
    'review detailed error': 'Не вдалося зберегти рішення перевірки' in main,
    'artifact max version': 'func.max(Artifact.version)' in main,
    'no H1 in rich content': '<h1 style=' not in pipeline and 'never use <h1>' in pipeline and 'Keep one semantic H1' not in pipeline,
    'database startup lock': 'pg_advisory_xact_lock' in (root / 'apps/api/app/db.py').read_text(encoding='utf-8'),
    'database init not at import': 'with engine.begin() as connection' not in (root / 'apps/api/app/db.py').read_text(encoding='utf-8').split('def ensure_schema')[0],
    'save click guard': 'pendingSave' in web,
    'Ukrainian UI': 'Проєкти' in web and 'Налаштування' in web and 'Користувачі' in web,
    'preview scroll CSS': 'scrollbar-gutter:stable' in css,
    'shared language layout': 'translate_html(master_html, language' in tasks and 'text-node-only translation' in tasks,
    'separate hero sizes': "'desktop': ('1536x1024'" in tasks and "'mobile': ('1024x1536'" in tasks,
    'project list view': "projectView:localStorage.getItem('projectView')" in web and 'list-view' in css,
    'light preview canvas': 'preview-stage' in web and '.preview-stage' in css and '.code{background:#fff' in css,
}
failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"{'OK' if ok else 'FAIL'}: {name}")
if failed:
    raise SystemExit('Smoke checks failed: ' + ', '.join(failed))
print('Smoke checks OK')
