"""Async SQLAlchemy database engine and session."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def get_async_engine():
    """Lazy-create async engine only when needed (not in Celery workers)."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.config import settings

    return create_async_engine(
        settings.database_url,
        pool_size=5,
        max_overflow=10,
        echo=settings.debug,
    )


def get_async_session():
    """Lazy-create async session factory."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    engine = get_async_engine()
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    """FastAPI dependency for async DB sessions."""
    from sqlalchemy.ext.asyncio import AsyncSession

    session_factory = get_async_session()
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
