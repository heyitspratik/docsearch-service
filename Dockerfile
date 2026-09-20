FROM python:3.11-slim

WORKDIR /app

# System dependencies for building wheels like asyncpg
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv and project dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir uv && \
    uv pip install --system -r requirements.txt

COPY . .

CMD ["python", "main.py"]
