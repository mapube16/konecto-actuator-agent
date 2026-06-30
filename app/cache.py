"""TTL in-memory cache for actuator queries using cachetools (actuator_cache only)."""

from cachetools import TTLCache

actuator_cache: TTLCache = TTLCache(maxsize=500, ttl=3600)  # keyed by part_number string
embedding_cache: TTLCache = TTLCache(maxsize=200, ttl=3600)  # keyed by query string
