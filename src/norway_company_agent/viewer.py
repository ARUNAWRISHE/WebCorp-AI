"""Self-contained HTML viewer for a run: search, filter, compare and verify every fact on desktop or mobile."""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .nace import division_label

FIELD_LABELS = {
    "legal_name": "Legal name", "legal_form": "Legal form / capital", "registry_status": "Registry status", "business_address": "Address",
    "industry": "Industry (NACE)", "business_purpose": "Registered activity", "founded_date": "Founded", "registered_employees": "Registered employees",
    "public_brand_name": "Public brand", "annual_account_metric": "Accounts", "annual_account_filing": "Annual account filing",
    "filed_account_years": "Filed account years", "role": "Role", "group_relation": "Group", "registered_workplace": "Registered workplace",
    "website_address": "Address on website", "registry_website": "Registry-declared website", "official_website": "Official website (verified)", "website_description": "Website description",
    "social_profile": "Social profile", "knowledge_base_entry": "Wikidata", "job_posting": "Job posting", "careers_page": "Careers page",
    "news_item": "News / press", "registry_event": "Registry event",
    "food_safety_inspection": "Food-safety inspection (Mattilsynet)", "public_approval": "Public approval",
}
METRIC_LABELS = {"revenue": "Revenue", "operating_expenses": "Operating expenses", "payroll_expenses": "Payroll", "operating_result": "Operating result",
                 "net_financial_items": "Net financial items", "profit_before_tax": "Profit before tax", "annual_result": "Annual result",
                 "total_assets": "Total assets", "cash_and_bank": "Cash and bank", "equity": "Equity", "total_debt": "Total debt"}


def _money(value: Any) -> str:
    try:
        return f"{float(value):,.0f}".replace(",", " ")
    except (TypeError, ValueError):
        return str(value)


def _value_text(claim: dict[str, Any]) -> tuple[str, str]:
    """Return (label, value text)."""
    field = claim["field"]
    value = claim.get("value")
    label = FIELD_LABELS.get(field, field)
    if value is None:
        return label, claim.get("note") or ""
    if field == "annual_account_metric":
        _, period, metric = (claim["key"].split(":") + ["", ""])[:3]
        scope = claim.get("scope", "company")
        return f"{METRIC_LABELS.get(metric, metric)} ({'group' if scope == 'group' else 'company'})", f"{claim.get('unit') or 'NOK'} {_money(value)}"
    if isinstance(value, dict):
        if field == "role":
            return value.get("role") or label, value.get("name") or ""
        if field == "legal_form":
            if "amount" in value:
                return "Share capital", f"{value.get('currency') or ''} {_money(value.get('amount'))}"
            return label, f"{value.get('description') or ''} ({value.get('code')})"
        if field == "business_address":
            return f"{label} ({claim['key']})", value.get("formatted") or ""
        if field == "industry":
            division = division_label(value.get("code"))
            return label, f"{value.get('code')} {value.get('description') or ''}" + (f" · {division}" if division else "")
        if field == "registry_status":
            return label, value.get("status") or ""
        if field == "registered_workplace":
            address = (value.get("address") or {}).get("formatted") or ""
            extra = f" · {value.get('registered_employees')} employees" if value.get("registered_employees") else ""
            return label, f"{value.get('name')} ({value.get('organisation_number')}) · {address}{extra}"
        if field == "group_relation":
            return f"Group: {value.get('relation')}", f"{value.get('name')} ({value.get('organisation_number')})"
        if field == "job_posting":
            bits = [value.get("title") or "", value.get("location") or "", f"expires {value['expires']}" if value.get("expires") else ""]
            return label, " · ".join(bit for bit in bits if bit)
        if field == "news_item":
            return label, f"{value.get('date')} · {value.get('title')}"
        if field in {"social_profile"}:
            return f"{label}: {value.get('platform')}", value.get("url") or ""
        if field == "knowledge_base_entry":
            return label, f"{value.get('id')} · {value.get('label') or ''} {('— ' + value['description']) if value.get('description') else ''}"
        if field == "annual_account_filing":
            return f"Filing ({value.get('scope')})", f"Year {value.get('year')}" + (" · audit opted out" if value.get("audit_opted_out") else "")
        if field == "filed_account_years":
            return label, ", ".join(value.get("years") or [])
        if field == "food_safety_inspection":
            return f"{label}", f"{value.get('establishment')} · {value.get('latest_inspection_date')} · {value.get('result')} ({value.get('inspections_on_record')} inspections)"
        if field == "public_approval":
            if "approved" in value:
                areas = ", ".join(f"{item.get('subject_area')} (class {item.get('grade')})" for item in (value.get("approval_areas") or [])[:4])
                return value.get("register") or label, f"{'Approved' if value.get('approved') else 'Not approved'} until {value.get('valid_until')} · {areas}"
            return value.get("register") or label, str(value.get("status") or "")
        if field == "registry_event":
            return label, f"{value.get('date')} · {value.get('event')}"
        if field == "careers_page":
            return label, value.get("url") or ""
        if field == "website_address":
            return label, ", ".join(str(v) for v in value.values())
        if field == "legal_name" and "former_name" in value:
            return "Former name", f"{value.get('former_name')} (until {str(value.get('to') or '')[:10]})"
        return label, json.dumps(value, ensure_ascii=False)[:300]
    return label, str(value)


