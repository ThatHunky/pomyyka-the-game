"""Database session management for async SQLAlchemy."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings
from database.models import Base

# Create async engine
engine = create_async_engine(
    settings.db_url,
    echo=False,
    future=True,
)

# Create async session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency function to get database session.

    Yields:
        AsyncSession: Database session instance.
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def first_session(session_iterable) -> AsyncGenerator[AsyncSession, None]:
    """
    Yield exactly one session from a `get_session()`-style provider.

    Supports:
    - Real async generators (our `get_session()` implementation)
    - Test doubles that implement `__aiter__()` but return a *sync* iterator
      (as used in some unit tests).
    """
    aiter_fn = getattr(session_iterable, "__aiter__", None)
    if callable(aiter_fn):
        try:
            iterator = aiter_fn()
        except TypeError:
            # Some tests patch __aiter__ as `lambda x: iter([...])` on the instance.
            iterator = aiter_fn(session_iterable)
    else:
        iterator = iter(session_iterable)

    if hasattr(iterator, "__anext__"):
        session = await iterator.__anext__()  # type: ignore[no-any-return]
        try:
            yield session
        finally:
            aclose = getattr(iterator, "aclose", None)
            if callable(aclose):
                await aclose()
    else:
        # Synchronous iterator (typically from mocks in tests)
        session = next(iterator)
        yield session


async def init_db() -> None:
    """Initialize database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, checkfirst=True))
