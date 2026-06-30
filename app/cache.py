"""TTL in-memory cache for actuator part-number lookups using cachetools."""

from cachetools import TTLCache

actuator_cache: TTLCache = TTLCache(maxsize=500, ttl=3600)  # keyed by part_number string
