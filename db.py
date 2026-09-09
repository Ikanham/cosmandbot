import os
import asyncio
import logging
import aiomysql
from dotenv import load_dotenv

load_dotenv()

_pool = None
_pool_lock = asyncio.Lock()

# Cache mémoire pour guild_settings : {guild_id: settings_dict}
_settings_cache: dict[int, dict] = {}
_cache_lock = asyncio.Lock()

logger = logging.getLogger("db")


async def get_pool():
    global _pool
    if _pool is None:
        async with _pool_lock:
            if _pool is None:
                host = os.getenv("DB_HOST", "127.0.0.1")
                port = int(os.getenv("DB_PORT", "3306"))
                user = os.getenv("DB_USER")
                password = os.getenv("DB_PASSWORD")
                db = os.getenv("DB_NAME")

                logger.info(f"Initialisation du pool de connexions MySQL sur {host}:{port}/{db}...")
                _pool = await aiomysql.create_pool(
                    host=host,
                    port=port,
                    user=user,
                    password=password,
                    db=db,
                    autocommit=True,
                    charset="utf8mb4",
                    minsize=1,
                    maxsize=10,
                )
    return _pool


async def close_pool():
    global _pool
    async with _pool_lock:
        if _pool is not None:
            logger.info("Fermeture du pool de connexions MySQL...")
            _pool.close()
            await _pool.wait_closed()
            _pool = None
            logger.info("Pool de connexions MySQL fermé avec succès.")


async def fetchall(query: str, params: tuple | list | None = None) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(query, params or ())
            return await cur.fetchall()


async def fetchone(query: str, params: tuple | list | None = None) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(query, params or ())
            return await cur.fetchone()


async def execute(query: str, params: tuple | list | None = None) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, params or ())
            return cur.lastrowid


# -------------------------------------------------------------
# Système de Cache pour guild_settings
# -------------------------------------------------------------

async def get_guild_settings(guild_id: int) -> dict:
    """Récupère les réglages d'un serveur depuis le cache mémoire (ou BDD si absent)."""
    if guild_id in _settings_cache:
        return _settings_cache[guild_id]

    async with _cache_lock:
        if guild_id in _settings_cache:
            return _settings_cache[guild_id]

        row = await fetchone("SELECT * FROM guild_settings WHERE guild_id=%s", (guild_id,))
        settings = dict(row) if row else {}
        _settings_cache[guild_id] = settings
        return settings


def invalidate_guild_cache(guild_id: int | None = None):
    """Invalide le cache des réglages pour un serveur donné ou pour tous les serveurs."""
    if guild_id is None:
        _settings_cache.clear()
    else:
        _settings_cache.pop(guild_id, None)


def update_guild_cache(guild_id: int, key: str, value: any):
    """Met à jour une clé spécifique dans le cache d'un serveur."""
    if guild_id in _settings_cache:
        _settings_cache[guild_id][key] = value


# -------------------------------------------------------------
# Migrations & Indexation Automatique
# -------------------------------------------------------------

async def init_db_indexes():
    """Crée les tables, index et colonnes manquants pour maximiser les performances."""
    table_queries = [
        """
        CREATE TABLE IF NOT EXISTS conventions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            guild_id BIGINT NOT NULL,
            channel_id BIGINT NOT NULL,
            message_id BIGINT NOT NULL,
            role_id BIGINT NOT NULL,
            title VARCHAR(150) NOT NULL,
            role_name VARCHAR(100) NOT NULL,
            role_prefix VARCHAR(100) NULL,
            location VARCHAR(255) NOT NULL,
            description TEXT NULL,
            days_json TEXT NOT NULL,
            dedicated_channel_id BIGINT NULL,
            meetup_days_json TEXT NULL,
            meetup_roles_json TEXT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_guild (guild_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """,
        """
        CREATE TABLE IF NOT EXISTS convention_participants (
            id INT AUTO_INCREMENT PRIMARY KEY,
            convention_id INT NOT NULL,
            user_id BIGINT NOT NULL,
            day_name VARCHAR(50) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_conv_user_day (convention_id, user_id, day_name),
            INDEX idx_conv (convention_id),
            INDEX idx_user (user_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """,
    ]
    for q in table_queries:
        try:
            await execute(q)
        except Exception as e:
            logger.warning(f"Note création table : {e}")

    alter_queries = [
        "ALTER TABLE guild_settings ADD COLUMN mod_role_id BIGINT NULL",
        "ALTER TABLE scheduled_messages ADD INDEX idx_scheduled_due (sent, run_at)",
        "ALTER TABLE event_participants ADD UNIQUE KEY uk_event_user (event_id, user_id)",
        "ALTER TABLE birthdays ADD INDEX idx_birthdays_date (guild_id, date)",
        "ALTER TABLE countdowns ADD INDEX idx_countdowns_guild (guild_id, event_date)",
        "ALTER TABLE conventions ADD COLUMN dedicated_channel_id BIGINT NULL",
        "ALTER TABLE conventions ADD COLUMN role_prefix VARCHAR(100) NULL",
        "ALTER TABLE conventions ADD COLUMN meetup_days_json TEXT NULL",
        "ALTER TABLE conventions ADD COLUMN meetup_roles_json TEXT NULL",
    ]
    for q in alter_queries:
        try:
            await execute(q)
            logger.info(f"Optimisation BDD appliquée : {q}")
        except Exception:
            # L'index ou la colonne existe déjà, poursuite normale
            pass