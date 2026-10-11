# News Summarizer

A backend service that fetches technology stories from Hacker News every 6 hours, stores them in PostgreSQL, and serves them through a REST API — including an AI-generated summary of any article, cached in Redis.

Built with FastAPI as a home assignment (Python Backend Developer, Ti-Space Career Accelerator).

## Requirements covered

| Requirement | Where |
|---|---|
| Fetch from a public API by keyword, fixed response shape | Hacker News search API (Algolia), stories only, keyword from `FETCH_QUERY` — `app/hn_client.py` |
| Store with at least 5 core attributes, PostgreSQL | `articles` table: title, url, author, points, comment count, story text, timestamps — `app/models.py` |
| AI integration (mock or real) and summarization | One `Summarizer` interface with mock, Google Gemini and Anthropic Claude implementations — `app/summarizer.py` |
| `GET /[dataType]` paginated | `GET /articles?page=&size=` |
| `GET /dataType/{id}` | `GET /articles/{id}` |
| `GET /dataType/{id}/summary` | `GET /articles/{id}/summary` |
| FastAPI, RESTful, proper HTTP methods | Resource paths, GET for reads, POST for the one state-changing action, meaningful status codes (404, 422, 502) |
| Automatic fetch every 6 hours | APScheduler, started with the app — `app/scheduler.py` |
| Caching of summaries | Redis, cache-aside, 24-hour TTL — `app/cache.py` |
| Dockerfile and Docker setup (bonus) | `Dockerfile`, `docker-compose.yml` (app + PostgreSQL + Redis) |
| Unit tests | 86 pytest tests — `tests/` |
| Example responses with Postman | `postman/` (collection with saved examples, plus an environment) |

## Quick start (Docker)

The only prerequisite is Docker with Compose.

```bash
git clone https://github.com/Nitzan101/news-summarizer.git
cd news-summarizer
docker compose up --build
```

When the three containers are up, the API is at **http://localhost:8000** and interactive documentation at **http://localhost:8000/docs**. On startup the service fetches the newest stories right away, so the database is populated within a few seconds — no manual step is needed.

