FROM python:3.14-slim

# Install system dependencies for PostgreSQL
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app

# Copy dependency file first for better layer caching
COPY pyproject.toml ./

# Install dependencies (extracted from pyproject.toml)
# Note: For better caching, we install dependencies before copying source
# Recommended change for Dockerfile
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .
# Copy application code
COPY . .

# Switch to non-root user
USER appuser

# Default command (can be overridden in docker-compose)
CMD ["python", "main.py"]
