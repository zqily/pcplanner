import logging
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from config import DB_FILE

logger = logging.getLogger(__name__)

# Ensure database directory exists
if not DB_FILE.parent.exists():
    try:
        DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.critical(f"Failed to create database directory: {e}")
        raise

# Define Base Class
class Base(DeclarativeBase):
    pass

# Create Engine
# check_same_thread=False is needed for SQLite when used across multiple threads (GUI + Workers)
# We rely on SQLAlchemy's session pooling/scoping to handle thread safety at the session level.
engine = create_engine(
    f"sqlite:///{DB_FILE}", 
    echo=False, 
    connect_args={"check_same_thread": False}
)

# Enable Write-Ahead Logging (WAL) for better concurrency and performance
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL") # NORMAL is faster and safe enough for WAL
    cursor.close()

# Create Session Factory
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def init_db():
    """Initializes the database schema."""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info(f"Database initialized at {DB_FILE}")
    except Exception as e:
        logger.critical(f"Failed to initialize database schema: {e}", exc_info=True)
        raise