Out of the box the summarizer is a **mock** (no API key, no network): summaries are clearly marked `[mock summary]`. See [Real AI summaries](#real-ai-summaries) to switch it on.

### Ports

| Host port | Service | Needed for |
|---|---|---|
| 8000 | API | Using the service |
| 5433 | PostgreSQL | Only for running the tests or the app from the host |
| 6379 | Redis | Only for running the tests or the app from the host |

PostgreSQL and Redis are published on `127.0.0.1` only, so they are not reachable from other machines.

If `docker compose up` fails with `port is already allocated`, something on your machine already uses one of these. Change the **left** number of that mapping in `docker-compose.yml` (for example `"8080:8000"`), and use the new port in the URLs. The right number is the port inside the container and must stay as it is.

## Real AI summaries

Copy `.env.example` to `.env` and set a provider and its key. Compose reads `.env` automatically; the file is ignored by git and is not copied into the image.

```
SUMMARIZER=gemini
GEMINI_API_KEY=your-key
```

Then `docker compose up --build` again.

| `SUMMARIZER` | Key | Default model | Status |
|---|---|---|---|
| `mock` (default) | none | — | Deterministic stand-in |
| `gemini` | `GEMINI_API_KEY` | `gemini-3.5-flash-lite` | Run against the real API |
| `claude` | `ANTHROPIC_API_KEY` | `claude-haiku-5-5` | Implemented and tested against a fake HTTP layer; **not** run against the real API |

Gemini was chosen as the live provider because Google AI Studio issues a key on a free tier with no payment method. Note that on that free tier Google may use submitted content to improve its products; this service only sends the text of public articles.

If the selected provider has no key, the service refuses to start and says why, rather than failing on the first request.

## API

| Method and path | Description |
|---|---|
| `GET /articles?page=1&size=10` | One page of articles, newest first. `page` starts at 1; `size` is 1–100. |
| `GET /articles/{id}` | One article. `404` if it does not exist, `422` if the id is not a positive integer. |
| `GET /articles/{id}/summary` | AI summary of the article. `404` if it does not exist, `502` if the AI provider fails. |
| `POST /fetch` | Fetch from Hacker News now instead of waiting for the schedule. `502` if Hacker News fails. |
| `GET /health` | Liveness check. |

```bash
curl "http://localhost:8000/articles?page=1&size=1"
```

```json
{
  "items": [
    {
      "id": 61,
      "hn_id": 50045480,
      "title": "Why we're watching these climate tech companies",
      "url": "https://www.technologyreview.com/2026/10/08/1145920/climate-tech-companies-list/",
      "author": "joozio",
      "points": 5,
      "num_comments": 0,
      "story_text": null,
      "created_at": "2026-10-11T17:18:21Z",
      "fetched_at": "2026-10-11T17:46:06.314223Z"
    }
  ],
  "total": 21,
  "page": 1,
  "size": 1
}
```

Ids are unique but not consecutive: PostgreSQL advances the id sequence even for a story that turns out to exist already, so each re-fetch leaves a gap.

With `SUMMARIZER=gemini` (the default mock returns an excerpt marked `[mock summary]` instead):

```bash
curl "http://localhost:8000/articles/2/summary"
```

```json
{
  "article_id": 2,
  "summary": "The 2026 Nobel Prize in physiology or medicine has been awarded for the development of optogenetics, a breakthrough technique that uses light to control neuronal activity millisecond by millisecond. This milestone builds on decades of technological advances in visualizing and measuring the brain, opening the door to potential treatments for conditions like epilepsy, vision loss, and mental health disorders.",
  "source": "page",
  "cached": false
}
```

`source` says what was summarized, and `cached` whether the answer came from Redis. A second request for the same article returns the same summary with `"cached": true` and does not call the AI provider.

Full example responses for every endpoint, including the error cases, are in the Postman collection.

### Postman

Import both files from `postman/` into Postman and select the **News Summarizer - local** environment (it defines `base_url` and `article_id`). Every request carries a saved example response captured from a real run, so the responses can be read without starting the service. The collection also runs from the command line:

```bash
npx newman run postman/news-summarizer.postman_collection.json -e postman/news-summarizer.postman_environment.json
```

## Architecture

```
                     ┌──────────────────────── app (FastAPI) ────────────────────────┐
  client ──HTTP──▶   │  main.py      routes, startup/shutdown                         │
                     │    ├─ fetcher.py ── hn_client.py ──HTTP──▶ Hacker News         │
  every 6 h ──────▶  │    │   (scheduler.py calls the same fetch)                     │
                     │    ├─ content.py ──HTTP──▶ the article's own web page          │
                     │    ├─ summarizer.py ──HTTP──▶ Gemini / Claude  (or mock)       │
                     │    ├─ cache.py ──▶ Redis        (summaries, 24 h TTL)          │
                     │    └─ db.py, models.py ──▶ PostgreSQL   (articles)             │
                     └────────────────────────────────────────────────────────────────┘
```

Each external system is reached through exactly one module, so replacing the data source, the AI provider or the cache touches one file.

| Module | Responsibility |
|---|---|
| `app/main.py` | Routes and application lifespan |
| `app/hn_client.py` | The only code that calls Hacker News |
| `app/fetcher.py` | Maps stories to rows and upserts them |
| `app/scheduler.py` | Runs the fetch at startup and every 6 hours |
| `app/content.py` | Finds the text to summarize for an article |
| `app/summarizer.py` | Summarizer interface and its three implementations |
| `app/cache.py` | Summary cache |
| `app/db.py`, `app/models.py` | Database engine, sessions and the `Article` table |
| `app/schemas.py` | Response shapes |
| `app/config.py` | Settings from environment variables |

### How a summary is produced

Hacker News is a link board: it stores a story's title, URL and metadata, not the article itself. So a summary request does the following:

1. Return the cached summary if Redis has one.
2. Otherwise find text to summarize, in order of preference: the linked page (fetched and reduced to plain text), then the story's own text for text posts such as "Ask HN", then the title. Every article therefore gets a summary; `source` reports which of the three was used.
3. Send the text to the summarizer, store the result in Redis for 24 hours, and return it.

## Configuration

All settings are environment variables; every one has a default, so nothing is required for the mock setup. Put overrides in `.env` (see `.env.example`): Compose passes every variable below into the container, and the app reads the same file when run from the host.

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | local PostgreSQL on port 5433 | Set by Compose inside Docker |
| `REDIS_URL` | local Redis on port 6379 | Set by Compose inside Docker |
| `SUMMARIZER` | `mock` | `mock`, `gemini` or `claude` |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | empty, `gemini-3.5-flash-lite` | Used when `SUMMARIZER=gemini` |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | empty, `claude-haiku-5-5` | Used when `SUMMARIZER=claude` |
| `FETCH_QUERY` | `technology` | Keyword searched on Hacker News |
| `FETCH_LIMIT` | `20` | Stories per fetch |
| `FETCH_INTERVAL_HOURS` | `6` | Time between scheduled fetches |
| `SCHEDULER_ENABLED` | `true` | Set to `false` to disable the scheduler |
| `SUMMARY_CACHE_TTL_SECONDS` | `86400` | Lifetime of a cached summary |

## Development

Running the app and the tests from the host needs Python 3.12 and the database and cache from Compose:

```bash
python -m venv .venv
# Windows:        .venv\Scripts\activate
# macOS / Linux:  source .venv/bin/activate
pip install -r requirements-dev.txt
docker compose up -d postgres redis
uvicorn app.main:app --reload
```

### Tests

```bash
pytest
```

The tests need the `postgres` and `redis` containers running. They never touch the application's data: they use a separate `news_test` database, created automatically, and Redis database 1.

What the tests are built on:

- **Real PostgreSQL and Redis, not fakes.** Upserts, unique constraints, TTLs and connection handling are properties of the real systems.
- **Real AI SDKs over a fake HTTP transport.** The Gemini and Anthropic clients build real requests and parse real-shaped responses; only the network underneath is replaced. No test needs a key or costs anything.
- **External HTTP is faked, never called.** Hacker News and article pages are served by in-memory transports.
- **Failure paths are tested, not only success:** a provider that is down, a blocked or empty AI reply, a malformed story or an unexpected body from Hacker News, an unreachable or malformed article URL, Redis being down or holding garbage, PostgreSQL closing its connections, ids and page numbers too large for the database.
- **Fixed settings.** The suite sets its own environment before importing the app, so a `.env` with a real provider and key cannot make it call a paid API.

## Design decisions

The reasoning behind each choice is recorded in [`docs/DESIGN.md`](docs/DESIGN.md). The ones most likely to be asked about:

- **Two identifiers per article.** `id` is ours and appears in URLs; `hn_id` is the story's id at the source, unique in the table. Clients never depend on an external system's ids, and a second data source could be added without collisions.
- **Idempotent fetch.** Stories are written with `INSERT ... ON CONFLICT (hn_id) DO UPDATE`, in one statement. Fetching the same stories again updates their scores instead of duplicating them, so the scheduled job, a manual `POST /fetch` and a retry after a failure can overlap safely.
- **Summaries on request, not at fetch time.** Summarizing every fetched story would spend AI calls on summaries nobody reads. The cost is a slower first request per article, which the cache then absorbs.
- **The cache can fail without failing the service.** Redis holds nothing that cannot be rebuilt, so Redis errors are swallowed and the request is served without caching. PostgreSQL is the source of truth and is treated differently.
- **Summaries expire after 24 hours.** A summary built from a fallback (the article's site was down, so only the title was summarized) would otherwise be served forever.
- **Database connections are checked before use** (`pool_pre_ping`). In a real run, the first request after PostgreSQL had dropped a pooled connection failed with a 500. For a service whose main job runs once every 6 hours, a stale connection is the normal case, not an edge case.
- **One malformed story does not cost the other nineteen.** A story missing a required field is skipped and logged.
- **The article text is untrusted input to the model.** The instructions tell the model to treat it as material to summarize and never to follow requests inside it.
- **The container runs as a non-root user**, and secrets reach it only as environment variables at run time.

### What I would change at scale

- **Migrations.** Tables are created with SQLAlchemy's `create_all`, which cannot alter an existing table. That is acceptable here — one table, a fixed schema, data that can be re-fetched — but a real system needs Alembic migrations.
- **The scheduler as its own service.** It runs inside the API process. With several API replicas, each would run its own scheduler and fetch in duplicate (harmless thanks to the upsert, but wasteful). The fix is a single-instance scheduler service that triggers the fetch.
- **Summaries off the request path.** A summary request waits for the article's site and for the AI provider. A job queue with a "pending" state would keep requests fast.
- **One AI call per article under concurrency.** Several simultaneous requests for an uncached summary each fetch the page and call the provider. A per-article lock (or the job queue above) would collapse them into one.
- **Pinned dependencies.** `requirements.txt` gives version ranges; a lockfile would make builds reproducible.
- **Better text extraction.** BeautifulSoup with a list of tags to drop leaves some page chrome in the text. A dedicated extractor would give cleaner input.

## Beyond the assignment

- `POST /fetch` — lets a reviewer trigger a fetch without waiting 6 hours, and gives the API a natural POST.
- `source` and `cached` in the summary response — make the fallback chain and the cache observable from outside.
- `GET /health` and container healthchecks, so Compose starts the app only once the database and cache are ready.
- A third summarizer implementation, as a demonstration of what the interface buys: adding Gemini changed one class and one factory branch, and no code that uses a summarizer.

## Known limitations

- The Claude implementation has not been run against the real Anthropic API.
- No authentication or rate limiting on the API.
- The service fetches whatever URL a Hacker News story links to. Only `http` and `https` URLs are fetched, with a 10-second timeout, and at most 8,000 characters of the extracted text are used, but the download itself is not size-limited, redirects are followed, and there is no protection against a link that points at an internal network address — whose content could then be reflected in a summary.
- Gemini's free tier has request quotas; when they are exhausted the summary endpoint returns `502` until they reset.
