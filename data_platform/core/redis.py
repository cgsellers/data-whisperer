"""Cliente Redis para colas y rate limiting"""
import redis.asyncio as redis
from .config import settings

redis_client: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    global redis_client
    if redis_client is None:
        redis_client = redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=10,
            socket_connect_timeout=10,
            retry_on_timeout=True,
        )
    return redis_client


async def close_redis():
    global redis_client
    if redis_client:
        await redis_client.close()
        redis_client = None


# ─────────────────────────────────────────────
# Rate Limiter (Token Bucket simple en Lua)
# ─────────────────────────────────────────────
RATE_LIMIT_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

redis.call('ZREMRANGEBYSCORE', key, 0, now - window * 1000)
local count = redis.call('ZCARD', key)

if count < limit then
    redis.call('ZADD', key, now, now .. '-' .. math.random())
    redis.call('EXPIRE', key, window)
    return {1, limit - count - 1}
else
    return {0, 0}
end
"""


async def check_rate_limit(identifier: str, limit: int = 100, window_seconds: int = 60) -> tuple[bool, int]:
    """Retorna (allowed, remaining)"""
    r = await get_redis()
    import time
    now_ms = int(time.time() * 1000)
    result = await r.eval(RATE_LIMIT_SCRIPT, 1, f"ratelimit:{identifier}", limit, window_seconds, now_ms)
    return bool(result[0]), int(result[1])


# ─────────────────────────────────────────────
# Helpers para Redis Streams
# ─────────────────────────────────────────────
async def stream_add(stream: str, data: dict) -> str:
    r = await get_redis()
    return await r.xadd(stream, data)


async def stream_read(stream: str, count: int = 10, block: int = 5000) -> list:
    r = await get_redis()
    return await r.xread({stream: "0"}, count=count, block=block)


async def stream_consume_group(stream: str, group: str, consumer: str, count: int = 10) -> list:
    r = await get_redis()
    try:
        await r.xgroup_create(stream, group, id="0", mkstream=True)
    except redis.ResponseError:
        pass  # Group ya existe
    return await r.xreadgroup(group, consumer, {stream: ">"}, count=count, block=5000)


async def stream_ack(stream: str, group: str, msg_id: str):
    r = await get_redis()
    await r.xack(stream, group, msg_id)