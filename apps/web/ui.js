// ARTLINE Rich Studio · shared UI primitives.
// Loaded before app.js. Plain globals on purpose: app.js renders templates with
// inline handlers, so every helper here must be reachable from markup.
// Nothing in this file talks to the API or owns business state.

// ————— Icons —————
// One line-icon set (24px grid, 1.9 stroke), drawn in-house so there is no
// runtime dependency. Rules: external link → external, download → download,
// back → chevron-left, menu → more, step forward → chevron-right.
const ICON_PATHS={
  projects:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M8 4v16"/>',
  landings:'<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/>',
  infographic:'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.5-3.5L9 20"/>',
  styles:'<path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.7-.9 1.4-1.9-.4-1.2.4-2.1 1.6-2.1H17a4 4 0 0 0 4-4c0-5.5-4-10-9-10z"/><circle cx="7.5" cy="11" r="1.2"/><circle cx="10.5" cy="7" r="1.2"/><circle cx="15.5" cy="8" r="1.2"/>',
  media:'<rect x="7" y="7" width="14" height="14" rx="2"/><path d="M3 17V5a2 2 0 0 1 2-2h12"/><path d="m21 17-3-3-5 5"/>',
  usage:'<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  users:'<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M21.5 20a6.5 6.5 0 0 0-4-6"/>',
  settings:'<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  'chevron-left':'<path d="m15 18-6-6 6-6"/>',
  'chevron-right':'<path d="m9 18 6-6-6-6"/>',
  'chevron-down':'<path d="m6 9 6 6 6-6"/>',
  'panel-left':'<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18M15 10l-2 2 2 2"/>',
  more:'<circle cx="5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="19" cy="12" r="1.3"/>',
  external:'<path d="M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  download:'<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>',
  x:'<path d="M18 6 6 18M6 6l12 12"/>',
  search:'<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  menu:'<path d="M4 6h16M4 12h16M4 18h16"/>',
  check:'<path d="M20 6 9 17l-5-5"/>',
  refresh:'<path d="M21 12a9 9 0 1 1-2.6-6.4L21 8M21 3v5h-5"/>',
  filter:'<path d="M3 5h18l-7 8v6l-4 2v-8z"/>',
  monitor:'<rect x="2" y="4" width="20" height="13" rx="2"/><path d="M8 21h8M12 17v4"/>',
  phone:'<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M11 18h2"/>',
  inspector:'<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M15 3v18"/>',
  alert:'<path d="M12 3 2 20h20L12 3z"/><path d="M12 10v4M12 17.5v.01"/>',
  info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.5v.01"/>',
  ok:'<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
  bad:'<circle cx="12" cy="12" r="9"/><path d="m15 9-6 6M9 9l6 6"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  play:'<path d="M7 4v16l13-8z"/>',
  logout:'<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
  lock:'<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',
  upload:'<path d="M12 21V9M7 14l5-5 5 5M5 3h14"/>',
  copy:'<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/>',
  trash:'<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>',
  eye:'<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  queue:'<path d="M4 6h16M4 12h10M4 18h7"/><circle cx="18" cy="16" r="3"/>',
  server:'<rect x="3" y="4" width="18" height="7" rx="1.5"/><rect x="3" y="13" width="18" height="7" rx="1.5"/><path d="M7 7.5h.01M7 16.5h.01"/>',
  wallet:'<path d="M3 7h16a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7zM3 7l12-4v4"/><circle cx="16.5" cy="13.5" r="1.2"/>',
};
function icon(name,opts={}){const p=ICON_PATHS[name];if(!p)return '';const cls=`i${opts.sm?' sm':''}${opts.cls?' '+opts.cls:''}`;return opts.label?`<svg class="${cls}" viewBox="0 0 24 24" role="img" aria-label="${String(opts.label).replace(/"/g,'&quot;')}">${p}</svg>`:`<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${p}</svg>`}

// ————— Live region —————
// Generation status and errors are announced once, not on every re-render.
function srLive(){let n=document.getElementById('srLive');if(!n){n=document.createElement('div');n.id='srLive';n.className='sr-only';n.setAttribute('aria-live','polite');n.setAttribute('role','status');document.body.append(n)}return n}
function announce(text){const n=srLive();n.textContent='';setTimeout(()=>{n.textContent=text},60)}

