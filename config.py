from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str

    # OpenAI Based
    OPENAI_BASE_URL: str
    MODEL_NAME: str
    
    # Security
    SECRET_KEY: str
    OPENAI_API_KEY: str
    
    # SMTP
    SMTP_SERVER: str
    SMTP_PORT: int
    SENDER_EMAIL: str
    SENDER_PASSWORD: str
    ADMIN_EMAIL: str

    # Cloudinary
    CLOUDINARY_CLOUD_NAME: str
    CLOUDINARY_API_KEY: str
    CLOUDINARY_API_SECRET: str

    PUBLIC_KEY: str
    PRIVATE_KEY: str
    SUBJECT: str

    # Tells Pydantic to read from the .env file
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

# lru_cache ensures the .env file is only read once. 
# Subsequent calls return the exact same cached object instantly.
@lru_cache()
def get_settings():
    return Settings()

# Instantiate it once to be imported across your app
settings = get_settings()