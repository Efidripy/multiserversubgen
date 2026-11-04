"""HTML and CSS for the built-in subscription page themes."""

from __future__ import annotations

import html
import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote


def _e(value: object, quote_attr: bool = True) -> str:
    """Escape a value before inserting it into HTML."""
    return html.escape(str(value if value is not None else ""), quote=quote_attr)


@lru_cache(maxsize=1)
def _apps_data() -> dict[str, object]:
    path = Path(__file__).with_name("subscription_page_apps.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _text(value: object, lang: str) -> str:
    if isinstance(value, dict):
        return str(value.get(lang) or value.get("ru") or value.get("en") or "")
    return str(value or "")


def _icon(name: str, fallback: str = "") -> str:
    icons = _apps_data().get("icons", {})
    value = icons.get(name, "") if isinstance(icons, dict) else ""
    if value and not re.search(r"\b(?:style|on[a-z]+)\s*=", value, re.I):
        return value
    return f'<span class="letter-icon">{_e((fallback or "?")[:1].upper())}</span>'


def _ui_icon(kind: str) -> str:
    paths = {
        "link": '<path d="M10 13a5 5 0 0 0 7.1.1l2-2a5 5 0 0 0-7.1-7.1l-1.1 1.1"/><path d="M14 11a5 5 0 0 0-7.1-.1l-2 2A5 5 0 0 0 12 20l1.1-1.1"/>',
        "support": '<path d="M4 5h16v11H8l-4 3z"/><path d="M8 9h8M8 12h5"/>',
        "qr": '<rect x="4" y="4" width="6" height="6"/><rect x="14" y="4" width="6" height="6"/><rect x="4" y="14" width="6" height="6"/><path d="M14 14h3v3h-3zM18 18h3v3h-3zM14 20h2"/>',
        "moon": '<path d="M20 15.3A8 8 0 0 1 8.7 4 8 8 0 1 0 20 15.3z"/>',
    }
    body = paths.get(kind, paths["link"])
    return f'<svg viewBox="0 0 24 24" aria-hidden="true" class="icon" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'


def _subscription_link(template: str, sub_url: str, username: str) -> str:
    replacements = {
        "{{SUBSCRIPTION_LINK_ENC}}": quote(sub_url, safe=""),
        "{{SUBSCRIPTION_LINK}}": sub_url,
        "{{USERNAME}}": quote(username, safe=""),
    }
    return re.sub(
        r"\{\{SUBSCRIPTION_LINK_ENC\}\}|\{\{SUBSCRIPTION_LINK\}\}|\{\{USERNAME\}\}",
        lambda match: replacements[match.group(0)],
        template,
    )


def _button_html(
    button: dict[str, object], data: dict[str, object], app_name: str
) -> str:
    kind = str(button.get("type") or "")
    raw_link = str(button.get("link") or "")
    sub_url = str(data.get("sub_url") or "")
    username = str(data.get("username") or data.get("title") or "")
    if kind == "subscriptionLink":
        if app_name.lower() == "happ" and data.get("happ_link"):
            raw_link = str(data["happ_link"])
        else:
            raw_link = _subscription_link(raw_link, sub_url, username)
        attrs = f'href="{_e(raw_link)}"'
    elif kind == "external":
        if not raw_link.lower().startswith(("http://", "https://")):
            return ""
        attrs = f'href="{_e(raw_link)}" target="_blank" rel="noreferrer"'
    else:
        return ""
    label = _text(button.get("text"), str(data.get("lang") or "ru"))
    icon = _icon(str(button.get("icon") or ""), label)
    return f'<a class="action" {attrs}>{icon}<span>{_e(label)}</span></a>'


def _app(platform: dict[str, object], index: int) -> dict[str, object]:
    apps = platform.get("apps", [])
    return apps[index] if isinstance(apps, list) and index < len(apps) else {}


def _app_tabs(platform_key: str, platform: dict[str, object], lang: str) -> str:
    apps = platform.get("apps", [])
    if not isinstance(apps, list):
        return ""
    result = []
    for index, app in enumerate(apps):
        name = _text(app.get("name"), lang)
        icon = _icon(str(app.get("icon") or ""), name)
        active = " active" if index == 0 else ""
        result.append(
            f'<button type="button" class="app-tab{active}" data-platform-app="{_e(platform_key)}" '
            f'data-app-index="{index}">{icon}<span>{_e(name)}</span></button>'
        )
    return "".join(result)


def _app_panels(
    platform_key: str, platform: dict[str, object], data: dict[str, object]
) -> str:
    apps = platform.get("apps", [])
    if not isinstance(apps, list):
        return ""
    lang = str(data.get("lang") or "ru")
    panels = []
    for index, app in enumerate(apps):
        app_name = _text(app.get("name"), lang)
        blocks = app.get("blocks", [])
        block_html = []
        for block in blocks if isinstance(blocks, list) else []:
            title = _text(block.get("title"), lang)
            description = _text(block.get("description"), lang)
            buttons = block.get("buttons", [])
            actions = "".join(
                _button_html(button, data, app_name)
                for button in buttons
                if isinstance(button, dict)
            )
            icon = _icon(str(block.get("icon") or ""), title)
            color = _e(block.get("color") or "cyan")
            block_html.append(
                f'<article class="step step-{color}"><div class="step-icon">{icon}</div>'
                f'<div class="step-body"><h3>{_e(title)}</h3><p>{_e(description)}</p>'
                f'<div class="actions">{actions}</div></div></article>'
            )
        hidden = "" if index == 0 else " hidden"
        panels.append(
            f'<div class="app-panel" data-platform-app-panel="{_e(platform_key)}" '
            f'data-app-index="{index}"{hidden}><div class="steps">{"".join(block_html)}</div></div>'
        )
    return "".join(panels)


def _platform_sections(data: dict[str, object]) -> tuple[str, str]:
    catalog = _apps_data().get("platforms", {})
    if not isinstance(catalog, dict):
        return "", ""
    lang = str(data.get("lang") or "ru")
    selectors = []
    sections = []
    first = True
    for key, platform in catalog.items():
        if not isinstance(platform, dict):
            continue
        name = _text(platform.get("name"), lang)
        icon = _icon(str(platform.get("icon") or ""), name)
        selectors.append(
            f'<button type="button" class="platform-option" data-platform="{_e(key)}">'
            f"{icon}<span>{_e(name)}</span></button>"
        )
        hidden = "" if first else " hidden"
        sections.append(
            f'<section class="platform-section" data-platform-section="{_e(key)}"{hidden}>'
            f'<div class="app-tabs">{_app_tabs(key, platform, lang)}</div>'
            f"{_app_panels(key, platform, data)}</section>"
        )
        first = False
    return "".join(selectors), "".join(sections)


BASE_CSS = """
*,*::before,*::after{box-sizing:border-box}
html,body{margin:0;min-width:320px;overflow-x:hidden;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}
button,a{font:inherit}
button{cursor:pointer}
.icon{display:block;width:20px;height:20px}
.muted{opacity:.68}
.qr-img{display:block;width:100%;max-width:240px;height:auto;margin:auto;border-radius:12px}
dialog{padding:0;border:0;background:transparent;color:inherit}
dialog::backdrop{background:rgba(0,0,0,.68)}
.dialog-card{width:min(360px,calc(100vw - 32px));
padding:22px;
border:1px solid var(--border);
border-radius:16px;
background:var(--card);
color:var(--text)}
.letter-icon{display:inline-grid;place-items:center;width:24px;height:24px;font-weight:700}
.lang-switch{display:flex;flex:0 0 auto;align-items:center;gap:2px;padding:3px;border:1px solid var(--border);border-radius:10px}
.lang-switch a{padding:5px 7px;border-radius:7px;color:var(--muted);font-size:13px;font-weight:600;line-height:1.2;text-decoration:none}
.lang-switch a.active{background:var(--border);color:var(--text)}
"""


REMNAWAVE_CSS = """
:root{--bg:#11151f;--card:#192231;--border:#344252;--text:#edf2f7;--muted:#9eabb8;--accent:#22b8cf}
body{background:var(--bg);
color:var(--text);
background-image:radial-gradient(circle at 8% 8%,#1c3443 0,transparent 35%),
radial-gradient(circle at 90% 80%,#30243d 0,transparent 35%),
linear-gradient(rgba(255,255,255,.018) 1px,transparent 1px),
linear-gradient(90deg,rgba(255,255,255,.018) 1px,transparent 1px);
background-size:auto,auto,32px 32px,32px 32px;background-attachment:fixed;min-height:100vh}
.wrap{width:min(672px,100%);margin:auto;padding:22px 16px 42px}
.top{display:flex;align-items:center;gap:12px;margin-bottom:18px}
.brand{flex:1;min-width:0;color:var(--accent)}
.brand h1{margin:0;font-size:22px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.actions{display:flex;gap:8px}
.icon-btn{display:inline-grid;
place-items:center;
width:40px;
height:40px;
border:1px solid var(--border);
border-radius:12px;
background:#1a2431;
color:#8de5ef;
text-decoration:none}
.card{margin:14px 0;
padding:18px;
border:1px solid var(--border);
border-radius:16px;
background:rgba(27,34,48,.9);
box-shadow:0 12px 35px rgba(0,0,0,.18)}
.user-head{display:flex;align-items:center;gap:12px}
.avatar{display:grid;place-items:center;width:44px;height:44px;border-radius:50%;background:#2f9e64;font-size:22px}
.bad .avatar{background:#d9485f}
.username{font-size:19px;font-weight:700}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:16px}
.tile{min-width:0;padding:12px;border:1px solid;border-radius:12px;background:rgba(20,27,39,.74)}
.tile b{display:block;margin-bottom:4px;color:var(--muted);font-size:12px}
.tile span{display:block;overflow-wrap:anywhere}
.tile-blue{border-color:#3979b9}
.tile-green{border-color:#3d9b69}
.tile-red{border-color:#b84e61}
.tile-amber{border-color:#b2853d}
.announce{border-color:#247f91;color:#c8f6fb;background:#183b4b}
.install-head{display:flex;align-items:center;justify-content:space-between;gap:12px}
.install-head h2{margin:0;font-size:18px}
.platform-select{position:relative}
.platform-select>button{display:flex;
align-items:center;
gap:6px;
border:1px solid var(--border);
border-radius:9px;
padding:7px 10px;
background:#17212d;
color:var(--text)}
.platform-menu{position:absolute;
right:0;
z-index:3;
display:grid;
min-width:150px;
margin-top:5px;
padding:5px;
border:1px solid var(--border);
border-radius:10px;
background:#17212d}
.platform-menu[hidden]{display:none}
.platform-option{display:flex;
align-items:center;
gap:8px;
border:0;
border-radius:7px;
padding:8px;
background:transparent;
color:var(--text);
text-align:left}
.platform-option:hover{background:#263548}
.app-tabs{display:grid;grid-template-columns:repeat(auto-fill,minmax(126px,1fr));gap:8px;padding:14px 0}
.app-tab{display:flex;
align-items:center;
gap:8px;
min-width:0;
border:1px solid var(--border);
border-radius:12px;
padding:10px;
background:#17212d;
color:var(--text);
text-align:left}
.app-tab.active{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent) inset}
.app-tab svg{width:28px;height:28px;opacity:.8}
.app-tab span{overflow:hidden;text-overflow:ellipsis}
.steps{display:grid;gap:10px}
.step{display:flex;gap:12px;padding:13px;border:1px solid var(--border);border-radius:13px;background:rgba(20,27,39,.58)}
.step-icon{display:grid;place-items:center;flex:0 0 auto;width:34px;height:34px;border-radius:50%;background:#24445b;color:#9be8f0}
.step-icon svg{width:19px;height:19px}
.step-body{min-width:0}
.step h3{margin:0 0 5px;font-size:15px}
.step p{margin:0;color:#c4d0dc;line-height:1.45}
.step .actions{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}
.action,.btn{display:inline-flex;
align-items:center;
justify-content:center;
gap:6px;
border:1px solid #466078;
border-radius:9px;
padding:7px 11px;
background:#202d3c;
color:#dcecf5;
text-decoration:none}
.action svg{width:16px;height:16px}
.action:hover,.btn:hover{border-color:var(--accent)}
.action[href^="happ:"]{background:#22b8cf;color:#07151a;border-color:#22b8cf}
@media(max-width:420px){.wrap{padding:14px 10px 28px}
.card{padding:14px}
.grid{gap:8px}
}
"""


THREEXUI_CSS = """
:root{--bg:#16171a;--card:#1f2125;--border:#2e3035;--text:#f1f3f5;--muted:#9da3ad;--accent:#1668dc}
:root.light{--bg:#f4f5f7;--card:#fff;--border:#dfe1e6;--text:#1f2329;--muted:#69707d}
body{background:var(--bg);color:var(--text);transition:background .15s}
.wrap{width:min(760px,100%);margin:auto;padding:20px 14px 34px}
.top{display:flex;align-items:center;gap:12px;margin-bottom:16px}
.logo{display:grid;place-items:center;width:38px;height:38px;border-radius:11px;background:var(--accent);color:white;font-weight:800}
.headtext{flex:1;min-width:0}
.headtext h1{margin:0;font-size:20px;overflow-wrap:anywhere}
.headtext small{color:var(--muted)}
.icon-btn{display:grid;
place-items:center;
width:38px;
height:38px;
border:1px solid var(--border);
border-radius:10px;
background:var(--card);
color:var(--text)}
.card{margin:12px 0;padding:16px;border:1px solid var(--border);border-radius:14px;background:var(--card)}
.stats{display:flex;align-items:center;gap:20px}
.ring{width:112px;height:112px;flex:0 0 auto}
.ring text{fill:var(--text);font-size:20px;font-weight:700;text-anchor:middle}
.usage strong{display:block;font-size:25px}
.usage span{color:var(--muted)}
.tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:14px}
.tile{min-width:0;padding:10px;border:1px solid var(--border);border-radius:10px}
.tile b{display:block;margin-bottom:3px;color:var(--muted);font-size:11px}
.tile span{overflow-wrap:anywhere}
.badge{display:inline-block;padding:3px 7px;border-radius:7px;background:#236b3a;color:#b6f2c6;font-size:12px}
.tabs{display:flex;flex-wrap:wrap;gap:6px;margin:-2px -16px 14px;padding:0 16px;border-bottom:1px solid var(--border)}
.tab{border:0;border-bottom:2px solid transparent;padding:10px 8px;background:none;color:var(--muted);white-space:nowrap}
.tab.active{border-color:var(--accent);color:var(--accent)}
.format-list,.nodes{display:grid;gap:8px;margin:0;padding:0;list-style:none}
.format-list li,.nodes li{display:flex;align-items:center;gap:8px;min-width:0;padding:9px 0;border-bottom:1px solid var(--border)}
.fmt{width:64px;color:var(--accent);font-size:11px;font-weight:700}
code{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted)}
.nodes li span{flex:1;min-width:0}
.nodes b,.nodes small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.nodes small{margin-top:2px;color:var(--muted)}
.btn,.app-action,.action{display:inline-flex;
align-items:center;
gap:5px;
border:1px solid var(--border);
border-radius:8px;
padding:7px 10px;
background:transparent;
color:var(--text);
text-decoration:none;
white-space:nowrap}
.platform-segments{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}
.platform-segments .btn.selected{border-color:var(--accent);color:var(--accent)}
.apps{display:grid;gap:8px}
.app-row{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-bottom:8px;padding:9px;border:1px solid var(--border);border-radius:10px}
.app-row .app-name{flex:1 1 140px;display:flex;align-items:center;gap:8px;min-width:0}
.app-name span{overflow:hidden;text-overflow:ellipsis}
.app-row .app-action{font-size:13px}
.qr-card{text-align:center}
.qr-card p{color:var(--muted)}
.update{color:var(--muted);font-size:12px;text-align:center}
@media(max-width:520px){.top{gap:8px}
.logo{display:none}
.headtext h1{font-size:17px;overflow-wrap:normal}
.stats{gap:12px}
.ring{width:88px;height:88px}
.tiles{grid-template-columns:repeat(2,minmax(0,1fr))}
}
"""


COMMON_SCRIPT = """
(function(){
  function get(k,d){try{return localStorage.getItem(k)||d}catch(e){return d}}
  function set(k,v){try{localStorage.setItem(k,v)}catch(e){}}
  var savedLang=get('sub-page-lang',''),pageUrl=new URL(location.href);
  if(savedLang&&savedLang!==document.documentElement.lang&&!pageUrl.searchParams.get('lang')){
    pageUrl.searchParams.set('lang',savedLang);location.replace(pageUrl);return}
  function fallback(text,done){try{var t=document.createElement('textarea');t.value=text;
    t.setAttribute('readonly','');t.style.position='fixed';t.style.left='-9999px';
    document.body.appendChild(t);t.select();document.execCommand('copy');t.remove();done()
  }catch(e){}}
  function copy(text,button){if(!text)return;var old=button.textContent;
    var done=function(){button.textContent=button.dataset.copied||'Copied';
      setTimeout(function(){button.textContent=old},1200)};
    if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(text)
      .then(done).catch(function(){fallback(text,done)})}else fallback(text,done)}
  function choosePlatform(key){
    document.querySelectorAll('[data-platform-section]').forEach(function(x){
      x.hidden=x.dataset.platformSection!==key});
    document.querySelectorAll('[data-platform]').forEach(function(x){
      x.classList.toggle('selected',x.dataset.platform===key);
      var label=document.querySelector('[data-platform-toggle]');
      if(label&&x.dataset.platform===key)label.innerHTML=x.innerHTML});set('sub-page-platform',key)}
  function chooseApp(platform,index){
    document.querySelectorAll('[data-platform-app-panel="'+platform+'"]').forEach(function(x){
      x.hidden=x.dataset.appIndex!==index});
    document.querySelectorAll('[data-platform-app="'+platform+'"]').forEach(function(x){
      x.classList.toggle('active',x.dataset.appIndex===index)});
    set('sub-page-app-'+platform,index)}
  document.addEventListener('click',function(e){
    var l=e.target.closest('[data-lang]');if(l)set('sub-page-lang',l.dataset.lang);
    var b=e.target.closest('[data-copy]');if(b)copy(b.getAttribute('data-copy'),b);
    var toggle=e.target.closest('[data-platform-toggle]');
    if(toggle){var menu=toggle.parentNode.querySelector('.platform-menu');if(menu)menu.hidden=!menu.hidden}
    var p=e.target.closest('[data-platform]');
    if(p){choosePlatform(p.dataset.platform);var first=document.querySelector(
      '[data-platform-app][data-platform-app="'+p.dataset.platform+'"]');
      if(first)chooseApp(p.dataset.platform,first.dataset.appIndex);
      var menu=p.closest('.platform-menu');if(menu)menu.hidden=true}
    var a=e.target.closest('[data-platform-app]');
    if(a)chooseApp(a.dataset.platformApp,a.dataset.appIndex);
    var t=e.target.closest('[data-tab]');
    if(t){document.querySelectorAll('[data-tab-panel]').forEach(function(x){
      x.hidden=x.dataset.tabPanel!==t.dataset.tab});document.querySelectorAll('[data-tab]').forEach(function(x){
      x.classList.toggle('active',x===t)});set('sub-page-3x-tab',t.dataset.tab)}
    var o=e.target.closest('[data-open-qr]');
    if(o){var d=document.getElementById('qr-dialog');if(d&&d.showModal)d.showModal()}
    var c=e.target.closest('[data-close-qr]');if(c){var d=document.getElementById('qr-dialog');if(d)d.close()}
    var m=e.target.closest('[data-theme-toggle]');if(m){var light=document.documentElement.classList.toggle('light');
      set('sub-page-3x-theme',light?'light':'dark')}});
  var firstPlatform=document.querySelector('[data-platform]');var detected='';
  var ua=(navigator.userAgent||'').toLowerCase();
  if(/iphone|ipad/.test(ua))detected='ios';else if(/android/.test(ua)&&/tv/.test(ua))detected='androidTV';
  else if(/android/.test(ua))detected='android';else if(/mac/.test(ua))detected='macos';
  else if(/windows/.test(ua))detected='windows';else if(/linux/.test(ua))detected='linux';
  var platform=get('sub-page-platform',detected||(firstPlatform&&firstPlatform.dataset.platform));
  if(platform&&document.querySelector('[data-platform-section="'+platform+'"]'))choosePlatform(platform);
  document.querySelectorAll('[data-platform-section]').forEach(function(s){var key=s.dataset.platformSection;
    var saved=get('sub-page-app-'+key,'0');if(document.querySelector(
      '[data-platform-app-panel="'+key+'"][data-app-index="'+saved+'"]'))chooseApp(key,saved)});
  var savedTheme=get('sub-page-3x-theme','');if(savedTheme==='light')document.documentElement.classList.add('light');
  var tab=get('sub-page-3x-tab','sub');var tabNode=document.querySelector('[data-tab="'+tab+'"]');if(tabNode)tabNode.click();
})();
"""


def _script(nonce: str) -> str:
    return f'<script nonce="{_e(nonce)}">{COMMON_SCRIPT}</script>'


def _theme_init_script(nonce: str) -> str:
    code = "try{if(localStorage.getItem('sub-page-3x-theme')==='light')document.documentElement.classList.add('light')}catch(e){}"
    return f'<script nonce="{_e(nonce)}">{code}</script>'


def _lang_switch(data: dict[str, object]) -> str:
    current = str(data.get("lang") or "ru")
    links = []
    for code in ("ru", "en"):
        state = ' class="active" aria-current="true"' if code == current else ""
        links.append(
            f'<a href="?html=1&amp;lang={code}" data-lang="{code}"{state}>{code.upper()}</a>'
        )
    return f'<nav class="lang-switch" aria-label="Language">{"".join(links)}</nav>'


def _qr_dialog(data: dict[str, object], include_qr: bool = True) -> str:
    qr = str(data.get("qr_data_url") or "")
    image = f'<img src="{_e(qr)}" alt="QR" class="qr-img">' if qr and include_qr else ""
    return (
        '<dialog id="qr-dialog"><div class="dialog-card">'
        f"<h2>{_e(data.get('qr_label'))}</h2>{image}"
        f"<p>{_e(data.get('qr_hint'))}</p>"
        f'<button type="button" class="btn" data-copy="{_e(data.get("sub_url"))}">'
        f"{_e(data.get('copy_label'))}</button> "
        f'<button type="button" class="btn" data-close-qr>{_e(data.get("close_label"))}</button>'
        "</div></dialog>"
    )


def render_remnawave(data: dict[str, object]) -> str:
    lang = _e(data.get("lang", "ru"))
    nonce = _e(data.get("nonce", ""))
    title = _e(data.get("title", "Subscription"))
    status = str(data.get("status") or "active")
    bad = " bad" if status in {"expired", "depleted"} else ""
    status_label = _e(data.get("status_label"))
    username = _e(data.get("username") or data.get("title"))
    support = str(data.get("support_url") or "")
    support_button = ""
    if support.lower().startswith(("http://", "https://")):
        support_button = f'<a class="icon-btn" href="{_e(support)}" aria-label="Support">{_ui_icon("support")}</a>'
    selectors, sections = _platform_sections(data)
    announce = str(data.get("announce") or "")
    percent = _e(data.get("percent_decimal", "0.0%"))
    tiles = (
        f'<div class="tile tile-blue"><b>{_e(data.get("username_label"))}</b><span>{username}</span></div>'
        f'<div class="tile tile-green"><b>{_e(data.get("status_label_name"))}</b><span>{status_label}</span></div>'
        f'<div class="tile tile-red"><b>{_e(data.get("expire_label"))}</b><span>{_e(data.get("expire"))}</span></div>'
        f'<div class="tile tile-amber"><b>{_e(data.get("traffic_label"))}</b>'
        f"<span>{_e(data.get('used'))} / {_e(data.get('total'))}</span></div>"
    )
    first_platform = next(iter(_apps_data().get("platforms", {})), "")
    platform_name = _text(
        _apps_data().get("platforms", {}).get(first_platform, {}).get("name"),
        str(data.get("lang") or "ru"),
    )
    platform_icon = _icon(
        str(
            _apps_data().get("platforms", {}).get(first_platform, {}).get("icon") or ""
        ),
        platform_name,
    )
    return (
        f'<!DOCTYPE html><html lang="{lang}"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>'
        f'<style nonce="{nonce}">{BASE_CSS}{REMNAWAVE_CSS}</style></head><body class="status-{_e(status)}">'
        f'<main class="wrap"><header class="top"><div class="brand"><h1>{title}</h1></div><div class="actions">'
        f'{_lang_switch(data)}<button type="button" class="icon-btn" data-open-qr aria-label="QR">{_ui_icon("qr")}</button>{support_button}'
        f'</div></header><section class="card{bad}"><div class="user-head"><div class="avatar">{"!" if bad else "✓"}</div>'
        f'<div><div class="username">{username}</div><div class="muted">{_e(data.get("expire_label"))}: '
        f'{_e(data.get("expire"))}</div></div></div><div class="grid">{tiles}</div>'
        f'<div data-width="{percent}"></div></section>'
        f"{f'<div class="card announce">{_e(announce)}</div>' if announce else ''}"
        f'<section class="card"><div class="install-head"><h2>{_e(data.get("install_title"))}</h2>'
        f'<div class="platform-select"><button type="button" data-platform-toggle>{platform_icon}<span>{_e(platform_name)}</span></button>'
        f'<div class="platform-menu" hidden>{selectors}</div></div></div>{sections}</section></main>'
        f"{_qr_dialog(data)}{_script(str(data.get('nonce', '')))}</body></html>"
    )


def _format_rows(data: dict[str, object]) -> str:
    sub_url = str(data.get("sub_url") or "")
    labels = data
    formats = [
        ("SUB", sub_url, False),
        ("JSON", sub_url + "?format=xray_json", True),
        ("CLASH", sub_url + "?format=clash", True),
        ("SING-BOX", sub_url + "?format=singbox", True),
    ]
    rows = []
    for name, url, downloadable in formats:
        download = (
            f'<a class="btn" href="{_e(url)}" download>↓</a>' if downloadable else ""
        )
        rows.append(
            f'<li><span class="fmt">{_e(name)}</span><code>{_e(url)}</code>'
            f'<button type="button" class="btn" data-copy="{_e(url)}">{_e(labels.get("copy_label"))}</button>{download}</li>'
        )
    return "".join(rows)


def _three_apps(data: dict[str, object]) -> str:
    catalog = _apps_data().get("platforms", {})
    lang = str(data.get("lang") or "ru")
    rows = []
    platforms = []
    first = True
    for key, platform in catalog.items() if isinstance(catalog, dict) else []:
        platform_name = (
            _text(platform.get("name"), lang) if isinstance(platform, dict) else key
        )
        platforms.append(
            f'<button type="button" class="btn" data-platform="{_e(key)}">{_e(platform_name)}</button>'
        )
        platform_rows = []
        for app in platform.get("apps", []) if isinstance(platform, dict) else []:
            name = str(app.get("name") or "")
            buttons = [
                b
                for block in app.get("blocks", [])
                for b in block.get("buttons", [])
                if isinstance(b, dict)
            ]
            add = next(
                (
                    _button_html(b, data, name)
                    for b in buttons
                    if b.get("type") == "subscriptionLink"
                ),
                "",
            )
            download = next(
                (
                    _button_html(b, data, name)
                    for b in buttons
                    if b.get("type") == "external"
                ),
                "",
            )
            icon = _icon(str(app.get("icon") or ""), name)
            platform_rows.append(
                f'<div class="app-row"><div class="app-name">{icon}<span>{_e(name)}</span></div>{add}{download}</div>'
            )
        hidden = "" if first else " hidden"
        rows.append(
            f'<div data-platform-section="{_e(key)}"{hidden}>{"".join(platform_rows)}</div>'
        )
        first = False
    return f'<div class="platform-segments">{"".join(platforms)}</div>{"".join(rows)}'


def render_3xui(data: dict[str, object]) -> str:
    lang = _e(data.get("lang", "ru"))
    nonce = _e(data.get("nonce", ""))
    title = _e(data.get("title", "Subscription"))
    links = data.get("links", []) or []
    node_rows = "".join(
        f"<li><span><b>{_e(name)}</b><small>{_e(proto)}</small></span>"
        f'<button type="button" class="btn" data-copy="{_e(link)}">{_e(data.get("copy_label"))}</button></li>'
        for name, proto, link in links
    )
    percent = str(data.get("percent", "∞"))
    offset = _e(data.get("ring_offset", "301.6"))
    identifier = _e(data.get("identifier") or "—")
    update = data.get("update_interval")
    update_html = ""
    if update:
        update_html = f'<div class="update">{_e(data.get("update_label"))}: {int(update)} {_e(data.get("hours_label"))}</div>'
    nodes_html = node_rows or f"<li>{_e(data.get('no_nodes'))}</li>"
    qr_image = ""
    if data.get("qr_data_url"):
        qr_image = f'<img class="qr-img" src="{_e(data.get("qr_data_url"))}" alt="QR">'
    return (
        f'<!DOCTYPE html><html lang="{lang}"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>'
        f'{_theme_init_script(str(data.get("nonce", "")))}<style nonce="{nonce}">{BASE_CSS}{THREEXUI_CSS}</style></head><body><main class="wrap">'
        f'<header class="top"><div class="logo">3X</div><div class="headtext"><h1>{_e(data.get("info_title"))}</h1>'
        f'<small>{identifier}</small></div>{_lang_switch(data)}<button type="button" class="icon-btn" data-open-qr aria-label="QR">{_ui_icon("qr")}</button>'
        f'<button type="button" class="icon-btn" data-theme-toggle aria-label="Theme">{_ui_icon("moon")}</button></header>'
        f'<section class="card stats"><svg class="ring" viewBox="0 0 120 120">'
        f'<circle cx="60" cy="60" r="48" fill="none" stroke="var(--border)" stroke-width="10"/>'
        f'<circle cx="60" cy="60" r="48" fill="none" stroke="var(--accent)" '
        f'stroke-width="10" stroke-linecap="round" stroke-dasharray="301.6" '
        f'stroke-dashoffset="{offset}" transform="rotate(-90 60 60)"/>'
        f'<text x="60" y="67">{_e(percent)}</text></svg><div class="usage">'
        f'<strong>{_e(data.get("used"))}</strong><span>{_e(data.get("total"))}</span></div></section>'
        f'<section class="tiles"><div class="tile"><b>{_e(data.get("remaining_label"))}</b><span>{_e(data.get("remaining"))}</span></div>'
        f'<div class="tile"><b>{_e(data.get("expire_label"))}</b><span>{_e(data.get("expire"))}</span></div>'
        f'<div class="tile"><b>{_e(data.get("status_label_name"))}</b>'
        f'<span class="badge">{_e(data.get("status_label"))}</span></div>'
        f'<div class="tile"><b>{_e(data.get("download_label"))}</b><span>{_e(data.get("download"))}</span></div>'
        f'<div class="tile"><b>{_e(data.get("upload_label"))}</b><span>{_e(data.get("upload"))}</span></div>'
        f'<div class="tile"><b>{_e(data.get("total_label"))}</b><span>{_e(data.get("total"))}</span></div></section>'
        f'<section class="card"><nav class="tabs"><button type="button" class="tab active" data-tab="sub">{_e(data.get("sub_tab"))} ({len(links)})</button>'
        f'<button type="button" class="tab" data-tab="apps">{_e(data.get("apps_tab"))}</button>'
        f'<button type="button" class="tab" data-tab="nodes">{_e(data.get("nodes_tab"))} ({len(links)})</button></nav>'
        f'<div data-tab-panel="sub"><ul class="format-list">{_format_rows(data)}</ul><div class="qr-card">'
        f"{qr_image}<p>{_e(data.get('qr_hint'))}</p></div></div>"
        f'<div data-tab-panel="apps" hidden><div class="apps">{_three_apps(data)}</div></div>'
        f'<div data-tab-panel="nodes" hidden><ul class="nodes">{nodes_html}</ul></div></section>{update_html}</main>'
        f"{_qr_dialog(data, include_qr=True)}{_script(str(data.get('nonce', '')))}</body></html>"
    )


def render_theme(theme: str, data: dict[str, object]) -> str:
    return render_3xui(data) if theme == "3xui" else render_remnawave(data)
