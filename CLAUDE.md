# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

MyBooks (formerly Talebook) is a personal Calibre-based ebook management webserver. It's a monorepo with two main parts:

- `webserver/` — Python/Tornado backend, built on top of Calibre's library DB (and PyQt5, since Calibre depends on it)
- `app/` — Vue 2 frontend (Nuxt.js + Vuetify), compiled to a static SPA served by the backend

Other top-level directories: `tests/` (backend unit tests), `tools/` (standalone scripts: spiders, converters, metadata scrapers), `conf/` (nginx/supervisor config templates), `docker/` (image entrypoints and prebuilt library), `extensions/` and `third-party/epub.js` (git submodules), `webserver/epub_to_audio` (git submodule for EPUB→audiobook conversion).

## Common commands

### Backend (Python / webserver)

```bash
# Lint (matches CI)
flake8 webserver --count --statistics --config .style.yapf --exclude epub_to_audio,test

# Run all backend tests
pytest tests

# Run a single test file / test case / test method
pytest tests/test_models.py
pytest tests/test_models.py::TestUser
pytest tests/test_models.py::TestUser::test_shrink_extra_size2

# Coverage (matches CI)
pytest ./tests -v --cov=webserver --cov-report=term-missing
```

Test fixtures (sample DBs, ebooks, ssl certs) live in `tests/cases/`. `tests/test_main.py` contains the Tornado `AsyncHTTPTestCase`-based integration tests that spin up the app; most other `tests/test_*.py` files cover individual services/handlers/models.

### Frontend (app/, Vue/Nuxt)

```bash
cd app
npm install
npm run dev          # dev server (nuxt)
npm run build-spa    # production SPA build -> app/dist/ (served by backend)
npm run generate     # static site generation
npm run lint         # eslint
```

Node 17+ requires `export NODE_OPTIONS=--openssl-legacy-provider` (also set in `app/Makefile`'s `make` target).

The frontend always calls the backend at `/api/...` relative to the page's own origin — when developing the backend separately, proxy `/api|/get|/read|/auth|/opds` to the Tornado server (see `document/Development.zh_CN.md` for an nginx example) rather than hardcoding a backend URL.

### Running the server directly
Prefer to use default conda environment instead of .venv.

```bash
python3 server.py --with-library=/data/books/library --port=8083 --host=127.0.0.1 --logging=info --log-file-prefix=/data/log/mybooks.log
# or
./run_webserver.sh
```

`server.py` just calls `webserver.main.main()`. First run needs `--syncdb` to create DB tables.

### Docker (primary deployment path)

The project is normally run via Docker (`docker-compose.yml`, `Dockerfile`, `Dockerfile.base`). `make build` / `make up` / `make down` wrap docker-compose. Recommended dev workflow: run the published `poxenstudio/mybooks` image and bind-mount `webserver/` into the container — the Tornado server autoreloads on code changes (see `document/Development.zh_CN.md`).

## Architecture

### Backend bootstrap (`webserver/main.py`)

`main()` wires together:
- A Calibre library DB (`legacy` book_db + `cache`, the new-style Calibre cache) opened from `--with-library`
- SQLAlchemy `ScopedSession` against the app's own user database (`user_database` setting, separate from Calibre's DB)
- Monkeypatches into Calibre internals (e.g. disabling the Qt GUI requirement, binding top-dir book names) — see `config_calibre()` and the `gui2.must_use_qt` patch
- A `tornado.web.Application` assembled from per-feature route modules under `webserver/handlers/`

**Route assembly order matters** — routes are concatenated in a specific order because some handlers register catch-alls:
1. social auth routes, then feature routes (`assistant`, `mcp`, `admin`, `barcode`, `scan`, `opds`, `book`, `user`, `meta`, `audio`, `toolbox`, `podcast`)
2. WAP routes (server-rendered pages for e-ink/Kindle browsers) — must precede static files
3. WebDAV routes (`/books/?(.*)`)
4. `static_files.routes()` last — it contains the catch-all `r"/(.*)"` that serves the Vue SPA

Several services (podcast, WebDAV, AI assistant) are *always* registered but check their `ENABLE_*` setting at request time, so toggling them in admin settings takes effect without a restart.

### Settings / configuration (`webserver/loader.py`, `webserver/settings.py`)

Settings are a layered dict: `webserver/settings.py` defaults are overlaid by an `auto.py` (machine-generated, e.g. via `SettingsSaver`) and then a `manual.py`, both loaded from `settings_path` (default `/data/books/settings/`). Access the merged config via `webserver.loader.get_settings()` (aliased `CONF` throughout the codebase). Don't hardcode values that exist in `settings.py` — read them from `CONF`.

### Data model (`webserver/models.py`)

Two separate databases coexist:
- **Calibre's library DB** — books/authors/tags/etc., accessed through `legacy`/`cache` (Calibre's own DB layer), not through SQLAlchemy models here
- **The app's own SQLAlchemy DB** (`user_database`) — `models.py` defines `Reader`, `Item`, `Message`, and other app-specific entities (users, reading progress, social-auth storage via `social_sqlalchemy`/`social_tornado`)

`bind_session()` wires a SQLAlchemy session into both `Base` (declarative models) and `SQLAlchemyMixin` (social-auth models) so they share one session.

### Handlers (`webserver/handlers/`)

Each module exposes a `routes()` function returning a list of Tornado URL specs; `main.py` concatenates them. `webserver/handlers/base.py` provides `BaseHandler` and shared helpers — notably the `@js` decorator which wraps handler methods to catch exceptions, JSON-encode the response, and set CORS/cache headers uniformly. A class-level `BaseHandler.db_lock` (threading.RLock) serializes thread-unsafe Calibre DB access.

### Services (`webserver/services/`)

Business logic that's too heavy for handlers lives here as service classes (e.g. `BookBarnService`, `AsyncService`, `ItemSyncService`, `ScanService`, `MonitorService`, conversion/import/metadata-update services). Handlers typically delegate to these. `AsyncService` and similar singletons are set up once in `main()` and may run periodic background work (DB checks, scheduled imports, etc.).

### i18n

`webserver/i18n.py` plus `webserver/i18n/` provide `_()`, `choose_language()`, `set_language()` for backend translations; the frontend uses `vue-i18n` with locale files under `app/locales/`.

### toolbox
Refer to [Toolbox Design](document/toolbox_design.md) for details to add new tool in MyBooks.

## metadata plugin
Refer to [Metadata Plugin](document/meta_plugins.md) for details to add new meta data plugin.

## Code style

- Python: flake8-checked (config in `.style.yapf` and `.flake8`; `E501` line-length ignored), formatted with yapf using a Google-based style (`column_limit=240`). Pylint config disables several docstring/logging warnings.
- TypeScript/JS (frontend): see `.claude/rules/typescript.md` — never use `any`; strict mode; ES2022 target; `_`-prefixed unused vars allowed.
