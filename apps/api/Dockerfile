# CONSILIUM API image. Python 3.11 per CLAUDE.md tech-stack lock.
FROM python:3.11-slim

# WHY these env vars: no .pyc clutter in the image, and unbuffered stdout so
# container logs stream in real time (critical for the "no silent failure"
# logging discipline).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy requirements first so Docker layer-caches the pip install unless deps
# actually change.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# --host 0.0.0.0 so the port is reachable from outside the container.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
