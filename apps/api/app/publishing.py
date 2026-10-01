"""Publishing Profile: перевірені факти компанії для публічних сторінок.

Один шлях читання для API і воркера: профіль з БД -> dict тієї самої форми,
що й ``seo_geo.DEFAULT_PUBLISHING_PROFILE``. Проєкт і лендінг зберігають
ЗНІМОК (``profile_snapshot``), тому пізніша правка профілю не змінює вже
затверджений артефакт.
"""
import json

from sqlalchemy import select

from app.models import PublishingProfile
from app.seo_geo import DEFAULT_PUBLISHING_PROFILE, profile_snapshot

_LIST_FIELDS = ('domains', 'markets', 'languages', 'approved_contacts', 'delivery_geography')
_DICT_FIELDS = ('verified_facts', 'statements', 'warranty_text', 'service_text')


def _load(raw: str, fallback):
    try:
        value = json.loads(raw or '')
        return value if isinstance(value, type(fallback)) else fallback
    except Exception:
        return fallback


def profile_to_dict(row: PublishingProfile | None) -> dict:
    if row is None:
        return dict(DEFAULT_PUBLISHING_PROFILE)
    return {
        'id': row.id,
        'name': row.name,
        'domains': _load(row.domains_json, []),
        'organization_name': row.organization_name or '',
        'organization_url': row.organization_url or '',
        'logo_url': row.logo_url or '',
        'primary_site': bool(row.primary_site),
        'markets': _load(row.markets_json, []),
        'languages': _load(row.languages_json, []),
        'verified_facts': _load(row.verified_facts_json, {}),
        'statements': _load(row.statements_json, {}),
        'approved_contacts': _load(row.approved_contacts_json, []),
        'delivery_geography': _load(row.delivery_geography_json, []),
        'warranty_text': _load(row.warranty_text_json, {}),
        'service_text': _load(row.service_text_json, {}),
        'is_default': bool(row.is_default),
        'version': int(row.version or 1),
        'updated_by': row.updated_by or '',
        'updated_at': row.updated_at,
        'created_at': row.created_at,
    }


def apply_profile_payload(row: PublishingProfile, data: dict, user_email: str = '') -> None:
    """Записати поля з API-payload у рядок; версія зростає на кожну зміну."""
    if 'name' in data and str(data['name']).strip():
        row.name = str(data['name']).strip()[:120]
    for key in ('organization_name', 'organization_url', 'logo_url'):
        if key in data:
            setattr(row, key, str(data.get(key) or '').strip()[:2000])
    if 'primary_site' in data:
        row.primary_site = bool(data['primary_site'])
    for key in _LIST_FIELDS:
        if key in data:
            values = data[key]
            if isinstance(values, str):
                values = [v.strip() for v in values.replace('\n', ',').split(',') if v.strip()]
            setattr(row, f'{key}_json', json.dumps([str(v)[:200] for v in (values or [])][:50], ensure_ascii=False))
    for key in _DICT_FIELDS:
        if key in data:
            value = data[key] if isinstance(data[key], dict) else {}
            setattr(row, f'{key}_json', json.dumps(value, ensure_ascii=False)[:20000])
    row.version = int(row.version or 1) + 1
    row.updated_by = user_email or row.updated_by


def default_profile(db) -> dict:
    """Профіль за замовчуванням із БД, або вбудований ARTLINE, якщо таблиця порожня."""
    row = db.scalar(select(PublishingProfile).where(PublishingProfile.is_default == True))  # noqa: E712
    if row is None:
        row = db.scalar(select(PublishingProfile).order_by(PublishingProfile.created_at).limit(1))
    return profile_to_dict(row)


def profile_by_id(db, profile_id: str | None) -> dict:
    if profile_id:
        row = db.get(PublishingProfile, profile_id)
        if row is not None:
            return profile_to_dict(row)
    return default_profile(db)


def snapshot_for(db, profile_id: str | None = None) -> str:
    """JSON-знімок профілю для збереження в проєкті або лендінгу."""
    snap = profile_snapshot(profile_by_id(db, profile_id))
    for key in ('updated_at', 'created_at'):
        snap.pop(key, None)
    return json.dumps(snap, ensure_ascii=False)


def seed_default_profile(db) -> None:
    """Перший запуск: ARTLINE-профіль з єдиним підтвердженим фактом - постачання
    по Україні та Польщі. Наявні профілі не чіпаються."""
    if db.scalar(select(PublishingProfile.id).limit(1)):
        return
    base = DEFAULT_PUBLISHING_PROFILE
    db.add(PublishingProfile(
        name=base['name'], domains_json=json.dumps(base['domains']), organization_name=base['organization_name'],
        organization_url=base['organization_url'], logo_url=base['logo_url'], primary_site=base['primary_site'],
        markets_json=json.dumps(base['markets']), languages_json=json.dumps(base['languages']),
        verified_facts_json=json.dumps(base['verified_facts'], ensure_ascii=False),
        statements_json=json.dumps(base['statements'], ensure_ascii=False),
        approved_contacts_json='[]', delivery_geography_json=json.dumps(base['delivery_geography']),
        warranty_text_json='{}', service_text_json='{}', is_default=True, version=1, updated_by='seed'))
    db.commit()
