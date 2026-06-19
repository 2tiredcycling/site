from logging.config import fileConfig
import os
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from flask import Flask
from sqlalchemy import engine_from_config, pool

from app.models import db

config = context.config
PROJECT_ROOT = Path(__file__).resolve().parent.parent

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


target_metadata = db.metadata


def _load_flask_database_url() -> str:
    load_dotenv(PROJECT_ROOT / ".env")
    env = os.getenv("FLASK_ENV", "development").lower()
    app = Flask(__name__, instance_relative_config=True)
    if env == "production":
        app.config.from_object("config.ProductionConfig")
    else:
        app.config.from_object("config.DevelopmentConfig")
    return app.config["SQLALCHEMY_DATABASE_URI"]


def _configure_database_url() -> str:
    database_url = _load_flask_database_url()
    # Alembic config values use ConfigParser interpolation, so literal percent
    # signs in database URLs must be escaped before set_main_option.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return database_url


DATABASE_URL = _configure_database_url()


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    existing_connection = config.attributes.get("connection", None)
    if existing_connection is not None:
        context.configure(connection=existing_connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
