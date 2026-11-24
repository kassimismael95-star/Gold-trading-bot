import os

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from database.models import Base


def get_database_url():
    database_url = os.getenv("DATABASE_URL", "")

    if not database_url:
        raise RuntimeError("DATABASE_URL is not set.")

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    return database_url


def create_engine_for_database():
    database_url = get_database_url()

    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_recycle=1800,
        future=True,
    )


def run_migrations():
    engine = create_engine_for_database()

    try:
        Base.metadata.create_all(engine)

        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_commands_status_created
                    ON commands (status, created_at);
                    """
                )
            )

            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_commands_bot_status
                    ON commands (bot_id, status);
                    """
                )
            )

            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_trades_bot_status
                    ON trades (bot_id, status);
                    """
                )
            )

            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_workers_status_heartbeat
                    ON workers (status, last_heartbeat_at);
                    """
                )
            )

        print("Database migrations completed successfully.")
        return True

    except SQLAlchemyError as error:
        print(f"Database migration failed: {error}")
        raise


if __name__ == "__main__":
    run_migrations()
