from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.ext.declarative import declarative_base
from config import settings


SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL


# connect_args = {"check_same_thread": False} if SQLALCHEMY_DATABASE_URL.startswith("sqlite") else {}


engine = create_async_engine(
                            SQLALCHEMY_DATABASE_URL, 
                             # 1. Optimize connection pool size for FastAPI
                            pool_size=20, 
                            max_overflow=10,
                            pool_pre_ping=True,  # Test the connection before using it
                            pool_recycle=300,
                            # 2. REQUIRED FOR NEON POOLER: Disable prepared statement caching
                            connect_args={
                                "prepared_statement_cache_size": 0,
                                "statement_cache_size": 0
                            }
                            )
SessionLocal = async_sessionmaker(
    autocommit=False, 
    autoflush=False, 
    bind=engine, 
    class_=AsyncSession,
    expire_on_commit=False
)

Base = declarative_base()

async def get_db():
    async with SessionLocal() as db:
        yield db