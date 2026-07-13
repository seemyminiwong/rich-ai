import hashlib
import json
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.config import settings
from app.db import Base, SessionLocal, engine, ensure_schema, get_db
from app.models import Artifact, Asset, AuditLog, BenchmarkRun, BrandProfile, CriticReport, Event, Invite, KnowledgeDocument, Project, PublishTarget, Review, Role, Status, Style, StyleVersion, User, WorkflowTemplate
from app.security import current, hash_password, token, verify
from app.tasks import process_project

Path(settings.media_dir).mkdir(parents=True, exist_ok=True)

DEFAULT_STYLE_PROMPT = 'Create premium ecommerce rich content in the ARTLINE design code. Use only verified product facts. Return one valid HTML section with inline CSS. Interface palette: #101010, #1A2128, #252525, #2F3137, #35393F, #434343, #555555, #69737D, #6E7781, #808080, #999999, #9E9EA4, #AFB8C1, #BBBBBB, #D0D7DE, #F5F7FA, #F7F8FA. Accent palette: #19BCC9, #37AEE2, #51C48A, #6890E4, #6D64BB, #735FF2, #8FAE4F, #C7BEFF, #CD7D74, #E8485E, #EB5757, #F7987C, #FFC77E. Keep a cohesive ARTLINE visual language: clear hierarchy, restrained shadows, consistent radii, readable typography and responsive desktop/mobile variants.'
DEFAULT_HERO_PROMPT = 'Photorealistic premium wide ecommerce hero. Preserve the exact product, place it in a realistic usage environment on the right, keep clean dark negative space on the left, no text or invented accessories.'
DEFAULT_FEATURE_PROMPT = 'Clean photorealistic product visualization on a light neutral background. Preserve exact geometry and branding, no text or invented accessories.'


def seed():
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == settings.admin_email))
        if not user:
            db.add(User(email=settings.admin_email, name='Адміністратор', password_hash=hash_password(settings.admin_password), role=Role.admin))
        if not db.scalar(select(Style).limit(1)):
            db.add(Style(name='ARTLINE Unified', description='Базовий стиль у фірмовій палітрі ARTLINE', prompt=DEFAULT_STYLE_PROMPT, hero_prompt=DEFAULT_HERO_PROMPT, feature_prompt=DEFAULT_FEATURE_PROMPT, negative_prompt='No text, watermarks, fake labels, invented accessories or distorted product geometry.', score_json=json.dumps({'consistency':92,'readability':94,'brand_fit':96}), is_default=True))
        if not db.scalar(select(WorkflowTemplate).limit(1)):
            db.add(WorkflowTemplate(name='ARTLINE Full Pipeline', steps_json=json.dumps(['research','images','content','image_critic','html_critic','fact_critic','review'], ensure_ascii=False), is_default=True))
        db.commit()

@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_schema()
    Base.metadata.create_all(engine)
    seed()
    yield


app = FastAPI(title='ARTLINE Rich Studio API', version='11.3', lifespan=lifespan)
app.mount('/media', StaticFiles(directory=settings.media_dir), name='media')

class Login(BaseModel): email: str; password: str
class RegisterIn(BaseModel): token: str; name: str = Field(min_length=2, max_length=120); password: str = Field(min_length=8, max_length=200)
class InviteIn(BaseModel): email: str; role: Role = Role.viewer
class UserUpdate(BaseModel): role: Role | None = None; active: bool | None = None; name: str | None = None
class UserPasswordIn(BaseModel): password: str = Field(min_length=8, max_length=200)
class UserCreate(BaseModel):
    email: str
    name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=200)
    role: Role = Role.viewer
class ProjectIn(BaseModel):
    name: str = ''; source_url: HttpUrl; style_id: str | None = None
    languages: list[str] = Field(default_factory=lambda: ['ru'])
    variants: list[str] = Field(default_factory=lambda: ['desktop', 'mobile'])
    text_model: str | None = None; image_model: str | None = None; image_quality: str = 'medium'
    custom_hero_url: str = ''; custom_feature_url: str = ''
class StyleIn(BaseModel):
    name: str
    description: str = ''
    prompt: str = ''
    hero_prompt: str = ''
    feature_prompt: str = ''
    negative_prompt: str = ''
    score: dict = Field(default_factory=dict)
    preview_html: str = ''
    is_default: bool = False
class StyleGenerateIn(BaseModel):
    name: str = 'Новий стиль'
    brief: str = ''
    reference_url: str = ''
    model: str | None = None
class StyleImproveIn(BaseModel):
    instructions: str = ''
    model: str | None = None
class StyleAnalyzeIn(BaseModel):
    prompt: str = ''
    hero_prompt: str = ''
    feature_prompt: str = ''
    negative_prompt: str = ''
class HtmlIn(BaseModel): html: str
class ReviewIn(BaseModel):
    decision: str
    comment: str = ''
    checklist: dict[str, bool] = Field(default_factory=dict)

class BrandIn(BaseModel):
    name: str
    description: str = ''
    design_dna: str = ''
    rules: dict = Field(default_factory=dict)
