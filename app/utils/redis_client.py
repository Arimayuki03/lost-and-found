import redis
from config.config import Config


# 获取指定键的值
def get(key):
    return redis_client.get(key)


# 设置键值对并指定过期时间
def setex(key, timeout, value):
    return redis_client.setex(key, timeout, value)


# 删除指定的键
def delete(key):
    return redis_client.delete(key)


# 键值自增（用于计数类限流），返回自增后的值
def incr(key):
    return redis_client.incr(key)


# 原子设置（nx=True 时仅当键不存在才写入并返回 True）：匹配任务等分布式互斥锁使用
def set(key, value, nx=False, ex=None):
    return redis_client.set(key, value, nx=nx, ex=ex)


# 设置键的过期时间（秒）
def expire(key, seconds):
    return redis_client.expire(key, seconds)


# 创建 Redis 客户端
def create_redis_client():
    return redis.StrictRedis(
        host=Config.REDIS_HOST,
        port=Config.REDIS_PORT,
        db=Config.REDIS_DB,
        # Config 里定义了 REDIS_PASSWORD 但此前从未传入，配置了密码也不会生效
        password=Config.REDIS_PASSWORD or None,
        decode_responses=True
    )


# 初始化 Redis 客户端
redis_client = create_redis_client()
