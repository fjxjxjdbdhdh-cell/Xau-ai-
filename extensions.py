from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from flask_cors import CORS
import redis

db = SQLAlchemy()
jwt = JWTManager()
cors = CORS()
redis_client = None

def get_redis():
    global redis_client
    if redis_client is None:
        redis_client = redis.Redis.from_url("redis://redis:6379/0", decode_responses=True)
    return redis_client