class KnowledgeIn(BaseModel):
    brand_id: str | None = None
    title: str
    source_url: str = ''
    content: str
    tags: str = ''
class PlaygroundIn(BaseModel):
    prompt: str
    product_json: dict = Field(default_factory=dict)
    model: str | None = None
class CompareIn(BaseModel):
    prompt: str
    product_json: dict = Field(default_factory=dict)
    models: list[str]
class WorkflowIn(BaseModel):
    name: str
    steps: list[str]
    is_default: bool = False
class TargetIn(BaseModel):
    name: str
    target_type: str = 'webhook'
    endpoint: str = ''
    config: dict = Field(default_factory=dict)
    active: bool = True
class PublishIn(BaseModel):
    target_id: str
    artifact_id: str
class BenchmarkIn(BaseModel):
    source_url: HttpUrl
    competitor_url: HttpUrl
class QueueIn(BaseModel):
    action: str
class CriticIn(BaseModel):
    auto_fix: bool = False


def require_roles(*roles):
    def dep(user=Depends(current)):
        if user.role not in roles:
            raise HTTPException(403, 'Недостатньо прав')
        return user
    return dep

def audit(db, user, action, entity_type='', entity_id='', metadata=None):
    db.add(AuditLog(user_id=getattr(user,'id',None), action=action, entity_type=entity_type, entity_id=entity_id, metadata_json=json.dumps(metadata or {}, ensure_ascii=False)))

def user_dict(x):
    return {'id':x.id,'email':x.email,'name':x.name,'role':x.role.value,'active':x.active,'created_at':x.created_at,'last_login_at':x.last_login_at}
def style_dict(x): return {'id':x.id,'name':x.name,'description':x.description,'prompt':x.prompt,'hero_prompt':x.hero_prompt,'feature_prompt':x.feature_prompt,'negative_prompt':x.negative_prompt,'score':json.loads(x.score_json or '{}'),'preview_html':x.preview_html,'is_default':x.is_default}
def artifact_dict(x): return {'id':x.id,'language':x.language,'variant':x.variant,'html':x.html,'version':x.version,'created_at':x.created_at}
def project_dict(p, full=False):
    r={'id':p.id,'name':p.name,'source_url':p.source_url,'style_id':p.style_id,'owner_id':p.owner_id,'status':p.status.value,'stage':p.stage,'progress':p.progress,
       'languages':[x for x in p.languages.split(',') if x],'variants':[x for x in p.variants.split(',') if x],'text_model':p.text_model,'image_model':p.image_model,'image_quality':p.image_quality,
       'custom_hero_url':p.custom_hero_url,'custom_feature_url':p.custom_feature_url,'product_category':p.product_category,'error':p.error,'duration_seconds':p.duration_seconds,'input_tokens':p.input_tokens,'output_tokens':p.output_tokens,
       'image_count':p.image_count,'text_request_count':p.text_request_count,'image_request_count':p.image_request_count,'text_cost':p.text_cost,'image_cost':p.image_cost,'estimated_cost':p.estimated_cost,
       'created_at':p.created_at,'started_at':p.started_at,'finished_at':p.finished_at}
    if full:
        r['product_json']=p.product_json; r['source_images']=p.source_images
        r['artifacts']=[artifact_dict(x) for x in sorted(p.artifacts,key=lambda a:(a.language,a.variant,a.version))]
    return r

@app.get('/health')
def health(): return {'status':'ok','version':'11.3'}
@app.post('/api/auth/login')
def login(payload: Login, db: Session=Depends(get_db)):
    user=db.scalar(select(User).where(User.email==payload.email))
    if not user or not verify(payload.password,user.password_hash): raise HTTPException(401,'Неправильний email або пароль')
    user.last_login_at=datetime.utcnow(); audit(db,user,'auth.login','user',user.id); db.commit()
    return {'access_token':token(user),'token_type':'bearer'}
@app.post('/api/auth/register')
def register(payload:RegisterIn, db:Session=Depends(get_db)):
    h=hashlib.sha256(payload.token.encode()).hexdigest(); inv=db.scalar(select(Invite).where(Invite.token_hash==h))
    if not inv or inv.accepted_at or inv.expires_at < datetime.utcnow(): raise HTTPException(400,'Запрошення недійсне або прострочене')
    if db.scalar(select(User).where(User.email==inv.email)): raise HTTPException(409,'Користувач уже існує')
    user=User(email=inv.email,name=payload.name,password_hash=hash_password(payload.password),role=inv.role,active=True)
    db.add(user); inv.accepted_at=datetime.utcnow(); db.flush(); audit(db,user,'auth.register','user',user.id); db.commit()
    return {'access_token':token(user),'token_type':'bearer'}
@app.get('/api/me')
def me(user=Depends(current)): return user_dict(user)

@app.get('/api/users')
def users(db:Session=Depends(get_db), user=Depends(require_roles(Role.admin))):
    return [user_dict(x) for x in db.scalars(select(User).order_by(User.created_at.desc())).all()]