def _link(claim: dict[str, Any]) -> str | None:
    value = claim.get("value")
    if isinstance(value, str) and value.startswith("http"):
        return value
    if isinstance(value, dict):
        for key in ("url", "wikipedia"):
            if isinstance(value.get(key), str) and value[key].startswith("http"):
                return value[key]
    return None


def view_model(envelope: dict[str, Any]) -> dict[str, Any]:
    evidence = {item["id"]: item for item in envelope.get("evidence", [])}
    ev_index: dict[str, int] = {}
    ev_rows: list[list[Any]] = []
    claims = []
    for claim in envelope.get("claims", []):
        refs = []
        for eid in claim.get("evidence_ids") or []:
            item = evidence.get(eid)
            if not item:
                continue
            if eid not in ev_index:
                ev_index[eid] = len(ev_rows)
                ev_rows.append([item.get("source_url"), item.get("retrieved_at"), (item.get("content_sha256") or "")[:12], item.get("source_class"),
                                (item.get("claim_span") or "")[:240], bool(item.get("superseded"))])
            refs.append(ev_index[eid])
        label, text = _value_text(claim)
        period = claim.get("reporting_period") or {}
        date = f"{period.get('from')} – {period.get('to')}" if period else (claim.get("effective_at") or "")
        claims.append([claim["section"], claim["field"], label, text, claim["availability"], str(date or "")[:25], refs, _link(claim),
                       bool(claim.get("stale")), claim.get("confidence")])
    company = envelope.get("company") or {}
    summary = envelope.get("summary") or {}
    return {
        "o": envelope["organisation_number"], "n": company.get("name") or envelope["organisation_number"], "f": company.get("legal_form") or "",
        "m": (company.get("municipality") or "").title(), "w": company.get("website") or "", "t": envelope["run"].get("terminal_status"),
        "s": {name: section.get("availability") for name, section in (envelope.get("sections") or {}).items()},
        "sum": summary.get("text") or "", "sm": summary.get("method") or "", "chg": summary.get("changes_text") or "", "unk": summary.get("unknowns_text") or "",
        "cl": claims, "ev": ev_rows,
        "ch": [[item["type"], item["key"], json.dumps(item.get("old_value"), ensure_ascii=False)[:160], json.dumps(item.get("new_value"), ensure_ascii=False)[:160], item.get("material")]
               for item in envelope.get("changes", [])],
        "rq": (envelope.get("operations") or {}).get("requests"),
    }


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Signalpost Company Profiles</title>
<style>
:root{--bg:#f6f7f9;--panel:#fff;--ink:#1b1f24;--muted:#5d6672;--line:#e1e4e8;--accent:#1f5fbf;--ok:#1a7f37;--warn:#9a6700;--bad:#cf222e;--na:#6e7781;--chip:#eef1f4}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0d1117;--panel:#161b22;--ink:#e6edf3;--muted:#9aa4af;--line:#30363d;--accent:#58a6ff;--ok:#3fb950;--warn:#d29922;--bad:#f85149;--na:#8b949e;--chip:#21262d}}
:root[data-theme=dark]{--bg:#0d1117;--panel:#161b22;--ink:#e6edf3;--muted:#9aa4af;--line:#30363d;--accent:#58a6ff;--ok:#3fb950;--warn:#d29922;--bad:#f85149;--na:#8b949e;--chip:#21262d}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{padding:14px 16px;border-bottom:1px solid var(--line);background:var(--panel);position:sticky;top:0;z-index:5}
h1{font-size:18px;margin:0 0 4px}.meta{color:var(--muted);font-size:13px}
.controls{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
input,select,button{font:inherit;padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--ink)}
input[type=search]{flex:1 1 220px;min-width:0}button{cursor:pointer}button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
main{display:grid;grid-template-columns:minmax(260px,360px) 1fr;gap:0;min-height:calc(100vh - 120px)}
#list{border-right:1px solid var(--line);overflow:auto;max-height:calc(100vh - 120px)}
.item{padding:10px 16px;border-bottom:1px solid var(--line);cursor:pointer;display:flex;gap:10px;align-items:flex-start}
.item:hover,.item.active{background:var(--chip)}.item .name{font-weight:600}.item .sub{color:var(--muted);font-size:12.5px}
.dots{display:flex;gap:3px;margin-top:5px}.dot{width:9px;height:9px;border-radius:50%}
#detail{padding:16px 20px;overflow:auto;max-height:calc(100vh - 120px)}
.badge{display:inline-block;padding:1px 7px;border-radius:10px;font-size:12px;font-weight:600;color:#fff;white-space:nowrap}
.available{background:var(--ok)}.ambiguous{background:var(--warn)}.blocked{background:#8250df}.failed{background:var(--bad)}.not_available,.not_applicable{background:var(--na)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:14px}
.card h2{font-size:16px;margin:0 0 8px;display:flex;justify-content:space-between;gap:8px;align-items:center}
table{width:100%;border-collapse:collapse;font-size:14px}td{padding:6px 6px;border-top:1px solid var(--line);vertical-align:top}
td.l{color:var(--muted);width:30%}td.v{word-break:break-word}.src a{font-size:12px;color:var(--accent)}a{color:var(--accent)}
.src details{font-size:12px;color:var(--muted)}.src summary{cursor:pointer}.stale{font-size:11px;color:var(--warn)}
.summary p{margin:0 0 8px}.unk{color:var(--muted);font-size:13.5px}
.cmp{overflow:auto}.cmp table td{min-width:160px}.back{display:none}
@media (max-width:760px){main{grid-template-columns:1fr}#list{max-height:none;border-right:0}#detail{display:none;max-height:none;padding:12px}
 body.show-detail #list{display:none}body.show-detail #detail{display:block}.back{display:inline-block;margin-bottom:10px}td.l{width:38%}}
</style></head><body>
<header><h1>Signalpost company profiles</h1><div class="meta" id="meta"></div>
<div class="controls"><input type="search" id="q" placeholder="Search name, org number, municipality…" aria-label="Search">
<select id="f"><option value="">All companies</option><option value="web">Verified website</option><option value="hiring">Hiring</option><option value="activity">Dated activity</option><option value="changes">Changed since last run</option><option value="ambiguous">Has ambiguous field</option><option value="failed">Has failed field</option></select>
<button id="cmpBtn" title="Compare checked companies">Compare (<span id="cmpN">0</span>)</button></div></header>
<main><div id="list" role="list"></div><div id="detail"></div></main>
<script>
const DATA=__DATA__;const REPORT=__REPORT__;
const SECTION_TITLES={legal_identity:"Legal identity and public brand",financials:"Annual accounts and history",leadership:"Leadership and group",workplaces:"Registered workplaces",web_presence:"Website and company-owned profiles",hiring:"Hiring",activity:"Dated public activity",assessments:"Inspections, approvals and ratings"};
const ORDER=Object.keys(SECTION_TITLES);const sel=new Set();let current=null;
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const color=st=>({available:"var(--ok)",ambiguous:"var(--warn)",blocked:"#8250df",failed:"var(--bad)"}[st]||"var(--na)");
document.getElementById("meta").textContent=`Run ${REPORT.run_id} · ${REPORT.emitted_envelopes} companies · completed ${REPORT.completed_at} · ${REPORT.elapsed_seconds}s · ${REPORT.requests.total} requests · third-party cost $${REPORT.third_party_cost_usd}`;
function match(c,q,f){if(q){const h=(c.n+" "+c.o+" "+c.m+" "+c.w).toLowerCase();if(!h.includes(q))return false}
 if(f==="web")return c.s.web_presence==="available"&&c.w;if(f==="hiring")return c.s.hiring==="available";if(f==="activity")return c.s.activity==="available";
 if(f==="changes")return c.ch.length>0;if(f==="ambiguous")return c.cl.some(x=>x[4]==="ambiguous");if(f==="failed")return c.cl.some(x=>x[4]==="failed");return true}
function renderList(){const q=document.getElementById("q").value.trim().toLowerCase(),f=document.getElementById("f").value;const L=document.getElementById("list");
 const rows=DATA.filter(c=>match(c,q,f));L.innerHTML=rows.slice(0,600).map(c=>`<div class="item${current===c.o?" active":""}" role="listitem" data-o="${c.o}">
 <input type="checkbox" aria-label="Select for comparison" data-c="${c.o}" ${sel.has(c.o)?"checked":""}><div><div class="name">${esc(c.n)}</div>
 <div class="sub">${c.o} · ${esc(c.f)} · ${esc(c.m)}</div><div class="dots">${ORDER.map(s=>`<span class="dot" title="${SECTION_TITLES[s]}: ${c.s[s]}" style="background:${color(c.s[s])}"></span>`).join("")}</div></div></div>`).join("")+(rows.length>600?`<div class="item sub">${rows.length-600} more — refine the search</div>`:"")||'<div class="item sub">No companies match.</div>'}
function srcHtml(c,refs){return refs.map(i=>{const e=c.ev[i];if(!e)return"";return `<details><summary>${esc(e[3])} · ${esc((e[1]||"").slice(0,10))}${e[5]?" · earlier evidence":""}</summary>
 <a href="${esc(e[0])}" target="_blank" rel="noopener noreferrer">${esc(e[0])}</a><br>sha256 ${esc(e[2])}… ${e[4]?"<br>“"+esc(e[4])+"”":""}</details>`}).join("")}
function renderDetail(o){const c=DATA.find(x=>x.o===o);if(!c)return;current=o;document.body.classList.add("show-detail");const D=document.getElementById("detail");
 let h=`<button class="back" onclick="document.body.classList.remove('show-detail')">← Back to list</button>
 <div class="card"><h2><span>${esc(c.n)}</span><span class="badge ${c.t==="completed"?"available":"failed"}">${esc(c.t)}</span></h2>
 <div class="meta">Org. no. ${c.o} · <a href="https://virksomhet.brreg.no/nb/oppslag/enheter/${c.o}" target="_blank" rel="noopener">Brønnøysund record</a>${c.w?` · <a href="${esc(c.w)}" target="_blank" rel="noopener">${esc(c.w)}</a>`:""}</div>
 <div class="summary" style="margin-top:10px"><p>${esc(c.sum)}</p>${c.chg?`<p><b>Changes:</b> ${esc(c.chg)}</p>`:""}${c.unk?`<p class="unk">${esc(c.unk)}</p>`:""}<div class="meta">Summary method: ${esc(c.sm)} · every sentence cites claims below</div></div></div>`;
 if(c.ch.length){h+=`<div class="card"><h2>Changes since previous run</h2><table>${c.ch.map(x=>`<tr><td class="l">${esc(x[0].replace(/_/g," "))}${x[4]?"":" (minor)"}</td><td class="v">${esc(x[1])}<br><span class="meta">${esc(x[2])} → ${esc(x[3])}</span></td></tr>`).join("")}</table></div>`}
 for(const s of ORDER){const rows=c.cl.filter(x=>x[0]===s);if(!rows.length)continue;
  h+=`<div class="card"><h2><span>${SECTION_TITLES[s]}</span><span class="badge ${c.s[s]}">${esc((c.s[s]||"").replace(/_/g," "))}</span></h2><table>`+rows.map(x=>{
   const val=x[7]&&x[4]==="available"?`<a href="${esc(x[7])}" target="_blank" rel="noopener noreferrer">${esc(x[3])}</a>`:esc(x[3]);
   return `<tr><td class="l">${esc(x[2])}${x[5]?`<br><span class="meta">${esc(x[5])}</span>`:""}</td><td class="v">${x[4]!=="available"?`<span class="badge ${x[4]}">${esc(x[4].replace(/_/g," "))}</span> `:""}${val}${x[8]?' <span class="stale">(stale — carried from previous run)</span>':""}<div class="src">${srcHtml(c,x[6])}</div></td></tr>`}).join("")+`</table></div>`}
 D.innerHTML=h;D.scrollTop=0;renderList()}
function renderCompare(){const cs=DATA.filter(c=>sel.has(c.o));if(cs.length<2){alert("Tick 2–4 companies to compare.");return}
 const pick=(c,f,k)=>{const r=c.cl.find(x=>x[1]===f&&x[4]==="available"&&(!k||x[2].startsWith(k)));return r?esc(r[3]):'<span class="meta">—</span>'};
 const latest=(c,m)=>{const r=c.cl.filter(x=>x[1]==="annual_account_metric"&&x[2].startsWith(m)&&x[2].includes("(company)")).sort((a,b)=>b[5].localeCompare(a[5]))[0];return r?esc(r[3])+`<br><span class="meta">${esc(r[5])}</span>`:'<span class="meta">—</span>'};
 const rows=[["Legal form",c=>pick(c,"legal_form")],["Status",c=>pick(c,"registry_status")],["Industry",c=>pick(c,"industry")],["Employees",c=>pick(c,"registered_employees")],
 ["Revenue",c=>latest(c,"Revenue")],["Annual result",c=>latest(c,"Annual result")],["Equity",c=>latest(c,"Equity")],["Website",c=>c.w?`<a href="${esc(c.w)}" target="_blank" rel="noopener">${esc(c.w)}</a>`:'<span class="meta">—</span>'],
 ["Active jobs",c=>String(c.cl.filter(x=>x[1]==="job_posting"&&x[4]==="available").length)],["Workplaces",c=>String(c.cl.filter(x=>x[1]==="registered_workplace"&&x[4]==="available").length)],
 ["Social profiles",c=>String(c.cl.filter(x=>x[1]==="social_profile"&&x[4]==="available").length)],["Latest news",c=>{const r=c.cl.filter(x=>x[1]==="news_item"&&x[4]==="available").sort((a,b)=>b[5].localeCompare(a[5]))[0];return r?esc(r[3]):'<span class="meta">—</span>'}]];
 document.body.classList.add("show-detail");document.getElementById("detail").innerHTML=`<button class="back" onclick="document.body.classList.remove('show-detail')">← Back to list</button><div class="card cmp"><h2>Comparison</h2><table><tr><td class="l"></td>${cs.map(c=>`<td><b>${esc(c.n)}</b><br><span class="meta">${c.o}</span></td>`).join("")}</tr>${rows.map(([l,f])=>`<tr><td class="l">${l}</td>${cs.map(c=>`<td>${f(c)}</td>`).join("")}</tr>`).join("")}</table></div>`}
document.getElementById("list").addEventListener("click",e=>{const cb=e.target.closest("input[data-c]");if(cb){cb.checked?sel.add(cb.dataset.c):sel.delete(cb.dataset.c);if(sel.size>4){sel.delete(cb.dataset.c);cb.checked=false}document.getElementById("cmpN").textContent=sel.size;return}
 const it=e.target.closest(".item[data-o]");if(it)renderDetail(it.dataset.o)});
document.getElementById("q").addEventListener("input",renderList);document.getElementById("f").addEventListener("change",renderList);document.getElementById("cmpBtn").addEventListener("click",renderCompare);
renderList();if(DATA.length&&window.innerWidth>760)renderDetail(DATA[0].o);
</script></body></html>"""


def build_viewer(envelopes: list[dict[str, Any]], report: dict[str, Any], path: str) -> None:
    data = [view_model(envelope) for envelope in envelopes]
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    report_payload = json.dumps({key: report.get(key) for key in ("run_id", "emitted_envelopes", "completed_at", "elapsed_seconds", "requests", "third_party_cost_usd")},
                                ensure_ascii=False).replace("</", "<\\/")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(TEMPLATE.replace("__DATA__", payload).replace("__REPORT__", report_payload), encoding="utf-8")


__all__ = ["build_viewer", "view_model", "html"]
