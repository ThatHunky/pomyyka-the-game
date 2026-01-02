# Test Suite

This directory contains comprehensive tests for the pomyyka-the-game Telegram bot.

## Structure

- `conftest.py` - Shared fixtures and test configuration
- `utils/` - Tests for utility functions
- `services/` - Tests for business logic services
- `handlers/` - Tests for Telegram bot handlers
- `database/` - Tests for database models and sessions
- `middlewares/` - Tests for middleware components
- `integration/` - End-to-end integration tests

## Running Tests

### Run all tests
```bash
pytest
```

### Run with coverage
```bash
pytest --cov=. --cov-report=html
```

### Run specific test file
```bash
pytest tests/services/test_battle_engine.py
```

### Run only unit tests (fast)
```bash
pytest -m "not integration"
```

### Run only integration tests
```bash
pytest -m integration
```

### Run in watch mode (auto-rerun on changes)
```bash
ptw
# or
pytest-watch
```

## Test Markers

- `@pytest.mark.unit` - Unit tests (fast, isolated)
- `@pytest.mark.integration` - Integration tests (require external services)
- `@pytest.mark.slow` - Slow running tests

## Coverage Goals

- Overall: 80%+
- Critical paths (battle engine, redis locks): 90%+
- Utilities: 95%+
- Handlers: 70%+

## Fixtures

Key fixtures available in `conftest.py`:

- `db_session` - Database session for testing
- `redis_client` - Fake Redis client
- `drop_manager` - DropManager instance
- `mock_bot` - Mock Telegram Bot
- `telegram_user` - Mock Telegram user
- `sample_user_db` - Sample user in database
- `sample_card_template_db` - Sample card template in database
- `sample_user_card` - Sample user card in database

## Continuous Integration

Tests run automatically on:
- Pre-commit hooks (fast tests only)
- GitHub Actions on push/PR (full test suite)