// ————— Dialogs —————
// showModal() already traps focus and closes on Escape. What it cannot do in an
// app that re-renders the whole page: return focus to the button that opened
// the dialog when that button was rebuilt meanwhile. We remember the opener by
// a stable key (id, data-key or its text) and find its successor on close.
(function(){
  const proto=window.HTMLDialogElement&&HTMLDialogElement.prototype;if(!proto||proto.__artlinePatched)return;proto.__artlinePatched=true;
  const orig=proto.showModal;
  const keyOf=el=>{if(!el||el===document.body)return null;return {id:el.id||'',key:el.dataset?.key||'',text:(el.textContent||'').trim().slice(0,60),tag:el.tagName}};
  proto.showModal=function(){const opener=document.activeElement;this.__opener=opener;this.__openerKey=keyOf(opener);const r=orig.apply(this,arguments);if(!this.__closeBound){this.__closeBound=true;this.addEventListener('close',()=>restoreFocus(this))}return r};
  function restoreFocus(dlg){const el=dlg.__opener,k=dlg.__openerKey;dlg.__opener=null;setTimeout(()=>{if(document.querySelector('dialog[open]'))return;if(el&&el.isConnected&&typeof el.focus==='function'){el.focus();return}if(!k)return;let next=k.id?document.getElementById(k.id):null;if(!next&&k.key)next=document.querySelector(`[data-key="${CSS.escape(k.key)}"]`);if(!next&&k.text)next=[...document.querySelectorAll(k.tag||'button')].find(x=>(x.textContent||'').trim().slice(0,60)===k.text);next?.focus?.()},0)}
})();
// ————— Menus (⋯) —————
function menuTpl(items,label='Інші дії',opts={}){const body=items.filter(Boolean).map(it=>{if(it==='-')return '<hr>';if(it.label&&!it.onclick&&!it.href)return `<div class="menu-label">${it.label}</div>`;const ic=it.icon?icon(it.icon,{sm:true}):'';if(it.href)return `<a role="menuitem" href="${it.href}" ${it.external?'target="_blank" rel="noopener noreferrer"':''} ${it.download?'download':''}>${ic}<span>${it.text}</span></a>`;return `<button type="button" role="menuitem" class="${it.danger?'danger':''}" ${it.disabled?'disabled':''} ${it.data!=null?`data-v="${it.data}"`:''} onclick="closeMenus();${it.onclick}">${ic}<span>${it.text}</span></button>`}).join('');return `<div class="menu-wrap"><button type="button" class="icon-btn ${opts.bordered?'bordered':''}" aria-haspopup="menu" aria-expanded="false" aria-label="${label}" title="${label}" onclick="event.stopPropagation();toggleMenu(this)">${icon('more')}</button><div class="menu" role="menu" hidden onclick="event.stopPropagation()">${body}</div></div>`}
function closeMenus(except){document.querySelectorAll('.menu-wrap .menu:not([hidden])').forEach(m=>{if(m===except)return;m.hidden=true;m.previousElementSibling?.setAttribute('aria-expanded','false')})}
function toggleMenu(btn){const menu=btn.nextElementSibling;if(!menu)return;const open=menu.hidden;closeMenus(menu);menu.hidden=!open;btn.setAttribute('aria-expanded',String(open));if(open){menu.classList.remove('up');const r=menu.getBoundingClientRect();if(r.bottom>innerHeight-8&&btn.getBoundingClientRect().top>r.height+8)menu.classList.add('up');menu.querySelector('[role=menuitem]:not([disabled])')?.focus()}}
document.addEventListener('click',()=>closeMenus());
document.addEventListener('keydown',e=>{const menu=e.target.closest?.('.menu');if(e.key==='Escape'){const open=document.querySelector('.menu-wrap .menu:not([hidden])');if(open){e.preventDefault();e.stopPropagation();const btn=open.previousElementSibling;closeMenus();btn?.focus()}return}if(!menu)return;const items=[...menu.querySelectorAll('[role=menuitem]:not([disabled])')];const i=items.indexOf(document.activeElement);if(e.key==='ArrowDown'){e.preventDefault();items[(i+1)%items.length]?.focus()}else if(e.key==='ArrowUp'){e.preventDefault();items[(i-1+items.length)%items.length]?.focus()}else if(e.key==='Home'){e.preventDefault();items[0]?.focus()}else if(e.key==='End'){e.preventDefault();items[items.length-1]?.focus()}else if(e.key==='Tab'){closeMenus()}},true);

// ————— Sidebar —————
// Desktop: collapsible rail, remembered per browser. Small screens: drawer.
function sidebarCollapsed(){try{return localStorage.getItem('sidebarCollapsed')==='1'}catch{return false}}
function toggleSidebar(){const shell=document.querySelector('.shell');if(!shell)return;const on=!shell.classList.contains('collapsed');shell.classList.toggle('collapsed',on);try{localStorage.setItem('sidebarCollapsed',on?'1':'0')}catch{}const b=document.querySelector('.collapse-btn');if(b){b.setAttribute('aria-expanded',String(!on));b.setAttribute('aria-label',on?'Розгорнути меню':'Згорнути меню');const t=b.querySelector('.nav-label');if(t)t.textContent=on?'Розгорнути':'Згорнути'}}
function openDrawer(){const shell=document.querySelector('.shell');if(!shell)return;shell.classList.add('drawer-open');document.querySelector('.drawer-btn')?.setAttribute('aria-expanded','true');setTimeout(()=>document.querySelector('aside.sidebar nav button')?.focus(),50)}
function closeDrawer(focusBack=true){const shell=document.querySelector('.shell');if(!shell||!shell.classList.contains('drawer-open'))return;shell.classList.remove('drawer-open');const b=document.querySelector('.drawer-btn');b?.setAttribute('aria-expanded','false');if(focusBack)b?.focus()}
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeDrawer()});
