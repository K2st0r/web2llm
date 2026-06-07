<div align="center">

# Web2LLM

**Web Content for AI Agents — URL to Clean Markdown/Text/JSON API**

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.x-green.svg)](https://flask.palletsprojects.com)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-1.0.0-purple.svg)](https://github.com/K2st0r/web2llm/releases)
[![Donate](https://img.shields.io/badge/Donate-USDT-red.svg)](#donate)

</div>

## 🎯 What is Web2LLM?

**Web2LLM** converts any webpage into clean, LLM-ready content. Built for AI agents, RAG pipelines, and developers who need structured web data.

| Input | Output | Best For |
|-------|--------|----------|
| URL → | **Markdown** | LLM prompts, RAG ingestion |
| URL → | **Plain Text** | Token-efficient extraction |
| URL → | **Structured JSON** | AI agents, data pipelines |

## 🚀 Live API (24/7)

```bash
# Health check
curl https://interest-designers-williams-sanyo.trycloudflare.com/health

# URL → Clean Markdown (for LLM/RAG)
curl -X POST https://interest-designers-williams-sanyo.trycloudflare.com/api/v1/markdown \
  -H "Content-Type: application/json" \
  -d '{"url": "https://en.wikipedia.org/wiki/Python_(programming_language)"}'

# URL → Structured JSON
curl -X POST https://interest-designers-williams-sanyo.trycloudflare.com/api/v1/structured \
  -H "Content-Type: application/json" \
  -d '{"url": "https://en.wikipedia.org/wiki/Python_(programming_language)"}'

# Batch (up to 10 URLs)
curl -X POST https://interest-designers-williams-sanyo.trycloudflare.com/api/v1/batch \
  -H "Content-Type: application/json" \
  -d '{"urls": ["https://a.com", "https://b.com"], "format": "markdown"}'
```

## 📦 Local Setup

```bash
git clone https://github.com/K2st0r/web2llm.git
cd web2llm
pip install -r requirements.txt
WEB2LLM_PROXY=http://127.0.0.1:10793 python web2llm.py
# → http://localhost:9528
```

## 💰 Pricing

| Tier | Price | Daily Limit |
|------|-------|-------------|
| Free | $0 | 100 requests |
| Pro | **$10/mo** | 10,000 requests |
| Unlimited | **$50/mo** | Unlimited |

**Pay with USDT (ERC20):** `0xAfe9B67B1DF618FAeD32dC71E3458cf549f26697`

## 🏗️ Architecture

```
URL → [Proxy] → [requests + retry] → [readability] → [markdownify] → Clean Content
                                         ↓
                              [BeautifulSoup] → [Structured JSON]
```

## 📄 License

MIT License — see [LICENSE](LICENSE).

*Made with ❤️ by [K2st0r](https://github.com/K2st0r)*
