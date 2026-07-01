#!/usr/bin/env python3
"""
Prime Video Watcher v2 - multi-region
Primary: TMDB (all regions) -> in-page region dropdown
Cross-check: Watchmode changes (US, IT, UK) -> flags/confirms titles
Outputs: docs/data.json, docs/index.html, state.json
"""
import os, sys, json, time, datetime as dt, smtplib
from email.mime.text import MIMEText
from email.utils import formataddr
from urllib import request, parse, error

TMDB_KEY = os.environ.get("TMDB_API_KEY", "").strip()
WM_KEY   = os.environ.get("WATCHMODE_API_KEY", "").strip()

REGIONS = {"US":"United States","IT":"Italia","GB":"United Kingdom",
           "DE":"Deutschland","FR":"France","ES":"Espana","CA":"Canada"}
WM_REGIONS = {"US":"US","IT":"IT","GB":"UK"}   # Watchmode uses UK not GB

TMDB_PROVIDERS = "9|2100"
TMDB_BASE = "https://api.themoviedb.org/3"
WM_BASE   = "https://api.watchmode.com/v1"
IMG_BASE  = "https://image.tmdb.org/t/p/w200"
LANG="en-US"; MAX_PAGES=6
STATE_FILE="state.json"; OUT_JSON="docs/data.json"; OUT_HTML="docs/index.html"

SMTP_HOST=(os.environ.get("SMTP_HOST") or "smtp.gmail.com").strip()
SMTP_PORT=int((os.environ.get("SMTP_PORT") or "587").strip())
SMTP_USER=os.environ.get("SMTP_USER","").strip()
SMTP_PASS=os.environ.get("SMTP_PASS","").strip()
MAIL_TO=os.environ.get("MAIL_TO","").strip()
PAGE_URL=os.environ.get("PAGE_URL","").strip()

if not TMDB_KEY:
    print("ERROR: TMDB_API_KEY not set.", file=sys.stderr); sys.exit(1)
USE_BEARER = TMDB_KEY.startswith("eyJ") or len(TMDB_KEY) > 60

def http_json(url, headers=None, tries=4):
    req=request.Request(url, headers=headers or {})
    for i in range(tries):
        try:
            with request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except error.HTTPError as e:
            if e.code==429: time.sleep(2+i*2); continue
            raise
        except error.URLError:
            time.sleep(2)
    raise RuntimeError(f"Request failed: {url}")

def tmdb_get(path, params):
    params=dict(params)
    headers={"Accept":"application/json","User-Agent":"prime-watcher/2.0"}
    if USE_BEARER: headers["Authorization"]=f"Bearer {TMDB_KEY}"
    else: params["api_key"]=TMDB_KEY
    return http_json(f"{TMDB_BASE}{path}?{parse.urlencode(params)}", headers)

def wm_get(path, params):
    params=dict(params); params["apiKey"]=WM_KEY
    return http_json(f"{WM_BASE}{path}?{parse.urlencode(params)}")

def discover(media_type, region):
    out=[]; sort="primary_release_date.desc" if media_type=="movie" else "first_air_date.desc"
    today=dt.date.today().isoformat()
    for page in range(1, MAX_PAGES+1):
        params={"language":LANG,"watch_region":region,
                "with_watch_providers":TMDB_PROVIDERS,
                "with_watch_monetization_types":"flatrate|ads",
                "sort_by":sort,"page":page}
        if media_type=="movie": params["primary_release_date.lte"]=today
        else: params["first_air_date.lte"]=today
        data=tmdb_get(f"/discover/{media_type}", params)
        for it in data.get("results",[]):
            title=it.get("title") or it.get("name") or "-"
            date=it.get("release_date") or it.get("first_air_date") or ""
            out.append({"id":f"{media_type}:{it['id']}","tmdb_id":it["id"],
                "title":title,"type":media_type,"date":date,
                "year":date[:4] if date else "",
                "overview":(it.get("overview") or "")[:240],
                "poster":(IMG_BASE+it["poster_path"]) if it.get("poster_path") else "",
                "rating":round(it.get("vote_average") or 0,1),
                "tmdb":f"https://www.themoviedb.org/{media_type}/{it['id']}",
                "sources":["tmdb"]})
        if page>=data.get("total_pages",1): break
    return out

def watchmode_recent_prime(wm_region):
    if not WM_KEY: return set(), False
    ids=set()
    try:
        for st in ("26","387"):
            data=wm_get("/list-titles/", {"source_ids":st,"regions":wm_region,
                "sort_by":"release_date_desc","limit":100})
            for t in data.get("titles",[]):
                tid=t.get("tmdb_id")
                if tid: ids.add(int(tid))
        return ids, True
    except Exception as e:
        print(f"  Watchmode {wm_region} skip: {e}", file=sys.stderr)
        return set(), False

