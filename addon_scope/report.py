"""Self-contained diagnostic reports, safe to open without a running service."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .models import ScanResult
from .comparison import package_comparison


def report_dict(result: ScanResult, redact_paths: bool = True) -> dict:
    """Return a portable snapshot; redact scan roots and the current home by default.

    This is path redaction, not a guarantee that logs contain no private content.
    Review a report before posting it publicly.
    """
    data = result.to_dict()
    for finding, record in zip(result.findings, data["findings"]):
        record["comparison"] = package_comparison(result, finding)
    data["paths_redacted"] = redact_paths
    if not redact_paths:
        return data

    replacements = []
    for index, root in enumerate(result.roots, 1):
        value = str(root).rstrip("/\\")
        if value and value not in {".", ".."}:
            replacements.append((value, f"$SCAN_{index}"))
    home = str(Path.home()).rstrip("/\\")
    if home:
        replacements.append((home, "$HOME"))
    # The most specific inspected root wins over a containing home directory.
    replacements.sort(key=lambda pair: len(pair[0]), reverse=True)
    patterns = []
    for original, label in replacements:
        variants = {original, original.replace("\\", "/"), original.replace("/", "\\")}
        for variant in variants:
            patterns.append((re.compile(re.escape(variant) + r"(?=$|[/\\!:\s'\")\],;])"), label))

    def redact(value):
        if isinstance(value, str):
            for pattern, label in patterns:
                value = pattern.sub(lambda _: label, value)
            return value
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, dict):
            return {redact(key): redact(item) for key, item in value.items()}
        return value

    return redact(data)


def write_json(result: ScanResult, path: str | Path, redact_paths: bool = True) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report_dict(result, redact_paths), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def write_html(result: ScanResult, path: str | Path, redact_paths: bool = True) -> Path:
    data = json.dumps(report_dict(result, redact_paths), ensure_ascii=False)
    # Application/json is still parsed as script raw text by the HTML parser.
    # Escaping '<' prevents data such as '</script>' from ending its container.
    for raw, escaped in (("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e"), ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        data = data.replace(raw, escaped)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_HTML.replace("__REPORT_DATA__", data), encoding="utf-8")
    return target


_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'">
<title>AddonScope · Diagnostic report</title>
<style>
:root{color-scheme:light;--ink:#243145;--muted:#526178;--line:#dce3ed;--shell:#f4f6f9;--blue:#315fc1;--selected:#edf3ff;--red:#a42d35;--amber:#855914;--mono:ui-monospace,SFMono-Regular,Consolas,monospace}
*{box-sizing:border-box}body{margin:0;background:var(--shell);color:var(--ink);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif}button,input,select{font:inherit}button{cursor:pointer}button:disabled{cursor:default}button:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible,a:focus-visible{outline:3px solid #82a8ff;outline-offset:3px}button{border:1px solid var(--line);border-radius:5px;background:white;color:var(--ink);padding:7px 12px}button:hover{background:#f0f4fa}a{color:var(--blue)}[hidden]{display:none!important}.topbar{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:16px 24px;border-bottom:1px solid var(--line);background:white}.identity{display:flex;align-items:center;gap:12px}.mark{height:34px;width:34px;display:grid;place-items:center;background:#233953;color:white;border-radius:7px;font:700 15px var(--mono)}.brand{font-size:16px;font-weight:650;letter-spacing:-.3px}.eyebrow{font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted)}.top-actions{display:flex;align-items:center;gap:12px}.subtle{font-size:12px;color:var(--muted)}.primary{background:var(--blue);border-color:var(--blue);color:white}.primary:hover{background:#254d9f}.scope{padding:14px 24px 0;max-width:1600px;margin:auto}.scope-line{display:flex;align-items:baseline;gap:8px 20px;flex-wrap:wrap}.scope-line h1{font-size:19px;letter-spacing:-.3px;font-weight:650;margin:0}.scope-line p{margin:0;color:var(--muted)}.tabs{display:flex;gap:24px;border-bottom:1px solid var(--line);margin-top:14px}.tab{border:0;border-radius:0;background:none;padding:10px 2px;position:relative;color:var(--muted)}.tab:hover{background:none;color:var(--ink)}.tab[aria-selected=true]{color:var(--blue);font-weight:600}.tab[aria-selected=true]:after{content:"";position:absolute;bottom:-1px;height:2px;left:0;right:0;background:var(--blue)}.tab span{font-size:12px;background:#e8edf4;border-radius:4px;padding:1px 6px;margin-left:5px;font-weight:400}.workspace{max-width:1552px;margin:20px auto 24px;border:1px solid var(--line);background:white;border-radius:7px;overflow:hidden}.findings-workspace{display:grid;grid-template-columns:minmax(290px,34%) minmax(0,1fr);min-height:600px}.queue{border-right:1px solid var(--line);background:#fbfcfe;min-width:0}.queue-head{padding:16px;border-bottom:1px solid var(--line)}.queue-head h2{font-size:13px;margin:0 0 12px;font-weight:650}.filters{display:flex;gap:8px}.search{min-width:0;flex:1;border:1px solid #becbdb;border-radius:5px;background:white;padding:8px 10px;color:var(--ink)}select{max-width:115px;border:1px solid #becbdb;background:white;border-radius:5px;color:var(--ink);padding:7px}.list-info{font-size:12px;color:var(--muted);margin-top:9px}.finding-list{max-height:calc(100vh - 337px);min-height:310px;overflow:auto;padding:6px 0}.finding{display:block;width:100%;text-align:left;border:0;border-radius:0;border-left:3px solid transparent;border-bottom:1px solid #eaf0f6;padding:14px 16px 14px 13px;background:transparent}.finding:hover{background:#f0f4fa}.finding[aria-pressed=true]{background:var(--selected);border-left-color:var(--blue)}.row-meta{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:11px;margin-bottom:5px}.severity{display:inline-flex;align-items:center;gap:5px;font-size:12px;font-weight:600}.severity.error{color:var(--red)}.severity.warning{color:var(--amber)}.severity.info{color:#315c90}.finding-title{display:block;font-weight:600;line-height:1.45;overflow-wrap:anywhere}.finding-owner{display:block;margin-top:5px;font-size:12px;color:var(--muted);overflow-wrap:anywhere}.detail{padding:24px 30px;min-width:0}.detail-header{border-bottom:1px solid var(--line);padding-bottom:20px;margin-bottom:22px}.detail-header .row-meta{justify-content:flex-start;gap:16px;margin-bottom:10px}.detail h2{font-size:21px;line-height:1.35;letter-spacing:-.35px;margin:0 0 12px;overflow-wrap:anywhere}.detail p{margin:0 0 12px;max-width:85ch}.detail h3{font-size:12px;letter-spacing:.06em;text-transform:uppercase;margin:24px 0 10px;color:var(--muted);font-weight:650}.evidence{list-style:none;padding:0;margin:0;display:grid;gap:1px;background:var(--line);border:1px solid var(--line);border-radius:5px;overflow:hidden}.evidence li{background:#f7f9fc;padding:10px 12px;font:12px/1.65 var(--mono);white-space:pre-wrap;overflow-wrap:anywhere}.owner-list{display:grid;gap:10px}.owner{display:grid;grid-template-columns:minmax(110px,1fr) minmax(0,2fr);gap:6px 16px;padding-bottom:10px;border-bottom:1px solid #eaf0f6}.owner strong{font-size:13px;font-weight:600;overflow-wrap:anywhere}.owner code{display:block;font:12px/1.55 var(--mono);overflow-wrap:anywhere;color:var(--muted)}.owner .subtle{display:block;margin-top:2px}.next-step{border-left:3px solid #8ba7dc;padding:2px 0 2px 14px;margin-top:8px}.next-step p{margin:0}.empty{padding:50px 24px;text-align:center;color:var(--muted)}.empty strong{display:block;font-size:16px;color:var(--ink);margin-bottom:8px}.empty p{margin:0 auto 14px;max-width:50ch}.detail .empty{text-align:left;padding:40px 0}.coverage{max-width:1552px;margin:0 auto 28px;font-size:12px;color:var(--muted)}.coverage details{border-top:1px solid var(--line);padding:14px 0}.coverage summary{cursor:pointer;font-weight:600;color:var(--ink);width:max-content;max-width:100%}.coverage-content{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-top:14px}.coverage p{margin:6px 0 10px}.coverage ul{margin:8px 0;padding-left:18px}.coverage code{font:12px var(--mono);overflow-wrap:anywhere}.inventory{padding:22px 24px}.section-heading{display:flex;align-items:baseline;justify-content:space-between;gap:16px;margin-bottom:16px}.section-heading h2{margin:0;font-size:17px}.section-heading p{margin:0;font-size:12px;color:var(--muted)}.table-scroll{overflow:auto;max-height:65vh;border:1px solid var(--line);border-radius:5px;margin-bottom:28px}table{border-collapse:collapse;width:100%;font-size:13px;text-align:left}th{position:sticky;top:0;background:#f3f6fa;z-index:1;color:var(--muted);font-size:12px;font-weight:600;white-space:nowrap}td,th{padding:10px 12px;border-bottom:1px solid #e6ecf3;vertical-align:top}tbody tr:last-child td{border-bottom:0}td code{font:12px/1.55 var(--mono);overflow-wrap:anywhere}td .subtle{display:block}.mono{font-family:var(--mono);font-size:12px}.path{max-width:450px;overflow-wrap:anywhere}.visually-hidden{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}.state-tag{display:inline-block;border:1px solid var(--line);border-radius:4px;padding:1px 6px;font-size:11px;white-space:nowrap}.muted{color:var(--muted)}.inventory details{margin-top:16px}.inventory summary{cursor:pointer}.inventory details .table-scroll{margin-top:12px}.footer-note{margin-top:16px;color:var(--muted);font-size:12px}
@media(min-width:1650px){.workspace,.coverage{max-width:1552px}}
@media(max-width:1600px){.workspace{margin-left:24px;margin-right:24px}.coverage{margin-left:24px;margin-right:24px}}
@media(max-width:900px){.detail{padding:22px}.findings-workspace{grid-template-columns:minmax(260px,36%) minmax(0,1fr)}.owner{grid-template-columns:1fr}.topbar{padding:14px 20px}.filters{flex-wrap:wrap}.filters select{max-width:none;width:100%}}
@media(max-width:760px){.topbar{align-items:flex-start;padding:14px 16px;gap:10px}.top-actions{flex-direction:column;align-items:flex-end;gap:5px}.top-actions .subtle{display:none}.scope{padding:16px 16px 0}.scope-line{gap:4px}.scope-line p{width:100%;font-size:12px}.workspace{margin:16px}.findings-workspace{display:block;min-height:0}.queue{border-right:0;border-bottom:1px solid var(--line)}.queue-head{padding:14px}.filters{flex-wrap:nowrap}.filters select{max-width:115px;width:auto}.finding-list{min-height:0;max-height:280px}.finding{padding:12px 14px 12px 11px}.detail{padding:22px 18px}.detail h2{font-size:19px}.coverage{margin:0 16px 20px}.coverage-content{grid-template-columns:1fr;gap:4px}.inventory{padding:18px 14px}.section-heading{align-items:flex-start;flex-direction:column;gap:4px}.tabs{gap:20px}.brand{font-size:15px}.eyebrow{font-size:10px}.top-actions button{font-size:12px;padding:7px 9px}}
@media print{body{background:white}.top-actions,.filters,.tabs{display:none}.workspace{border:0;margin:12px 0;overflow:visible}.findings-workspace{display:block}.queue{display:none}.detail{padding:0}.coverage{margin:0}.coverage details>div{display:block}button{display:none}}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{scroll-behavior:auto!important;animation:none!important;transition:none!important}}
</style>
</head>
<body>
<header class="topbar">
  <div class="identity"><div class="mark" aria-hidden="true">as</div><div><div class="brand">AddonScope</div><div class="eyebrow">Blender environment diagnostics</div></div></div>
  <div class="top-actions"><span class="subtle" id="path-status"></span><button class="primary" id="download">Download JSON</button></div>
</header>
<div class="scope">
  <div class="scope-line"><h1>Environment report</h1><p id="scope-summary"></p></div>
  <div class="tabs" role="tablist" aria-label="Report views">
    <button class="tab" role="tab" id="findings-tab" aria-controls="findings-panel" aria-selected="true">Findings <span id="finding-count"></span></button>
    <button class="tab" role="tab" id="inventory-tab" aria-controls="inventory-panel" aria-selected="false" tabindex="-1">Inventory <span id="addon-count"></span></button>
  </div>
</div>
<main>
  <section class="workspace findings-workspace" id="findings-panel" role="tabpanel" aria-labelledby="findings-tab">
    <aside class="queue" aria-label="Finding selection">
      <div class="queue-head"><h2>Review findings</h2><div class="filters"><label class="visually-hidden" for="search">Search findings</label><input id="search" class="search" type="search" placeholder="Search findings…" autocomplete="off"><label class="visually-hidden" for="severity">Filter severity</label><select id="severity"><option value="all">All severities</option><option value="error">Errors</option><option value="warning">Warnings</option><option value="info">Information</option></select></div><div class="list-info" id="list-info" role="status" aria-live="polite"></div></div>
      <div class="finding-list" id="finding-list" aria-label="Findings"></div>
    </aside>
    <article class="detail" id="detail" aria-label="Selected finding"></article>
  </section>
  <section class="workspace inventory" id="inventory-panel" role="tabpanel" aria-labelledby="inventory-tab" hidden>
    <div class="section-heading"><h2>Installed add-ons</h2><p>Discovered from the inspected roots. “Unknown” means activation was not captured.</p></div>
    <div id="addon-table"></div>
    <div class="section-heading"><h2>Python distributions</h2><p>Metadata candidates; a wheel in an add-on is not proof that it is loaded.</p></div>
    <div id="distribution-table"></div>
    <details><summary id="loaded-summary">Loaded modules</summary><div id="loaded-table"></div></details>
  </section>
  <div class="coverage"><details open><summary>Scope, evidence and limitations</summary><div class="coverage-content"><div><p><strong>Inspected roots</strong></p><ul id="roots"></ul><p id="environment"></p><p id="timestamp"></p></div><div><p>This report records manifest and Python-package metadata, potential cross-owner collisions, and import paths captured when available. An observed metadata difference is not by itself a reproduced add-on failure.</p><p>Scene-dependent behavior, UI callbacks, dynamically imported packages and native-library interactions can require a separate reproduction. No findings does not establish that all add-ons work together.</p><p id="privacy-note"></p></div></div></details></div>
</main>
<noscript><p style="padding:24px">This report needs JavaScript to display its embedded diagnostic data. It does not make network requests. Use the companion JSON report if scripting is unavailable.</p></noscript>
<script type="application/json" id="report-data">__REPORT_DATA__</script>
<script>
'use strict';
const data=JSON.parse(document.getElementById('report-data').textContent);
const $=id=>document.getElementById(id);
const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=String(text);return n;};
const findings=data.findings||[],addons=data.addons||[],dists=data.distributions||[];
let selected=findings.length?0:-1;
const severityText={error:'Error',warning:'Warning',info:'Information'},severityIcon={error:'×',warning:'△',info:'i'};
function severityBadge(value){const n=el('span','severity '+(Object.hasOwn(severityText,value)?value:'info'));n.append(el('span',null,severityIcon[value]||'i'),document.createTextNode(severityText[value]||value));return n;}
function displayOwner(owner){const a=addons.find(a=>a.id===owner||a.module===owner);return a?a.name:owner;}
function empty(target,title,body,reset){const n=el('div','empty');n.append(el('strong',null,title),el('p',null,body));if(reset){const b=el('button',null,'Clear filters');b.addEventListener('click',()=>{$('search').value='';$('severity').value='all';renderList();$('search').focus();});n.append(b);}target.append(n);}
function renderDetail(index){const pane=$('detail');pane.replaceChildren();if(index<0){empty(pane,findings.length?'Choose a finding':'No findings in this scan',findings.length?'Select an item to inspect its owners, evidence and suggested next step.':'Review the inventory and scan coverage below. Static metadata cannot rule out runtime conflicts.');return;}
 const f=findings[index];const header=el('header','detail-header'),meta=el('div','row-meta');meta.append(severityBadge(f.severity),el('span','state-tag',f.confidence==='potential'?'Potential conflict':'Observed evidence'),el('code','subtle',f.code));header.append(meta,el('h2',null,f.title),el('p',null,f.summary));pane.append(header);
 const owners=f.owners||[];if(owners.length){pane.append(el('h3',null,'Affected owners'));const list=el('div','owner-list');owners.forEach(id=>{const a=addons.find(a=>a.id===id||a.module===id);const row=el('div','owner'),identity=el('div');identity.append(el('strong',null,a?a.name:id));if(a)identity.append(el('span','subtle',[a.version||'Version not recorded',a.enabled===true?'Enabled':a.enabled===false?'Disabled':'Activation unknown'].join(' · ')));const location=el('div');if(a){location.append(el('code',null,a.module||a.id),el('code',null,a.path));}else{location.append(el('code',null,id));}row.append(identity,location);list.append(row);});pane.append(list);}
 (f.comparison||[]).forEach(group=>{pane.append(el('h3',null,'Dependency comparison · '+group.package));pane.append(makeTable(['Owner','Supplied version','Source'],group.providers.map(p=>[displayOwner(p.owner),p.version,p.source])));const imports=Object.entries(group.loaded||{});if(imports.length){const d=el('details');d.append(el('summary',null,'Captured import paths ('+imports.length+')'));d.append(makeTable(['Module','Loaded from'],imports.map(([name,path])=>[name,pathCell(path)])));pane.append(d);}else pane.append(el('p','muted','Import path not captured. Scan after using the add-ons, or inspect a fresh-process test.'));pane.append(el('p','footer-note','Supplied versions are metadata candidates, not proof of the loaded version.'));});
 pane.append(el('h3',null,'Evidence'));const evidence=f.evidence||[];if(evidence.length){const list=el('ul','evidence');evidence.forEach(value=>list.append(el('li',null,value)));pane.append(list);}else{pane.append(el('p','muted','No additional evidence was captured.'));}
 const related=dists.filter(d=>owners.includes(d.owner));if(related.length){const disclosure=el('details');disclosure.style.marginTop='20px';disclosure.append(el('summary',null,'Package candidates from these owners ('+related.length+')'));disclosure.append(makeTable(['Package','Version','Source'],related.map(d=>[d.name,d.version,d.source+' · '+d.owner])));pane.append(disclosure);}
 if(f.advice){pane.append(el('h3',null,'Suggested next step'));const next=el('div','next-step');next.append(el('p',null,f.advice));pane.append(next);}pane.append(el('p','footer-note',f.confidence==='potential'?'This is a candidate to investigate. Confirm it with a controlled reproduction before changing your installation.':'The evidence above describes this scan. It does not imply a reproduced failure unless the evidence explicitly records one.'));
}
function filtered(){const q=$('search').value.trim().toLocaleLowerCase(),s=$('severity').value;return findings.map((f,i)=>({f,i})).filter(({f})=>(s==='all'||f.severity===s)&&(!q||[f.title,f.summary,f.code,...(f.owners||[]).map(displayOwner),...(f.evidence||[])].join(' ').toLocaleLowerCase().includes(q)));}
function select(index,focus=false){selected=index;renderList(false);renderDetail(index);if(focus){const b=$('finding-list').querySelector('[data-index="'+index+'"]');if(b)b.focus();}}
function renderList(updateDetail=true){const list=$('finding-list'),rows=filtered();list.replaceChildren();$('list-info').textContent=rows.length+' of '+findings.length+' findings';
 if(!rows.length){empty(list,findings.length?'No matching findings':'Nothing flagged',findings.length?'Try another search or severity.':'The inspected metadata produced no findings. Coverage and runtime limits still apply.',findings.length>0);if(updateDetail){if(findings.length)emptyDetailFiltered();else renderDetail(-1);}return;}
 if(!rows.some(r=>r.i===selected))selected=rows[0].i;
 rows.forEach(({f,i})=>{const button=el('button','finding');button.type='button';button.dataset.index=i;button.setAttribute('aria-pressed',String(i===selected));button.setAttribute('aria-controls','detail');const meta=el('span','row-meta');meta.append(severityBadge(f.severity),el('span','subtle',f.confidence==='potential'?'Potential':'Observed'));button.append(meta,el('span','finding-title',f.title),el('span','finding-owner',(f.owners||[]).map(displayOwner).join(' · ')||f.code));button.addEventListener('click',()=>select(i));button.addEventListener('keydown',event=>{const keys=['ArrowDown','ArrowUp','Home','End'];if(!keys.includes(event.key))return;event.preventDefault();const at=rows.findIndex(r=>r.i===i);const next=event.key==='Home'?0:event.key==='End'?rows.length-1:Math.max(0,Math.min(rows.length-1,at+(event.key==='ArrowDown'?1:-1)));select(rows[next].i,true);});list.append(button);});if(updateDetail)renderDetail(selected);
}
function emptyDetailFiltered(){const p=$('detail');p.replaceChildren();empty(p,'No matching findings','Clear the filters to return to the complete finding list.');}
function makeTable(headers,rows){const wrap=el('div','table-scroll'),table=el('table'),head=el('thead'),tr=el('tr');headers.forEach(label=>{const th=el('th',null,label);th.scope='col';tr.append(th);});head.append(tr);table.append(head);const body=el('tbody');rows.forEach(values=>{const row=el('tr');values.forEach(value=>{const td=el('td');if(value instanceof Node)td.append(value);else td.textContent=String(value??'');row.append(td);});body.append(row);});table.append(body);wrap.append(table);return wrap;}
function pathCell(value){const n=el('code','path',value);return n;}
function populateInventory(){if(addons.length){$('addon-table').append(makeTable(['Add-on / module','Version','Activation','Location'],addons.map(a=>{const identity=el('div');identity.append(el('strong',null,a.name),el('code','subtle',a.module||a.id));return[identity,a.version||'—',a.enabled===true?'Enabled':a.enabled===false?'Disabled':'Unknown',pathCell(a.path)];})));}else empty($('addon-table'),'No add-ons discovered','Check the inspected roots below.');
 if(dists.length){$('distribution-table').append(makeTable(['Distribution','Version','Owner / source','Location'],dists.map(d=>{const owner=el('div');owner.append(el('span',null,displayOwner(d.owner)),el('span','subtle',d.source));return[d.name,d.version,owner,pathCell(d.path)];})));}else empty($('distribution-table'),'No package metadata discovered','Add-ons may still bundle code without distribution metadata.');
 const loaded=Object.entries(data.loaded||{});$('loaded-summary').textContent='Captured import paths ('+loaded.length+')';if(loaded.length)$('loaded-table').append(makeTable(['Module','Loaded from'],loaded.map(([name,path])=>[name,pathCell(path)])));else $('loaded-table').append(el('p','muted','No runtime module snapshot was supplied. A CLI-only static scan cannot observe imports in another Blender process.'));
}
const tabs=[$('findings-tab'),$('inventory-tab')];function activateTab(index){tabs.forEach((tab,i)=>{tab.setAttribute('aria-selected',String(i===index));tab.tabIndex=i===index?0:-1;$(tab.getAttribute('aria-controls')).hidden=i!==index;});}
tabs.forEach((tab,i)=>{tab.addEventListener('click',()=>activateTab(i));tab.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const index=event.key==='Home'?0:event.key==='End'?1:1-i;activateTab(index);tabs[index].focus();});});
$('search').addEventListener('input',()=>renderList());$('severity').addEventListener('change',()=>renderList());
$('finding-count').textContent=findings.length;$('addon-count').textContent=addons.length;
const errors=findings.filter(f=>f.severity==='error').length,warnings=findings.filter(f=>f.severity==='warning').length;
$('scope-summary').textContent=addons.length+(addons.length===1?' add-on · ':' add-ons · ')+dists.length+(dists.length===1?' package candidate · ':' package candidates · ')+errors+(errors===1?' error · ':' errors · ')+warnings+(warnings===1?' warning':' warnings');
$('path-status').textContent=data.paths_redacted?'Scan paths redacted':'Full paths included';
$('privacy-note').textContent=data.paths_redacted?'Scan-root and home-directory prefixes were replaced with labels. Other content can still be identifying; review before sharing.':'This report includes full filesystem paths. Review it before sharing publicly.';
(data.roots||[]).forEach(root=>{const li=el('li');li.append(el('code',null,root));$('roots').append(li);});if(!(data.roots||[]).length)$('roots').append(el('li',null,'No scan roots were recorded.'));
$('timestamp').textContent='Captured '+(data.created_at||'at an unrecorded time')+' · Report schema '+(data.schema_version||1);
const env=data.environment||{};$('environment').textContent=Object.keys(env).length?'Environment: '+Object.entries(env).map(([k,v])=>k+' = '+(typeof v==='object'?JSON.stringify(v):v)).join(' · '):'Environment details were not captured.';
$('download').addEventListener('click',()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)+'\n'],{type:'application/json'}));const a=el('a');a.href=url;a.download='addonscope-report.json';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);});
populateInventory();renderList();
</script>
</body></html>
'''
