# syntax=docker/dockerfile:1

# --- Builder stage: install dependencies ---
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# Install Python dependencies in a virtualenv
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && . /opt/venv/bin/activate \
    && pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# --- Final stage: minimal runtime image ---
FROM python:3.11-slim

WORKDIR /app

# Copy virtualenv from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application code
COPY deep_research_mcp.py .
COPY .env ./
# If there are other needed files, add COPY lines here

# Activate virtualenv by default
ENV PATH="/opt/venv/bin:$PATH"

# Set environment variables (override in Helm chart as needed)
ENV PYTHONUNBUFFERED=1

EXPOSE 8001

# Run the app
CMD ["python", "deep_research_mcp.py"]
