"""
Database Utilities

Connection pool management using asyncpg for direct PostgreSQL access.
Works with both Supabase PostgreSQL (Phase A) and AWS RDS (Phase B) -
just change DB_HOST environment variable.
"""

import asyncio
import logging
import os
import json
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from dateutil import parser
from fastapi import HTTPException

import asyncpg
import redis

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manager class for PostgreSQL (asyncpg) + Redis connections"""

    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None
        self._redis_client = None

    async def connect(self):
        """Initialize the asyncpg connection pool"""
        if self._pool is not None:
            return

        db_host = os.environ.get("DB_HOST")
        db_port = int(os.environ.get("DB_PORT", 5432))
        db_name = os.environ.get("DB_NAME", "postgres")
        db_user = os.environ.get("DB_USER", "postgres")
        db_password = os.environ.get("DB_PASSWORD")

        if not db_host or not db_password:
            raise ValueError("Database credentials not configured (DB_HOST, DB_PASSWORD required)")

        ssl_mode = os.environ.get("DB_SSL_MODE", "require")
        ssl = ssl_mode if ssl_mode != "disable" else False

        async def _init_connection(conn):
            await conn.set_type_codec(
                'jsonb', encoder=json.dumps, decoder=json.loads, schema='pg_catalog'
            )
            await conn.set_type_codec(
                'json', encoder=json.dumps, decoder=json.loads, schema='pg_catalog'
            )

        self._pool = await asyncpg.create_pool(
            host=db_host,
            port=db_port,
            database=db_name,
            user=db_user,
            password=db_password,
            ssl=ssl,
            min_size=3,
            max_size=20,
            command_timeout=30,
            init=_init_connection,
        )
        logger.info(f"PostgreSQL pool connected to {db_host}:{db_port}/{db_name}")

    async def close(self):
        """Close the connection pool"""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("PostgreSQL pool closed")

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Database pool not initialized. Call await db_manager.connect() first.")
        return self._pool

    # ------------------------------------------------------------------
    # Convenience query methods
    # ------------------------------------------------------------------

    async def fetch(self, query: str, *args) -> List[asyncpg.Record]:
        """Execute query and return all rows"""
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args) -> Optional[asyncpg.Record]:
        """Execute query and return first row"""
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args):
        """Execute query and return first column of first row"""
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    async def execute(self, query: str, *args) -> str:
        """Execute a statement (INSERT/UPDATE/DELETE)"""
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def executemany(self, query: str, args_list: list) -> None:
        """Execute a statement with multiple sets of arguments"""
        async with self.pool.acquire() as conn:
            await conn.executemany(query, args_list)

    # ------------------------------------------------------------------
    # Redis property
    # ------------------------------------------------------------------

    @property
    def redis(self) -> redis.StrictRedis:
        """Get the Redis client instance"""
        if not self._redis_client:
            redis_host = os.environ.get("REDIS_HOST")
            redis_port = os.environ.get("REDIS_PORT")
            redis_username = os.environ.get("REDIS_USERNAME")
            redis_password = os.environ.get("REDIS_PASSWORD")

            if not redis_host or not redis_port:
                raise ValueError("Redis credentials not configured")

            self._redis_client = redis.StrictRedis(
                host=redis_host,
                port=int(redis_port),
                username=redis_username,
                password=redis_password,
                db=0,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5,
                retry_on_timeout=True,
                connection_pool=redis.ConnectionPool(
                    host=redis_host,
                    port=int(redis_port),
                    username=redis_username,
                    password=redis_password,
                    db=0,
                    max_connections=50,
                    retry_on_timeout=True,
                    socket_keepalive=True,
                    socket_keepalive_options={},
                )
            )
        return self._redis_client

    # ------------------------------------------------------------------
    # Health checks
    # ------------------------------------------------------------------

    async def test_connections(self) -> Dict[str, bool]:
        """Test database connections and return status"""
        status = {}

        try:
            result = await self.fetchval("SELECT get_service_status()")
            status['database'] = result == 'ok'
        except Exception as e:
            logger.error(f"Database health check failed: {str(e)}")
            status['database'] = False

        try:
            ping_result = self.redis.ping()
            status['redis'] = ping_result
        except Exception as e:
            logger.error(f"Redis connection test failed: {str(e)}")
            status['redis'] = False

        return status


# Global instance
db_manager = DatabaseManager()


def get_db() -> DatabaseManager:
    """Get the database manager instance"""
    return db_manager


def get_redis_client() -> redis.StrictRedis:
    """Get the Redis client"""
    return db_manager.redis


# ------------------------------------------------------------------
# Helper: convert asyncpg.Record to dict
# ------------------------------------------------------------------

def record_to_dict(record: Optional[asyncpg.Record]) -> Optional[Dict[str, Any]]:
    """Convert an asyncpg Record to a plain dict, handling UUID/datetime serialization"""
    if record is None:
        return None
    return {k: _serialize_value(v) for k, v in dict(record).items()}


def records_to_list(records: List[asyncpg.Record]) -> List[Dict[str, Any]]:
    """Convert a list of asyncpg Records to a list of dicts"""
    return [record_to_dict(r) for r in records]


def _serialize_value(v):
    """Serialize asyncpg values to JSON-compatible types"""
    import uuid as _uuid
    if isinstance(v, _uuid.UUID):
        return str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    return v


# ------------------------------------------------------------------
# Cache Manager (unchanged - still uses Redis)
# ------------------------------------------------------------------

class CacheManager:
    """Manager for Redis caching operations"""

    def __init__(self, redis_client: Optional[redis.StrictRedis] = None):
        self.redis = redis_client or get_redis_client()

    async def get_cached_data(self, key: str) -> Optional[Any]:
        try:
            cached_data = self.redis.get(key)
            if cached_data:
                return json.loads(cached_data)
            return None
        except Exception as e:
            logger.warning(f"Cache get failed for key {key}: {str(e)}")
            return None

    async def set_cached_data(self, key: str, data: Any, expiry: int = 300) -> bool:
        try:
            self.redis.setex(key, expiry, json.dumps(data))
            return True
        except Exception as e:
            logger.warning(f"Cache set failed for key {key}: {str(e)}")
            return False

    async def delete_cached_data(self, key: str) -> bool:
        try:
            self.redis.delete(key)
            return True
        except Exception as e:
            logger.warning(f"Cache delete failed for key {key}: {str(e)}")
            return False


cache_manager = CacheManager()
