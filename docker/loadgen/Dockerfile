FROM python:3.11-slim-bookworm

WORKDIR /app

# Install httpx (only dependency needed)
RUN pip install --no-cache-dir httpx>=0.27.0

COPY loadgen.py .

# Use exec form for proper signal handling
CMD ["python", "loadgen.py"]
