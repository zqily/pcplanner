import logging
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from config import DB_FILE

logger = logging.getLogger(__name__)

# Define Base Class
class Base(DeclarativeBase):
    pass

# Create Engine
# check_same_thread=False is needed because we use the session in different threads (GUI vs Workers)
# though best practice is one session per thread.
engine = create_engine(f"sqlite:///{DB_FILE}", echo=False, connect_args={"check_same_thread": False})

# Enable Write-Ahead Logging (WAL) for better concurrency
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

# Create Session Factory
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def init_db():
    """Initializes the database schema."""
    Base.metadata.create_all(bind=engine)
    logger.info(f"Database initialized at {DB_FILE}")

def get_db_session():
    """Returns a new database session."""
    return SessionLocal()