@app.post('/api/users')
def create_user(payload:UserCreate, db:Session=Depends(get_db), user=Depends(require_roles(Role.admin))):
    email=payload.email.strip().lower()
    if db.scalar(select(User).where(User.email==email)): raise HTTPException(409,'Користувач уже існує')
    target=User(email=email,name=payload.name.strip(),password_hash=hash_password(payload.password),role=payload.role,active=True)
    db.add(target);db.flush();audit(db,user,'user.create','user',target.id,{'email':email,'role':payload.role.value});db.commit();db.refresh(target)
    return user_dict(target)

@app.post('/api/users/invites')
def create_invite(payload:InviteIn, db:Session=Depends(get_db), user=Depends(require_roles(Role.admin))):
    if db.scalar(select(User).where(User.email==payload.email)): raise HTTPException(409,'Користувач уже існує')
    raw=secrets.token_urlsafe(32); inv=Invite(email=payload.email,role=payload.role,token_hash=hashlib.sha256(raw.encode()).hexdigest(),created_by=user.id,expires_at=datetime.utcnow()+timedelta(days=7))
    db.add(inv); audit(db,user,'invite.create','invite',inv.id,{'email':payload.email,'role':payload.role.value}); db.commit()
    return {'token':raw,'register_path':f'/register?token={raw}','expires_at':inv.expires_at}
@app.patch('/api/users/{user_id}')
def update_user(user_id:str,payload:UserUpdate,db:Session=Depends(get_db),user=Depends(require_roles(Role.admin))):
    target=db.get(User,user_id)
    if not target: raise HTTPException(404,'Користувача не знайдено')
    for k,v in payload.model_dump(exclude_none=True).items(): setattr(target,k,v)
    audit(db,user,'user.update','user',target.id,payload.model_dump(exclude_none=True)); db.commit(); return user_dict(target)

@app.post('/api/users/{user_id}/password')
def reset_user_password(user_id:str,payload:UserPasswordIn,db:Session=Depends(get_db),user=Depends(require_roles(Role.admin))):
    target=db.get(User,user_id)
    if not target: raise HTTPException(404,'Користувача не знайдено')
    target.password_hash=hash_password(payload.password)
    audit(db,user,'user.password_reset','user',target.id); db.commit(); return {'ok':True}

@app.delete('/api/users/{user_id}')
def delete_user(user_id:str,db:Session=Depends(get_db),user=Depends(require_roles(Role.admin))):
    if user_id==user.id: raise HTTPException(400,'Не можна видалити власний обліковий запис')
    target=db.get(User,user_id)
    if not target: raise HTTPException(404,'Користувача не знайдено')
    linked=db.scalar(select(func.count(Project.id)).where(Project.owner_id==target.id)) or 0
    if linked:
        target.active=False
        audit(db,user,'user.archive','user',target.id,{'email':target.email,'linked_projects':linked}); db.commit()
        return {'ok':True,'archived':True}
    audit(db,user,'user.delete','user',target.id,{'email':target.email}); db.delete(target); db.commit(); return {'ok':True,'archived':False}

@app.get('/api/styles')
def styles(db:Session=Depends(get_db),user=Depends(current)): return [style_dict(x) for x in db.scalars(select(Style).order_by(Style.name)).all()]
@app.post('/api/styles')
def create_style(payload:StyleIn,db:Session=Depends(get_db),user=Depends(require_roles(Role.admin,Role.editor))):
    if payload.is_default:
        for item in db.scalars(select(Style)).all(): item.is_default=False
    data=payload.model_dump(); score=data.pop('score',{}); preview=data.pop('preview_html',''); s=Style(**data,score_json=json.dumps(score,ensure_ascii=False),preview_html=preview); db.add(s); db.flush(); db.add(StyleVersion(style_id=s.id,version=1,prompt=s.prompt,hero_prompt=s.hero_prompt,feature_prompt=s.feature_prompt,created_by=user.id)); audit(db,user,'style.create','style',s.id); db.commit(); db.refresh(s); return style_dict(s)
@app.put('/api/styles/{style_id}')
def update_style(style_id:str,payload:StyleIn,db:Session=Depends(get_db),user=Depends(require_roles(Role.admin,Role.editor))):
    s=db.scalar(select(Style).where(Style.id==style_id).with_for_update())
    if not s: raise HTTPException(404,'Стиль не знайдено')
    if payload.is_default:
        for item in db.scalars(select(Style)).all(): item.is_default=False
    data=payload.model_dump(); score=data.pop('score',{}); preview=data.pop('preview_html','');
    for k,v in data.items(): setattr(s,k,v)
    s.score_json=json.dumps(score,ensure_ascii=False); s.preview_html=preview
    current_version=db.scalar(select(func.max(StyleVersion.version)).where(StyleVersion.style_id==s.id)) or 0; db.add(StyleVersion(style_id=s.id,version=current_version+1,prompt=s.prompt,hero_prompt=s.hero_prompt,feature_prompt=s.feature_prompt,created_by=user.id)); audit(db,user,'style.update','style',s.id); db.commit(); return style_dict(s)


