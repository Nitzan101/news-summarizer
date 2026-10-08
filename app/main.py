from fastapi import FastAPI

app = FastAPI(title="News Summarizer")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