def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f: return json.load(f)
    except FileNotFoundError:
        return {"seen":{}, "history":[]}

def save_state(s):
    with open(STATE_FILE,"w",encoding="utf-8") as f:
        json.dump(s,f,ensure_ascii=False,indent=2)

def main():
    state=load_state(); seen=state.get("seen",{})
    first_run=len(seen)==0
    now=dt.datetime.utcnow().isoformat(timespec="seconds")+"Z"
    page_data={}; email_items=[]
    for code,label in REGIONS.items():
        print(f"Region {code} ({label})...")
        catalog=discover("movie",code)+discover("tv",code)
        wm_used=False
        if code in WM_REGIONS:
            wm_ids,wm_used=watchmode_recent_prime(WM_REGIONS[code])
            if wm_used:
                have=set(c["tmdb_id"] for c in catalog)
                for c in catalog:
                    if c["tmdb_id"] in wm_ids and "watchmode" not in c["sources"]:
                        c["sources"].append("watchmode")
                page_data.setdefault("_wm_missed",{})[code]=len(wm_ids-have)
        region_seen=seen.get(code,{}); region_first=len(region_seen)==0
        new_items=[]
        for it in catalog:
            if it["id"] not in region_seen:
                if not region_first: new_items.append(it)
                region_seen[it["id"]]={"first_seen":now}
        seen[code]=region_seen
        new_items.sort(key=lambda x:x["date"],reverse=True)
        page_data[code]={"label":label,"total":len(catalog),"new":new_items,"wm":wm_used}
        print(f"  catalog {len(catalog)}, new {len(new_items)}, watchmode={'yes' if wm_used else 'no'}")
        if code in WM_REGIONS and new_items:
            for it in new_items: email_items.append({**it,"region":code})
    total_new=sum(len(v["new"]) for k,v in page_data.items() if isinstance(v,dict) and "new" in v)
    state["seen"]=seen
    state.setdefault("history",[]).append({"date":now,"new_count":total_new})
    state["history"]=state["history"][-20:]
    save_state(state)
    write_outputs(page_data, now, first_run, state["history"])
    if email_items and not first_run: send_email(email_items)
    else: print("No email sent (first run or no new US/IT/UK titles).")
    print(f"Done. Total new across regions: {total_new}")

def write_outputs(page_data, now, first_run, history):
    os.makedirs("docs", exist_ok=True)
    payload={"generated":now,"first_run":first_run,
        "regions":{k:v for k,v in page_data.items() if not k.startswith("_")},
        "wm_missed":page_data.get("_wm_missed",{}),"history":history}
    with open(OUT_JSON,"w",encoding="utf-8") as f:
        json.dump(payload,f,ensure_ascii=False)
    with open(OUT_HTML,"w",encoding="utf-8") as f:
        f.write(PAGE_HTML)
    print(f"Wrote {OUT_JSON} and {OUT_HTML}")

def send_email(items):
    if not (SMTP_USER and SMTP_PASS and MAIL_TO):
        print("SMTP not configured: email skipped."); return
    import html as _h
    by={}
    for it in items: by.setdefault(it["region"],[]).append(it)
    blocks=[]
    for reg,its in by.items():
        rows="".join(
            f'<li style="margin:6px 0"><b>{_h.escape(x["title"])}</b> '
            f'<span style="color:#888">({"Series" if x["type"]=="tv" else "Film"}'
            f'{" - "+x["year"] if x["year"] else ""}'
            f'{" - *"+str(x["rating"]) if x["rating"] else ""})</span>'
            f'{" - Watchmode ok" if "watchmode" in x.get("sources",[]) else ""}</li>'
            for x in its)
        blocks.append(f'<h3 style="margin:16px 0 6px">{reg} - {len(its)} new</h3>'
                      f'<ul style="list-style:none;padding:0">{rows}</ul>')
    link=(f'<p><a href="{_h.escape(PAGE_URL)}" style="color:#00a8e1">Open dashboard</a></p>'
          if PAGE_URL else "")
    body=(f'<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:640px">'
          f'<h2 style="color:#00a8e1">Prime Video - new titles (US/IT/UK)</h2>'
          f'<p style="color:#555">{len(items)} new titles across your priority regions.</p>'
          f'{link}{"".join(blocks)}<hr style="border:none;border-top:1px solid #eee">'
          f'<p style="color:#999;font-size:12px">Sources: TMDB + Watchmode. Auto-sent by GitHub Actions.</p></div>')
    msg=MIMEText(body,"html","utf-8")
    msg["Subject"]=f"Prime Video: {len(items)} new titles (US/IT/UK)"
    msg["From"]=formataddr(("Prime Video Watcher",SMTP_USER)); msg["To"]=MAIL_TO
    try:
        with smtplib.SMTP(SMTP_HOST,SMTP_PORT,timeout=30) as s:
            s.starttls(); s.login(SMTP_USER,SMTP_PASS)
            s.sendmail(SMTP_USER,[a.strip() for a in MAIL_TO.split(",")],msg.as_string())
        print(f"Email sent to {MAIL_TO}")
    except Exception as e:
        print(f"Email error: {e}", file=sys.stderr)

