FROM python:3.12-slim

WORKDIR /app

# Dependencies first, in their own layer: Docker reuses it on every build
# where requirements.txt did not change, so editing code does not reinstall.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Run as an unprivileged user rather than root.
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# 0.0.0.0: accept connections from outside the container, not only from itself.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
