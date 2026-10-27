from sqlalchemy import event
from sqlmodel import Session, create_engine

from app.config import settings

settings.data_dir.mkdir(parents=True, exist_ok=True)
engine = create_engine(settings.database_url, connect_args={"check_same_thread": False, "timeout": 30} if settings.database_url.startswith("sqlite") else {})
if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def sqlite_setup(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")


def get_session():
    with Session(engine) as session:
        yield session
