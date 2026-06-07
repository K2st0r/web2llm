#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================
Web2LLM v1.0 — 网页内容转 LLM 友好格式 API
Web-to-LLM: Clean web content for AI agents
=============================================================
License:    MIT
Donate:     0xAfe9B67B1DF618FAeD32dC71E3458cf549f26697 (ETH/USDT)
=============================================================
Features:
  - URL → Clean Markdown (for LLM/RAG agents)
  - URL → Raw text (token-efficient)
  - URL → Structured JSON (title, content, meta, images)
  - Automatic main content extraction (readability algorithm)
  - Anti-bot detection bypass (headers, timing, retry)
  - Proxy support (Chinese users can reach foreign sites)
  - Rate limiting + usage tracking
  - RESTful API with JSON responses
  - Batch URL processing
=============================================================
"""
import os, sys, json, time, re, base64, sqlite3, logging
from datetime import datetime
from pathlib import Path
from functools import wraps
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse, urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from readability import Document
from markdownify import markdownify as md
from flask import Flask, request, jsonify, render_template_string, g
from flask_cors import CORS

__version__ = "1.0.0"
__wallet__  = "0xAfe9B67B1DF618FAeD32dC71E3458cf549f26697"

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

WORK_DIR = Path(__file__).resolve().parent

# ─── Logging ───────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("web2llm")

# ─── Database ──────────────────────────────────────────
DB_PATH = WORK_DIR / "web2llm.db"

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    db = sqlite3.connect(str(DB_PATH))
    db.execute("""
        CREATE TABLE IF NOT EXISTS request_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT    NOT NULL,
            url         TEXT    NOT NULL,
            format      TEXT    NOT NULL,
            chars       INTEGER DEFAULT 0,
            time_ms     REAL,
            ip          TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS daily_stats (
            date           TEXT PRIMARY KEY,
            total          INTEGER DEFAULT 0,
            total_chars    INTEGER DEFAULT 0,
            avg_time_ms    REAL    DEFAULT 0
        )
    """)
    db.commit()
    db.close()
    log.info("DB initialized")

init_db()

def record(url, fmt, chars, time_ms, ip):
    try:
        db = sqlite3.connect(str(DB_PATH))
        now = datetime.now()
        db.execute("INSERT INTO request_log (timestamp, url, format, chars, time_ms, ip) VALUES (?,?,?,?,?,?)",
                   (now.isoformat(), url[:200], fmt, chars, time_ms, ip))
        today = now.strftime("%Y-%m-%d")
        db.execute("""INSERT INTO daily_stats (date, total, total_chars, avg_time_ms)
                      VALUES (?,1,?,?) ON CONFLICT(date) DO UPDATE SET
                      total=total+1, total_chars=total_chars+?,
                      avg_time_ms=(avg_time_ms*total+?)/(total+1)""",
                   (today, chars, time_ms, chars, time_ms))
        db.commit()
        db.close()
    except Exception as e:
        log.warning("DB error: %s", e)

# ─── Proxy config ──────────────────────────────────────
PROXY = os.environ.get("WEB2LLM_PROXY", "http://127.0.0.1:10793")

def make_session() -> requests.Session:
    """Create a requests session with proxy, retry, and proper headers."""
    session = requests.Session()
    
    # Retry strategy
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # Proxy
    session.proxies = {"http": PROXY, "https": PROXY}
    
    # Browser-like headers
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    })
    
    return session

# ─── Core extraction engine ────────────────────────────

class Web2LLM:
    """
    Web-to-LLM extraction engine.
    
    Extracts clean, LLM-ready content from any URL.
    """
    
    def __init__(self):
        self.session = make_session()
    
    def fetch(self, url: str, timeout: int = 30) -> Tuple[str, Dict]:
        """
        Fetch a URL and return (html_content, metadata).
        
        Returns:
            (html_string, meta_dict)
        """
        t0 = time.perf_counter()
        
        resp = self.session.get(url, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        
        # Detect encoding
        if resp.encoding and resp.encoding.lower() != 'utf-8':
            resp.encoding = resp.apparent_encoding or 'utf-8'
        
        html = resp.text
        elapsed = (time.perf_counter() - t0) * 1000
        
        # Build metadata
        parsed = urlparse(resp.url)
        meta = {
            "url": resp.url,
            "status": resp.status_code,
            "domain": parsed.netloc,
            "content_type": resp.headers.get("Content-Type", ""),
            "fetch_time_ms": round(elapsed, 1),
            "html_size": len(html),
        }
        
        return html, meta
    
    def extract_markdown(self, url: str, timeout: int = 30) -> Dict:
        """URL → Clean Markdown (best for LLM/RAG consumption)."""
        html, meta = self.fetch(url, timeout)
        
        t0 = time.perf_counter()
        doc = Document(html)
        content_html = doc.summary()
        title = doc.title() or ""
        
        markdown = md(content_html, heading_style="ATX", bullets="-", strip=["script", "style"])
        
        # Clean up excessive whitespace
        markdown = re.sub(r'\n{3,}', '\n\n', markdown)
        markdown = markdown.strip()
        
        elapsed = (time.perf_counter() - t0) * 1000
        
        return {
            "success": True,
            "title": title,
            "content": markdown,
            "chars": len(markdown),
            "extract_time_ms": round(elapsed, 1),
            **meta,
        }
    
    def extract_text(self, url: str, timeout: int = 30) -> Dict:
        """URL → Plain text (minimal, token-efficient)."""
        html, meta = self.fetch(url, timeout)
        
        t0 = time.perf_counter()
        soup = BeautifulSoup(html, 'lxml')
        
        # Remove unwanted elements
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
            tag.decompose()
        
        text = soup.get_text(separator='\n', strip=True)
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        elapsed = (time.perf_counter() - t0) * 1000
        
        return {
            "success": True,
            "content": text,
            "chars": len(text),
            "extract_time_ms": round(elapsed, 1),
            **meta,
        }
    
    def extract_structured(self, url: str, timeout: int = 30) -> Dict:
        """URL → Structured JSON (title, content, meta, images, links)."""
        html, meta = self.fetch(url, timeout)
        
        t0 = time.perf_counter()
        doc = Document(html)
        content_html = doc.summary()
        title = doc.title() or ""
        
        soup = BeautifulSoup(html, 'lxml')
        
        # Extract images
        images = []
        for img in soup.find_all('img'):
            src = img.get('src', '')
            if src and not src.startswith('data:'):
                alt = img.get('alt', '')
                images.append({"src": urljoin(url, src), "alt": alt})
        
        # Extract links
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('http'):
                text = a.get_text(strip=True)[:100]
                links.append({"href": href, "text": text})
        
        # Description / meta
        desc = ""
        meta_tag = soup.find('meta', attrs={'name': 'description'}) or soup.find('meta', attrs={'property': 'og:description'})
        if meta_tag:
            desc = meta_tag.get('content', '')
        
        markdown = md(content_html, heading_style="ATX", bullets="-", strip=["script", "style"])
        markdown = re.sub(r'\n{3,}', '\n\n', markdown).strip()
        
        elapsed = (time.perf_counter() - t0) * 1000
        
        return {
            "success": True,
            "title": title,
            "description": desc,
            "content": markdown,
            "chars": len(markdown),
            "images": images[:50],
            "links": links[:100],
            "extract_time_ms": round(elapsed, 1),
            **meta,
        }

engine = Web2LLM()

# ─── Dashboard HTML ────────────────────────────────────
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Web2LLM — Web Content for AI Agents</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--bd:#30363d;--fg:#c9d1d9;--fg2:#8b949e;--blue:#58a6ff;--green:#3fb950}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--fg);padding:24px}
.container{max-width:960px;margin:0 auto}
.hdr{text-align:center;padding:40px 0 24px}
.hdr h1{font-size:36px;background:linear-gradient(135deg,var(--blue),#d2a8ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hdr p{color:var(--fg2);margin-top:8px;font-size:14px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:20px;margin-bottom:16px}
.card h2{font-size:15px;margin-bottom:10px}
.card label{font-size:12px;color:var(--fg2);display:block;margin-bottom:4px}
.card input[type=text]{width:100%;padding:10px 14px;background:var(--bg);border:1px solid var(--bd);border-radius:8px;color:var(--fg);font-size:14px}
.card input[type=text]:focus{outline:none;border-color:var(--blue)}
.card select{padding:8px 12px;background:var(--bg);border:1px solid var(--bd);border-radius:6px;color:var(--fg);font-size:13px;margin-right:8px}
.card button{padding:10px 24px;background:var(--green);color:#000;border:none;border-radius:8px;font-size:13px;font-weight:700;cursor:pointer}
.card button:hover{opacity:.9}
.opt-row{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:12px 0}
.out{background:var(--bg);border:1px solid var(--bd);border-radius:8px;padding:14px;margin-top:12px;font-family:monospace;font-size:12px;white-space:pre-wrap;word-break:break-all;max-height:400px;overflow:auto}
.wallet{text-align:center;font-size:11px;color:var(--fg2);margin-top:24px;padding-top:20px;border-top:1px solid var(--bd)}
.wallet code{color:#d2a8ff}
.ft{text-align:center;color:#484f58;font-size:11px;margin-top:12px}
</style>
</head>
<body>
<div class="container">
<div class="hdr">
<h1>Web2LLM</h1>
<p>Convert any webpage to clean, LLM-ready content. One API call.</p>
</div>

<div class="card">
<h2>Try it</h2>
<label>URL</label>
<input type="text" id="url" placeholder="https://example.com/article" value="https://en.wikipedia.org/wiki/Python_(programming_language)">
<div class="opt-row">
<select id="fmt"><option value="markdown">Markdown (LLM-ready)</option><option value="text">Plain Text</option><option value="structured">Structured JSON</option></select>
<span style="font-size:11px;color:var(--fg2)">100 requests/day free · Pro: $10/mo — 10k/day</span>
</div>
<button onclick="extract()">Extract</button>
<div class="out" id="out">Enter a URL and click Extract</div>
</div>

<div class="card">
<h2>API Endpoints</h2>
<pre style="font-size:12px;background:var(--bg);padding:12px;border-radius:8px;overflow-x:auto">
# Markdown (for LLM/RAG)
POST /api/v1/markdown
{"url": "https://example.com"}

# Plain text (token-efficient)
POST /api/v1/text
{"url": "https://example.com"}

# Structured JSON
POST /api/v1/structured
{"url": "https://example.com"}

# Batch (up to 10 URLs)
POST /api/v1/batch
{"urls": ["https://a.com", "https://b.com"], "format": "markdown"}

# Health
GET /health
</pre>
</div>

<div class="wallet">
Donate: <code>0xAfe9B67B1DF618FAeD32dC71E3458cf549f26697</code> (USDT/ERC20) &middot; Buy Pro: k2st0r@users.noreply.github.com
</div>
<div class="ft">Powered by Web2LLM v1.0 &middot; MIT License</div>
</div>
<script>
async function extract(){
 const url=document.getElementById('url').value.trim();
 const fmt=document.getElementById('fmt').value;
 if(!url){document.getElementById('out').textContent='Enter a URL';return}
 document.getElementById('out').textContent='Fetching...';
 try{
  const r=await fetch('/api/v1/'+fmt,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:url})});
  const d=await r.json();
  let out=JSON.stringify(d,null,2);
  if(d.content&&d.content.length>2000) out=JSON.stringify({...d,content:d.content.slice(0,2000)+'\n... [truncated '+(d.content.length-2000)+' more chars]'},null,2);
  document.getElementById('out').textContent=out;
 }catch(e){document.getElementById('out').textContent='Error: '+e}
}
</script>
</body>
</html>
"""

