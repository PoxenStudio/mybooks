# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

**Primary:** an individual ebook collector who self-hosts MyBooks on a NAS or Docker host for their own library. They are comfortable with servers and Calibre, and they run the system at home, often reachable only on a LAN or behind their own reverse proxy.

**Secondary:** family and small household members who share that one library through separate accounts, each with their own reading progress, booklists, and history. Multi-account sharing is a first-class, common case even though the owner is the primary audience.

## Product Purpose

MyBooks is a personal Calibre-based ebook and print-book management webserver: it catalogs a library, serves it to readers (web UI, OPDS, WebDAV, KOReader, e-ink/WAP pages), and manages multi-account reading. It exists so one person or family can own and administer their whole library without a public book site. Success means the owner keeps using it as the single place their books, reading data, and library utilities live.

## Positioning

Depth of reading data and management tools, not just catalog browsing. MyBooks bundles reading statistics and dashboards, user booklists and sharing, a toolbox of library utilities, format conversion, audiobook generation, metadata plugins, podcast feeds, and sync — a management suite around Calibre that a plain catalog front-end cannot truthfully claim.

## Operating Context

- Runs as a Docker container (recommended) or directly via `server.py`; the backend is Python/Tornado on Calibre's library DB, the frontend a Vue 2 / Nuxt / Vuetify SPA.
- Libraries are existing Calibre libraries; books and metadata are managed through Calibre's own DB layer.
- Used from desktop browsers, phones (responsive web), e-ink/Kindle-class browsers (server-rendered WAP pages), and external clients: OPDS readers, KOReader plugin, WebDAV mounts, browser extension, and AI/MCP clients.
- Configuration is layered settings files (`auto.py` / `manual.py`), with admin pages for site name, notice, users, permissions, and integrations.
- Frequently deployed on home networks or private servers; exposure to the public internet is discouraged.

## Capabilities and Constraints

- Confirmed capabilities: book import/monitoring, metadata plugins, custom categories, print books, multi-user accounts and permissions, reading progress/history/statistics and dashboards, booklists and sharing, favorites/wants/read-done shelves, private ("soled"/私藏) books, format conversion (epub/azw3/pdf, Word import), EPUB→audiobook and TTS, podcast feed, WebDAV and sync APIs, OPDS, KOReader support, WAP lite pages, toolbox, dark mode, avatar/icon customization.
- Technical constraints: must remain compatible with existing Calibre libraries and Calibre internals; keep the Vue 2 / Vuetify 2 frontend conventions and shared dialog/UI rules; all API calls stay relative to the page origin under `/api`, `/get`, `/read`, `/auth`, `/opds`.
- Product boundaries: not a site-hosting platform and not a public book-publishing/serving service; not an ebook reader replacement (MyReader is the companion reader).
- Chinese-first: Simplified Chinese is the primary language; English and Traditional Chinese locales exist and must keep working.
- Private-by-default security model is a hard constraint: access cookies/passwords, permission levels, and no assumption that the deployment is public.

## Brand Commitments

- Name: MyBooks (formerly Talebook); open source and free, MIT-licensed.
- Voice: friendly, practical, Chinese-first, aimed at book lovers rather than enterprises.
- Existing identity assets: `document/example.jpg` screenshots, architecture diagram, WeChat public account imagery; dark mode and theme switching are established expectations.

## Evidence on Hand

- Working codebase (`webserver/`, `app/`), extensive design docs under `document/` (Web API, toolbox, reading stats, sync, booklists, themes), `tests/`, `features.md`, and `release_notes.txt`.
- Real feature evidence: `skills/mybooks` agent skill, MCP service, browser extension and KOReader plugin repos, published Docker images.
- No verified testimonials, customer logos, pricing, or benchmark claims are on hand; future work must not fabricate them.

## Product Principles

1. The library belongs to its owner: private by default, self-hosted, and never shaped like a public book site.
2. Depth over breadth of surface: reading data and management tools are the product's reason to exist.
3. Calibre and existing clients are contracts — OPDS, WebDAV, KOReader, and the API must keep working.
4. Chinese-first craft: typography, search (simplified/traditional), and localization quality are part of the product, not an afterthought.
5. Family-scale multi-account: separate progress and shelves without making the owner's admin job harder.

## Accessibility & Inclusion

No product-specific accessibility standard has been confirmed. Existing expectations: responsive use on phones, and readable, low-bandwidth e-ink/WAP pages for simple browsers.