@app.get('/api/styles/{style_id}/versions')
def style_versions(style_id:str,db:Session=Depends(get_db),user=Depends(current)):
    rows=db.scalars(select(StyleVersion).where(StyleVersion.style_id==style_id).order_by(StyleVersion.version.desc())).all()
    return [{'id':x.id,'version':x.version,'prompt':x.prompt,'hero_prompt':x.hero_prompt,'feature_prompt':x.feature_prompt,'created_at':x.created_at} for x in rows]

@app.post('/api/styles/analyze')
def analyze_style(payload:StyleAnalyzeIn,user=Depends(require_roles(Role.admin,Role.editor))):
    text=' '.join([payload.prompt,payload.hero_prompt,payload.feature_prompt,payload.negative_prompt]).strip()
    length=len(text)
    required=['inline css','responsive','desktop','mobile','hero','section','product','facts']
    coverage=sum(1 for key in required if key in text.lower())
    consistency=min(100, 52 + coverage*5 + min(8, length//1500))
    readability=min(100, 58 + (10 if 'typography' in text.lower() else 0) + (10 if 'line-height' in text.lower() else 0) + min(12, length//1000))
    brand_fit=min(100, 50 + (18 if 'artline' in text.lower() else 0) + (12 if '#19bcc9' in text.lower() else 0) + (10 if '#101010' in text.lower() else 0) + min(10, length//1800))
    issues=[]
    if length<1200: issues.append('Style Prompt надто короткий для стабільної генерації.')
    if not payload.hero_prompt.strip(): issues.append('Генерацію Hero вимкнено, оскільки Hero Prompt порожній.')
    if not payload.feature_prompt.strip(): issues.append('Генерацію Feature вимкнено, оскільки Feature Prompt порожній.')
    if 'mobile' not in text.lower(): issues.append('Немає правил для мобільної версії.')
    if 'facts' not in text.lower() and 'invent' not in text.lower(): issues.append('Правила фактологічної безпеки слабкі або відсутні.')
    return {'score':{'consistency':consistency,'readability':readability,'brand_fit':brand_fit},'issues':issues,'ready':min(consistency,readability,brand_fit)>=70}

@app.get('/api/projects')
def projects(db:Session=Depends(get_db),user=Depends(current)): return [project_dict(x) for x in db.scalars(select(Project).order_by(Project.created_at.desc())).all()]
@app.post('/api/projects')
def create_project(payload:ProjectIn,db:Session=Depends(get_db),user=Depends(require_roles(Role.admin,Role.editor))):
    style=db.get(Style,payload.style_id) if payload.style_id else db.scalar(select(Style).where(Style.is_default==True))
    if not style: raise HTTPException(400,'Немає доступного стилю')
    langs=[x for x in payload.languages if x in {'ru','ua','pl'}]; vars=[x for x in payload.variants if x in {'desktop','mobile'}]
    if not langs or not vars: raise HTTPException(400,'Оберіть щонайменше одну мову та формат')
    p=Project(name=payload.name.strip() or 'Определение товара…',source_url=str(payload.source_url),style_id=style.id,owner_id=user.id,languages=','.join(dict.fromkeys(langs)),variants=','.join(dict.fromkeys(vars)),
      text_model=payload.text_model or settings.openai_text_model,image_model=payload.image_model or settings.openai_image_model,image_quality=payload.image_quality if payload.image_quality in {'low','medium','high'} else 'medium',custom_hero_url=payload.custom_hero_url.strip(),custom_feature_url=payload.custom_feature_url.strip(),status=Status.queued,stage='queued')
    db.add(p); db.flush(); audit(db,user,'project.create','project',p.id); db.commit(); db.refresh(p); process_project.delay(p.id); return project_dict(p)
@app.get('/api/projects/{project_id}')
def project(project_id:str,db:Session=Depends(get_db),user=Depends(current)):
    p=db.get(Project,project_id)
    if not p: raise HTTPException(404,'Проєкт не знайдено')
    r=project_dict(p,True)
    r['reviews']=[{'id':x.id,'reviewer_id':x.reviewer_id,'decision':x.decision,'comment':x.comment,'checklist':json.loads(x.checklist_json or '{}'),'created_at':x.created_at} for x in db.scalars(select(Review).where(Review.project_id==p.id).order_by(Review.created_at.desc())).all()]
    r['assets']=[{'id':x.id,'kind':x.kind,'label':x.label,'url':x.url,'prompt':x.prompt,'model':x.model,'width':x.width,'height':x.height,'cost':x.cost,'metadata':json.loads(x.metadata_json or '{}'),'created_at':x.created_at} for x in db.scalars(select(Asset).where(Asset.project_id==p.id).order_by(Asset.created_at.desc())).all()]
    r['critics']=[{'id':x.id,'type':x.critic_type,'score':x.score,'summary':x.summary,'issues':json.loads(x.issues_json or '[]'),'suggestions':json.loads(x.suggestions_json or '[]'),'auto_fixed':x.auto_fixed,'created_at':x.created_at} for x in db.scalars(select(CriticReport).where(CriticReport.project_id==p.id).order_by(CriticReport.created_at.desc())).all()]
    return r
@app.post('/api/projects/{project_id}/run')
def rerun(project_id:str,db:Session=Depends(get_db),user=Depends(require_roles(Role.admin,Role.editor))):
    p=db.get(Project,project_id)
    if not p: raise HTTPException(404,'Проєкт не знайдено')
    if p.status==Status.processing: raise HTTPException(409,'Проєкт уже виконується')
    p.status=Status.queued;p.stage='queued';p.progress=0;p.error='';p.input_tokens=0;p.output_tokens=0;p.image_count=0;p.text_request_count=0;p.image_request_count=0;p.text_cost=0;p.image_cost=0;p.estimated_cost=0
    audit(db,user,'project.rerun','project',p.id);db.commit();process_project.delay(p.id);return {'queued':True}
@app.post('/api/projects/{project_id}/review')
def review(project_id:str,payload:ReviewIn,db:Session=Depends(get_db),user=Depends(require_roles(Role.admin,Role.editor,Role.reviewer))):
    p=db.get(Project,project_id)
    if not p:
        raise HTTPException(404,'Проєкт не знайдено')
    if payload.decision not in {'approve','request_changes','submit'}:
        raise HTTPException(400,'Неприпустиме рішення')
    if payload.decision=='request_changes' and not payload.comment.strip():
        raise HTTPException(400,'Коментар обов’язковий')
    if payload.decision=='approve' and user.role not in {Role.admin,Role.reviewer}:
        raise HTTPException(403,'Схвалювати результат може адміністратор або рев’юер')
    try:
        mapping={'approve':Status.approved,'request_changes':Status.changes_requested,'submit':Status.review}
        new_status=mapping[payload.decision]
        p.status=new_status
        p.stage=new_status.value
        row=Review(project_id=p.id,reviewer_id=user.id,decision=payload.decision,comment=payload.comment.strip(),checklist_json=json.dumps(payload.checklist or {},ensure_ascii=False))
        db.add(row)
        decision_label={'approve':'Схвалено','request_changes':'Запитано зміни','submit':'Надіслано на перевірку'}[payload.decision]
        db.add(Event(project_id=p.id,stage='review',level='info',message=f'{user.email}: {decision_label}'))
        audit(db,user,'review.'+payload.decision,'project',p.id)
        db.commit()
        return {'status':new_status.value,'message':decision_label}
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(500,f'Не вдалося зберегти рішення перевірки: {exc}') from exc

@app.get('/api/projects/{project_id}/events')
def events(project_id:str,db:Session=Depends(get_db),user=Depends(current)):
    return [{'id':x.id,'stage':x.stage,'level':x.level,'message':x.message,'created_at':x.created_at} for x in db.scalars(select(Event).where(Event.project_id==project_id).order_by(Event.created_at.desc())).all()]
@app.put('/api/artifacts/{artifact_id}')
def save_artifact(artifact_id:str,payload:HtmlIn,db:Session=Depends(get_db),user=Depends(require_roles(Role.admin,Role.editor))):
    source=db.get(Artifact,artifact_id)
    if not source:
        raise HTTPException(404,'Результат не знайдено')
    if not payload.html.strip():
        raise HTTPException(400,'HTML не може бути порожнім')
    try:
        # Serialize version allocation for one project. The UI blocks double clicks,
        # while this lock also protects simultaneous saves from different users.
        db.scalar(select(Project.id).where(Project.id==source.project_id).with_for_update())
        latest_version=db.scalar(select(func.max(Artifact.version)).where(Artifact.project_id==source.project_id,Artifact.language==source.language,Artifact.variant==source.variant)) or 0
        new=Artifact(project_id=source.project_id,language=source.language,variant=source.variant,html=payload.html,version=latest_version+1,created_by=user.id)
        db.add(new);db.flush();audit(db,user,'artifact.version','artifact',new.id);db.commit();db.refresh(new);return artifact_dict(new)
    except Exception as exc:
        db.rollback()
        raise HTTPException(500,f'Не вдалося зберегти нову версію: {exc}') from exc

@app.get('/api/models')
def available_models(user=Depends(current)):
    text_models=list(settings.text_models); image_models=list(settings.image_models); reasoning_models=[]; source='configuration'
    if settings.openai_api_key:
        try:
            from openai import OpenAI
            rows=OpenAI(api_key=settings.openai_api_key).models.list().data
            ids=sorted({x.id for x in rows})
            excluded=('audio','realtime','transcribe','tts','embedding','moderation','whisper','dall-e')
            discovered_image=[x for x in ids if ('image' in x or x.startswith('dall-e'))]
            discovered_text=[x for x in ids if any(x.startswith(prefix) for prefix in ('gpt-','o1','o3','o4')) and not any(k in x for k in excluded) and x not in discovered_image]
            reasoning_models=[x for x in discovered_text if x.startswith(('o1','o3','o4')) or 'reasoning' in x]
            text_models=sorted(dict.fromkeys(discovered_text+text_models)); image_models=sorted(dict.fromkeys(discovered_image+image_models)); source='openai+configuration'
        except Exception:
            pass
    return {'text_models':text_models,'image_models':image_models,'reasoning_models':reasoning_models,'source':source,'default_text_model':settings.openai_text_model,'default_image_model':settings.openai_image_model}

@app.get('/api/assets')
def all_assets(db:Session=Depends(get_db),user=Depends(current)):
    rows=db.scalars(select(Asset).order_by(Asset.created_at.desc())).all()
    return [{'id':x.id,'project_id':x.project_id,'kind':x.kind,'label':x.label,'url':x.url,'prompt':x.prompt,'model':x.model,'width':x.width,'height':x.height,'cost':x.cost,'metadata':json.loads(x.metadata_json or '{}'),'created_at':x.created_at} for x in rows]

def _style_ai_payload(name, brief, reference_url=''):
    palette='ARTLINE palette: #101010 #1A2128 #252525 #2F3137 #35393F #434343 #555555 #69737D #6E7781 #808080 #999999 #9E9EA4 #AFB8C1 #BBBBBB #D0D7DE #F5F7FA #F7F8FA; accents #19BCC9 #37AEE2 #51C48A #6890E4 #6D64BB #735FF2 #8FAE4F #C7BEFF #CD7D74 #E8485E #EB5757 #F7987C #FFC77E.'
    prompt=f'''Create a complete ecommerce rich-content design style named {name}. {palette}
Brief: {brief}
Reference URL: {reference_url}
Return strict JSON with keys description, style_prompt, hero_prompt, feature_prompt, negative_prompt, score (object with consistency, readability, brand_fit integers 0-100), preview_html. The preview_html must be a compact safe demo section using inline CSS only.'''
    return prompt

@app.post('/api/styles/generate')
def generate_style(payload:StyleGenerateIn,user=Depends(require_roles(Role.admin,Role.editor))):
    model=payload.model or settings.openai_text_model
    fallback={'description':'Згенерований ARTLINE-стиль','style_prompt':DEFAULT_STYLE_PROMPT+'\n'+payload.brief,'hero_prompt':DEFAULT_HERO_PROMPT,'feature_prompt':DEFAULT_FEATURE_PROMPT,'negative_prompt':'No text, watermark, distortion or invented accessories.','score':{'consistency':90,'readability':92,'brand_fit':95},'preview_html':'<section style="padding:32px;border-radius:24px;background:#101010;color:#F5F7FA;font-family:Arial"><small style="color:#19BCC9">ARTLINE STYLE</small><h2 style="font-size:36px;margin:12px 0">Premium product presentation</h2><p style="color:#AFB8C1">Unified ARTLINE visual system preview.</p></section>','model':model}
    if not settings.openai_api_key: return fallback
    try:
        from openai import OpenAI
        r=OpenAI(api_key=settings.openai_api_key).responses.create(model=model,input=_style_ai_payload(payload.name,payload.brief,payload.reference_url),max_output_tokens=6000,store=False)
        raw=r.output_text.strip(); raw=raw[raw.find('{'):raw.rfind('}')+1]; data=json.loads(raw); data['model']=model; return data
    except Exception as exc:
        fallback['warning']=str(exc); return fallback

@app.post('/api/styles/{style_id}/improve')
def improve_style(style_id:str,payload:StyleImproveIn,db:Session=Depends(get_db),user=Depends(require_roles(Role.admin,Role.editor))):
    s=db.get(Style,style_id)
    if not s: raise HTTPException(404,'Стиль не знайдено')
    generated=generate_style(StyleGenerateIn(name=s.name,brief=(s.prompt+'\nImprovement request: '+payload.instructions)[:12000],model=payload.model),user)
    return generated

@app.get('/api/usage')
def usage(db:Session=Depends(get_db),user=Depends(current)):
    rows=db.scalars(select(Project)).all(); total=sum(x.estimated_cost for x in rows)
    return {'total_cost':total,'projects':len(rows),'input_tokens':sum(x.input_tokens for x in rows),'output_tokens':sum(x.output_tokens for x in rows),'images':sum(x.image_count for x in rows),'average_cost':total/len(rows) if rows else 0,
            'by_project':[{'id':x.id,'name':x.name,'cost':x.estimated_cost,'created_at':x.created_at} for x in sorted(rows,key=lambda x:x.created_at,reverse=True)[:20]]}
@app.get('/api/settings')
def settings_view(user=Depends(current)):
    return {'openai_configured':bool(settings.openai_api_key),'default_text_model':settings.openai_text_model,'default_image_model':settings.openai_image_model,'text_models':settings.text_models,'image_models':settings.image_models,'text_pricing':settings.text_pricing,'image_pricing':settings.image_pricing,'model_source':'configured suggestions'}

@app.get('/api/brands')
def brands(db:Session=Depends(get_db),user=Depends(current)):
    return [{'id':x.id,'name':x.name,'description':x.description,'design_dna':x.design_dna,'rules':json.loads(x.rules_json or '{}'),'created_at':x.created_at} for x in db.scalars(select(BrandProfile).order_by(BrandProfile.name)).all()]

@app.post('/api/brands')
def create_brand(payload:BrandIn,db:Session=Depends(get_db),user=Depends(require_roles(Role.admin,Role.editor))):
    row=BrandProfile(name=payload.name,description=payload.description,design_dna=payload.design_dna,rules_json=json.dumps(payload.rules,ensure_ascii=False))
    db.add(row);db.flush();audit(db,user,'brand.create','brand',row.id);db.commit();return {'id':row.id}

@app.get('/api/knowledge')
def knowledge(db:Session=Depends(get_db),user=Depends(current)):
    return [{'id':x.id,'brand_id':x.brand_id,'title':x.title,'source_url':x.source_url,'content':x.content,'tags':x.tags,'created_at':x.created_at} for x in db.scalars(select(KnowledgeDocument).order_by(KnowledgeDocument.created_at.desc())).all()]

@app.post('/api/knowledge')
def add_knowledge(payload:KnowledgeIn,db:Session=Depends(get_db),user=Depends(require_roles(Role.admin,Role.editor))):
    row=KnowledgeDocument(brand_id=payload.brand_id,title=payload.title,source_url=payload.source_url,content=payload.content,tags=payload.tags,created_by=user.id)
    db.add(row);db.flush();audit(db,user,'knowledge.create','knowledge',row.id);db.commit();return {'id':row.id}

@app.delete('/api/knowledge/{doc_id}')
def delete_knowledge(doc_id:str,db:Session=Depends(get_db),user=Depends(require_roles(Role.admin,Role.editor))):
    row=db.get(KnowledgeDocument,doc_id)
    if not row: raise HTTPException(404,'Document not found')
    db.delete(row);audit(db,user,'knowledge.delete','knowledge',doc_id);db.commit();return {'deleted':True}

@app.get('/api/styles/{style_id}/versions')
def style_versions(style_id:str,db:Session=Depends(get_db),user=Depends(current)):
    return [{'id':x.id,'version':x.version,'prompt':x.prompt,'hero_prompt':x.hero_prompt,'feature_prompt':x.feature_prompt,'created_at':x.created_at} for x in db.scalars(select(StyleVersion).where(StyleVersion.style_id==style_id).order_by(StyleVersion.version.desc())).all()]

@app.post('/api/playground')
def playground(payload:PlaygroundIn,user=Depends(require_roles(Role.admin,Role.editor))):
    from app.pipeline import client, _usage_counts
    model=payload.model or settings.openai_text_model
    if not client: return {'output':'OpenAI is not configured','input_tokens':0,'output_tokens':0,'estimated_cost':0,'model':model}
    prompt=payload.prompt+'\nPRODUCT JSON:\n'+json.dumps(payload.product_json,ensure_ascii=False)
    response=client.responses.create(model=model,input=prompt,max_output_tokens=8000,store=False)
    i,o=_usage_counts(response,prompt,response.output_text)
    rates=settings.text_pricing.get(model,{'input':1,'output':4})
    cost=i/1_000_000*float(rates.get('input',1))+o/1_000_000*float(rates.get('output',4))
    return {'output':response.output_text,'input_tokens':i,'output_tokens':o,'estimated_cost':cost,'model':model}

@app.post('/api/compare')
def compare(payload:CompareIn,user=Depends(require_roles(Role.admin,Role.editor))):
    results=[]
    for model in payload.models[:4]:
        try: results.append({**playground(PlaygroundIn(prompt=payload.prompt,product_json=payload.product_json,model=model),user), 'ok':True})
        except Exception as exc: results.append({'model':model,'ok':False,'error':str(exc)})
    return results

@app.post('/api/projects/{project_id}/critic')
def run_critic(project_id:str,payload:CriticIn,db:Session=Depends(get_db),user=Depends(require_roles(Role.admin,Role.editor,Role.reviewer))):
    from app.pipeline import critic_html
    p=db.get(Project,project_id)
    if not p: raise HTTPException(404,'Проєкт не знайдено')
    latest={}
    for a in sorted(p.artifacts,key=lambda x:x.version): latest[(a.language,a.variant)]=a
    reports=[]
    for kind in ('html','facts','accessibility','marketing'):
        score,summary,issues,suggestions=critic_html(list(latest.values()),kind,json.loads(p.product_json or '{}'))
        row=CriticReport(project_id=p.id,critic_type=kind,score=score,summary=summary,issues_json=json.dumps(issues,ensure_ascii=False),suggestions_json=json.dumps(suggestions,ensure_ascii=False),auto_fixed=False)
        db.add(row);reports.append({'type':kind,'score':score,'summary':summary,'issues':issues,'suggestions':suggestions})
    db.add(Event(project_id=p.id,stage='critic',message='AI critic completed'));audit(db,user,'critic.run','project',p.id);db.commit();return reports

@app.post('/api/projects/{project_id}/queue')
def queue_control(project_id:str,payload:QueueIn,db:Session=Depends(get_db),user=Depends(require_roles(Role.admin,Role.editor))):
    p=db.get(Project,project_id)
    if not p: raise HTTPException(404,'Проєкт не знайдено')
    if payload.action=='pause': p.status=Status.paused;p.stage='paused'
    elif payload.action=='cancel': p.status=Status.cancelled;p.stage='cancelled'
    elif payload.action in {'resume','retry'}:
        p.status=Status.queued;p.stage='queued';p.progress=0;process_project.delay(p.id)
    else: raise HTTPException(400,'Invalid action')
    audit(db,user,'queue.'+payload.action,'project',p.id);db.commit();return {'status':p.status.value}

@app.get('/api/workflows')
def workflows(db:Session=Depends(get_db),user=Depends(current)):
    return [{'id':x.id,'name':x.name,'steps':json.loads(x.steps_json or '[]'),'is_default':x.is_default} for x in db.scalars(select(WorkflowTemplate).order_by(WorkflowTemplate.name)).all()]

@app.post('/api/workflows')
def create_workflow(payload:WorkflowIn,db:Session=Depends(get_db),user=Depends(require_roles(Role.admin))):
    if payload.is_default:
        for x in db.scalars(select(WorkflowTemplate)).all(): x.is_default=False
    row=WorkflowTemplate(name=payload.name,steps_json=json.dumps(payload.steps,ensure_ascii=False),is_default=payload.is_default)
    db.add(row);db.flush();audit(db,user,'workflow.create','workflow',row.id);db.commit();return {'id':row.id}

@app.get('/api/publish-targets')
def publish_targets(db:Session=Depends(get_db),user=Depends(current)):
    return [{'id':x.id,'name':x.name,'target_type':x.target_type,'endpoint':x.endpoint,'active':x.active,'config':json.loads(x.config_json or '{}')} for x in db.scalars(select(PublishTarget).order_by(PublishTarget.name)).all()]

@app.post('/api/publish-targets')
def create_target(payload:TargetIn,db:Session=Depends(get_db),user=Depends(require_roles(Role.admin))):
    row=PublishTarget(name=payload.name,target_type=payload.target_type,endpoint=payload.endpoint,config_json=json.dumps(payload.config,ensure_ascii=False),active=payload.active)
    db.add(row);db.flush();audit(db,user,'publish_target.create','publish_target',row.id);db.commit();return {'id':row.id}

@app.post('/api/publish')
def publish(payload:PublishIn,db:Session=Depends(get_db),user=Depends(require_roles(Role.admin,Role.editor))):
    import httpx
    target=db.get(PublishTarget,payload.target_id);artifact=db.get(Artifact,payload.artifact_id)
    if not target or not artifact: raise HTTPException(404,'Target or artifact not found')
    if target.target_type=='download': return {'status':'ready','html':artifact.html}
    if target.target_type=='webhook':
        if not target.endpoint: raise HTTPException(400,'Webhook endpoint is empty')
        response=httpx.post(target.endpoint,json={'artifact_id':artifact.id,'language':artifact.language,'variant':artifact.variant,'html':artifact.html},timeout=30)
        response.raise_for_status();status='published'
    else: status='exported'
    audit(db,user,'publish.execute','artifact',artifact.id,{'target':target.id});db.commit();return {'status':status}

@app.post('/api/benchmark')
def benchmark(payload:BenchmarkIn,db:Session=Depends(get_db),user=Depends(require_roles(Role.admin,Role.editor))):
    from app.pipeline import fetch_html, parse_page
    a=parse_page(fetch_html(str(payload.source_url)),str(payload.source_url));b=parse_page(fetch_html(str(payload.competitor_url)),str(payload.competitor_url))
    report={'source':{'title':a[2],'text_length':len(a[3]),'images':len(a[1])},'competitor':{'title':b[2],'text_length':len(b[3]),'images':len(b[1])},'recommendations':[]}
    if report['source']['images']<report['competitor']['images']: report['recommendations'].append('Add more product images')
    if report['source']['text_length']<report['competitor']['text_length']: report['recommendations'].append('Increase factual content depth')
    row=BenchmarkRun(source_url=str(payload.source_url),competitor_url=str(payload.competitor_url),report_json=json.dumps(report,ensure_ascii=False))
    db.add(row);db.flush();audit(db,user,'benchmark.run','benchmark',row.id);db.commit();return report

@app.get('/api/analytics')
def analytics(db:Session=Depends(get_db),user=Depends(current)):
    projects=db.scalars(select(Project)).all();critics=db.scalars(select(CriticReport)).all();styles_=db.scalars(select(Style)).all()
    model_counts={};style_counts={}
    for p in projects:
        model_counts[p.text_model]=model_counts.get(p.text_model,0)+1;style_counts[p.style_id]=style_counts.get(p.style_id,0)+1
    style_names={x.id:x.name for x in styles_}
    return {'projects':len(projects),'cost':sum(x.estimated_cost for x in projects),'average_time':sum(x.duration_seconds for x in projects)/len(projects) if projects else 0,'average_score':sum(x.score for x in critics)/len(critics) if critics else 0,'models':model_counts,'styles':{style_names.get(k,k):v for k,v in style_counts.items()},'statuses':{s.value:sum(1 for p in projects if p.status==s) for s in Status}}