PAGE_HTML = r'''<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Prime Video - New Titles by Region</title>
<style>
:root{--bg:#0a0e17;--panel:#111826;--line:#1e2a3d;--txt:#e8eef7;--mut:#8a98ac;
--accent:#00a8e1;--movie:#ffb454;--tv:#7ee787;--wm:#c98bff}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
background:var(--bg);color:var(--txt);line-height:1.5;
background-image:radial-gradient(circle at 20% -10%,rgba(0,168,225,.08),transparent 40%)}
.wrap{max-width:1180px;margin:0 auto;padding:26px 18px 80px}
header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;
flex-wrap:wrap;padding-bottom:18px;border-bottom:1px solid var(--line);margin-bottom:20px}
h1{font-size:1.5rem;letter-spacing:-.02em;display:flex;align-items:center;gap:10px}
.logo{width:34px;height:34px;border-radius:8px;display:inline-flex;align-items:center;
justify-content:center;font-weight:800;font-size:.85rem;color:#fff;
background:linear-gradient(135deg,var(--accent),#0066b3)}
.sub{color:var(--mut);font-size:.85rem;margin-top:4px}
.asof{background:var(--panel);border:1px solid var(--line);border-radius:10px;
padding:10px 14px;font-size:.78rem;color:var(--mut);text-align:right}
.asof b{color:var(--txt);display:block}
.bar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:22px}
select{background:var(--panel);border:1px solid var(--line);color:var(--txt);
border-radius:10px;padding:10px 14px;font-size:.9rem;font-weight:600;cursor:pointer}
.seg{display:flex;background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.seg button{background:transparent;border:0;color:var(--mut);padding:9px 16px;
font-size:.84rem;cursor:pointer;font-weight:600}
.seg button.on{background:var(--accent);color:#fff}
.banner{border-radius:10px;padding:12px 16px;font-size:.85rem;margin-bottom:20px;border:1px solid var(--line)}
.banner.first{background:rgba(255,180,84,.1);border-left:3px solid var(--movie);color:#ffe1b8}
.banner.empty{color:var(--mut)}
.legend{font-size:.75rem;color:var(--mut);margin-bottom:16px;display:flex;gap:16px;flex-wrap:wrap}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;vertical-align:middle}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden;
text-decoration:none;color:inherit;transition:.15s;display:flex;flex-direction:column}
.card:hover{border-color:var(--accent);transform:translateY(-3px)}
.card.hl{box-shadow:0 0 0 1px var(--accent),0 8px 28px rgba(0,168,225,.18)}
.poster{position:relative;aspect-ratio:2/3;background:#0d1420}
.poster img{width:100%;height:100%;object-fit:cover;display:block}
.noposter{width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:2rem;opacity:.3}
.type{position:absolute;top:8px;left:8px;font-size:.62rem;font-weight:800;padding:3px 8px;
border-radius:6px;letter-spacing:.05em;backdrop-filter:blur(4px)}
.card.movie .type{background:rgba(255,180,84,.85);color:#1a1206}
.card.tv .type{background:rgba(126,231,135,.85);color:#06210b}
.wmtag{position:absolute;top:8px;right:8px;font-size:.6rem;font-weight:800;padding:3px 7px;
border-radius:6px;background:rgba(201,139,255,.85);color:#1a0a2e}
.body{padding:11px 13px}
.title{font-weight:700;font-size:.9rem;line-height:1.25}
.meta{font-size:.74rem;color:var(--mut);margin-top:4px}
.rate{color:var(--movie)}
.ov{font-size:.74rem;color:var(--mut);margin-top:7px;display:-webkit-box;
-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.none{color:var(--mut);padding:40px;text-align:center}
.stats{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 16px}
.stat .n{font-size:1.4rem;font-weight:800}.stat .l{font-size:.7rem;color:var(--mut);text-transform:uppercase}
footer{margin-top:46px;padding-top:18px;border-top:1px solid var(--line);font-size:.74rem;color:var(--mut);line-height:1.7}
footer a{color:var(--accent);text-decoration:none}
</style></head><body><div class="wrap">
<header>
  <div><h1><span class="logo">PV</span> Prime Video - New Titles</h1>
  <div class="sub">Weekly diff - TMDB (7 regions) + Watchmode cross-check (US/IT/UK)</div></div>
  <div class="asof">Last update<b id="asof">-</b></div>
</header>
<div class="bar">
  <label style="color:var(--mut);font-size:.85rem">Region</label>
  <select id="region"></select>
  <div class="seg" id="type">
    <button class="on" data-t="all">All</button>
    <button data-t="tv">Series</button>
    <button data-t="movie">Films</button>
  </div>
</div>
<div id="banner"></div>
<div class="stats" id="stats"></div>
<div class="legend">
  <span><span class="dot" style="background:var(--movie)"></span>Film</span>
  <span><span class="dot" style="background:var(--tv)"></span>Series</span>
  <span><span class="dot" style="background:var(--wm)"></span>Confirmed by Watchmode</span>
</div>
<div class="grid" id="grid"></div>
<footer>
  Sources: <a href="https://www.themoviedb.org/" target="_blank">TMDB</a> +
  <a href="https://www.watchmode.com/" target="_blank">Watchmode</a>.
  This product uses the TMDB API but is not endorsed or certified by TMDB.<br>
  Watchmode cross-check available for US, IT, UK only (free-tier 3-country limit). Other regions are TMDB-only.
</footer>
</div>
<script>
let DATA=null, state={region:null,type:"all"};
async function boot(){
  try{ DATA=await (await fetch("data.json?"+Date.now())).json(); }
  catch(e){ document.getElementById("grid").innerHTML='<div class="none">data.json not found yet - run the workflow first.</div>'; return; }
  document.getElementById("asof").textContent=new Date(DATA.generated).toLocaleString();
  const sel=document.getElementById("region");
  const codes=Object.keys(DATA.regions);
  state.region=codes[0];
  sel.innerHTML=codes.map(c=>'<option value="'+c+'">'+DATA.regions[c].label+' ('+c+')</option>').join("");
  sel.onchange=e=>{state.region=e.target.value;render();};
  document.getElementById("type").onclick=e=>{
    if(!e.target.dataset.t)return;
    state.type=e.target.dataset.t;
    [...e.currentTarget.children].forEach(b=>b.classList.toggle("on",b===e.target));
    render();
  };
  render();
}
function render(){
  const r=DATA.regions[state.region];
  const items=(r.new||[]).filter(x=>state.type==="all"||x.type===state.type);
  const banner=document.getElementById("banner");
  if(DATA.first_run){banner.className="banner first";
    banner.innerHTML="First run: baseline snapshot taken. Real new titles appear from next week's run.";}
  else if(!items.length){banner.className="banner empty";banner.textContent="No new titles for this region/filter since last run.";}
  else {banner.className="";banner.textContent="";}
  const movies=items.filter(x=>x.type==="movie").length, tv=items.filter(x=>x.type==="tv").length;
  const wm=items.filter(x=>(x.sources||[]).includes("watchmode")).length;
  document.getElementById("stats").innerHTML=
    '<div class="stat"><div class="n">'+items.length+'</div><div class="l">New</div></div>'+
    '<div class="stat"><div class="n" style="color:var(--tv)">'+tv+'</div><div class="l">Series</div></div>'+
    '<div class="stat"><div class="n" style="color:var(--movie)">'+movies+'</div><div class="l">Films</div></div>'+
    (r.wm?'<div class="stat"><div class="n" style="color:var(--wm)">'+wm+'</div><div class="l">WM ok</div></div>':"");
  const grid=document.getElementById("grid");
  if(!items.length){grid.innerHTML='<div class="none">- Nothing new -</div>';return;}
  grid.innerHTML=items.map(x=>{
    const wmt=(x.sources||[]).includes("watchmode")?'<span class="wmtag">WM ok</span>':"";
    const pos=x.poster?'<img src="'+x.poster+'" loading="lazy" alt="">':'<div class="noposter">*</div>';
    const rate=x.rating?'<span class="rate">* '+x.rating+'</span>':"";
    return '<a class="card '+x.type+' hl" href="'+x.tmdb+'" target="_blank" rel="noopener">'+
      '<div class="poster">'+pos+'<span class="type">'+(x.type==="tv"?"SERIES":"FILM")+'</span>'+wmt+'</div>'+
      '<div class="body"><div class="title">'+esc(x.title)+'</div>'+
      '<div class="meta">'+(x.year||"")+' '+rate+'</div>'+
      '<div class="ov">'+esc(x.overview||"")+'</div></div></a>';
  }).join("");
}
function esc(s){const d=document.createElement("div");d.textContent=s;return d.innerHTML;}
boot();
</script>
</body></html>
'''

if __name__ == "__main__":
    main()
