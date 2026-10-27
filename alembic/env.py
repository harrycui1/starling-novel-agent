from alembic import context
from sqlmodel import SQLModel
from app.db import engine
from app import models

with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=SQLModel.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
