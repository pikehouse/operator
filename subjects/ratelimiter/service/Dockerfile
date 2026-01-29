FROM python:3.11-slim-bookworm

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Copy and install dependencies
COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir .

# Run the service
CMD ["uvicorn", "ratelimiter_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