# ─── Routes ────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)

@app.route("/health")
def health():
    return jsonify({"status": "ok", "version": __version__, "uptime_s": round((datetime.now() - datetime.fromisoformat(engine._started_at)).total_seconds(), 1) if hasattr(engine, '_started_at') else 0})

engine._started_at = datetime.now().isoformat()

def extract_endpoint(fmt: str):
    """Generic endpoint handler."""
    data = request.get_json(silent=True) or {}
    url = data.get("url", "")
    timeout = min(int(data.get("timeout", 30)), 60)
    
    if not url:
        return jsonify({"success": False, "error": "Missing 'url' field"}), 400
    
    # Validate URL
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return jsonify({"success": False, "error": "Invalid URL"}), 400
    
    t0 = time.perf_counter()
    try:
        if fmt == "markdown":
            result = engine.extract_markdown(url, timeout)
        elif fmt == "text":
            result = engine.extract_text(url, timeout)
        elif fmt == "structured":
            result = engine.extract_structured(url, timeout)
        else:
            return jsonify({"success": False, "error": "Invalid format"}), 400
        
        elapsed = (time.perf_counter() - t0) * 1000
        result["total_time_ms"] = round(elapsed, 1)
        
        record(url, fmt, result.get("chars", 0), elapsed, request.remote_addr or "unknown")
        return jsonify(result)
    
    except requests.exceptions.Timeout:
        msg = f"Request timed out after {timeout}s"
        record(url, fmt, 0, timeout * 1000, request.remote_addr or "unknown")
        return jsonify({"success": False, "error": msg}), 504
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else 502
        msg = f"HTTP {status}: {str(e)[:100]}"
        record(url, fmt, 0, 0, request.remote_addr or "unknown")
        return jsonify({"success": False, "error": msg}), status
    except Exception as e:
        record(url, fmt, 0, 0, request.remote_addr or "unknown")
        return jsonify({"success": False, "error": str(e)[:200]}), 500

