# Design

## Requirements (from the assignment)
- Fetch data from a public API by keyword/category; store it in PostgreSQL with at least 5 core attributes.
- Fetch automatically every 6 hours with a scheduler that works with FastAPI.
- Summarize items with an AI API (mock or real); cache summaries (Redis).
- Endpoints: `GET /articles` (paginated), `GET /articles/{id}`, `GET /articles/{id}/summary`.
- Unit tests, README, Postman collection with example responses; Dockerfile and Docker setup as a bonus.

## Decisions
- **Data source: Hacker News via Algolia** (`https://hn.algolia.com/api/v1/search?tags=story&query=...`). No API key and no quota, so a reviewer can run the project with nothing to sign up for. `tags=story` is required: without it the search mixes stories and comments, which have different fields.
- **AI: Anthropic Claude behind a summarizer interface, plus a mock**, selected by `SUMMARIZER=mock|claude`. A reviewer without a key can still run everything, and tests never call the network.
- **Caching: cache-aside in Redis**, keyed by article id. A summary of an unchanged article never changes, while generating one is slow, costs money and is rate-limited.
- **One app container; the scheduler (APScheduler) runs in-process with FastAPI.** Simplest thing that meets the requirement. At scale, several app replicas would each run a scheduler and fetch in duplicate; the answer then is a separate single-instance scheduler service.
- **Postgres and Redis run from `docker-compose.yml`** using official images, so nothing has to be installed locally besides Docker.

- **Summary input: the linked page's text**, extracted from its HTML at summary time, falling back to `story_text` and then the title when the page can't be fetched. Most HN stories carry only a title and URL, so summarizing the page is the only way to summarize the article itself rather than its headline. Decided 2026-10-08.

## Plan
Milestones and the definition of done: `docs/MILESTONES.md`.
