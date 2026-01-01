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
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    "aiogram>=3.17,<4.0" \
    "asyncpg>=0.29.0" \
    "sqlalchemy[asyncio]>=2.0.0" \
    "alembic>=1.13.0" \
    "redis>=5.2.0,<6.0" \
    "apscheduler>=3.10.0" \
    "google-genai==1.56.0" \
    "pydantic>=2.10,<3.0" \
    "pydantic-settings>=2.1.0" \
    "structlog>=24.1.0" \
    "python-dotenv>=1.0.0"

# Copy application code
COPY . .

# Switch to non-root user
USER appuser

# Default command (can be overridden in docker-compose)
CMD ["python", "-m", "bot"]