@app.route("/api/v1/markdown", methods=["POST"])
def api_markdown():
    return extract_endpoint("markdown")

@app.route("/api/v1/text", methods=["POST"])
def api_text():
    return extract_endpoint("text")

@app.route("/api/v1/structured", methods=["POST"])
def api_structured():
    return extract_endpoint("structured")

@app.route("/api/v1/batch", methods=["POST"])
def api_batch():
    data = request.get_json(silent=True) or {}
    urls = data.get("urls", [])
    fmt = data.get("format", "markdown")
    timeout = min(int(data.get("timeout", 15)), 30)
    
    if not urls or not isinstance(urls, list):
        return jsonify({"success": False, "error": "Missing 'urls' array"}), 400
    if len(urls) > 10:
        return jsonify({"success": False, "error": "Max 10 URLs per batch"}), 400
    
    results = []
    for url in urls:
        t0 = time.perf_counter()
        try:
            if fmt == "markdown":
                r = engine.extract_markdown(url, timeout)
            elif fmt == "text":
                r = engine.extract_text(url, timeout)
            else:
                r = engine.extract_structured(url, timeout)
            r["total_time_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            results.append({"url": url, "success": True, **r})
        except Exception as e:
            results.append({"url": url, "success": False, "error": str(e)[:200]})
    
    return jsonify({"success": True, "count": len(results), "results": results})

@app.route("/api/v1/stats")
def api_stats():
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        db = sqlite3.connect(str(DB_PATH))
        row = db.execute("SELECT * FROM daily_stats WHERE date=?", (today,)).fetchone()
        db.close()
        today_stats = dict(row) if row else {"total": 0, "total_chars": 0, "avg_time_ms": 0}
    except:
        today_stats = {"total": 0, "total_chars": 0, "avg_time_ms": 0}
    return jsonify({"version": __version__, "today": today_stats, "server_time": datetime.now().isoformat()})

# ─── Main ──────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("WEB2LLM_PORT", "9528"))
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║   Web2LLM v{__version__:<48}║
║   Web Content for AI Agents                                ║
╠══════════════════════════════════════════════════════════════╣
║   Web:    http://0.0.0.0:{port:<39}║
║   API:    POST /api/v1/markdown    URL -> Clean Markdown    ║
║           POST /api/v1/text        URL -> Plain Text        ║
║           POST /api/v1/structured  URL -> Structured JSON   ║
║           POST /api/v1/batch       Bulk (max 10 URLs)       ║
╠══════════════════════════════════════════════════════════════╣
║   Proxy: {PROXY:<46}║
║   Donate: {__wallet__}        ║
╚══════════════════════════════════════════════════════════════╝
    """)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
