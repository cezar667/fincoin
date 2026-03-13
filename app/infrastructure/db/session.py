from collections.abc import Generator
from urllib.parse import urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.settings.config import get_settings

settings = get_settings()


def _connect_args_for(url: str) -> dict[str, object]:
    args: dict[str, object] = {}
    if url.startswith("sqlite"):
        args["check_same_thread"] = False
        return args

    parsed = urlparse(url)
    if parsed.scheme.startswith("postgresql"):
        # Avoid long startup hangs when Postgres is unavailable.
        args["connect_timeout"] = 3
    return args


def _build_engine(url: str) -> Engine:
    return create_engine(url, future=True, pool_pre_ping=True, connect_args=_connect_args_for(url))


def _can_connect(engine: Engine) -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("select 1"))
        return True
    except Exception:
        return False


primary_engine = _build_engine(settings.database_url)
if settings.database_url.startswith("sqlite") or _can_connect(primary_engine):
    engine = primary_engine
else:
    fallback_url = "sqlite+pysqlite:///./finsight.db"
    print(
        f"[FinSight] Warning: failed to connect to DATABASE_URL '{settings.database_url}'. "
        f"Falling back to '{fallback_url}'."
    )
    engine = _build_engine(fallback_url)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

