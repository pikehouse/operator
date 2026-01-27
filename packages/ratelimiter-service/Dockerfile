FROM python:3.11-slim-bookworm

WORKDIR /app

# Install curl for healthcheck (required in slim image)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency specification first for layer caching
COPY pyproject.toml .

# Install the package
RUN pip install --no-cache-dir .

# Copy source code
COPY src/ ./src/

# Expose port
EXPOSE 8000

# Use exec form for proper signal handling (graceful shutdown)
CMD ["uvicorn", "ratelimiter_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
