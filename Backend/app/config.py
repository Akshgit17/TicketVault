from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SUPABASE_URL: str
    SUPABASE_SERVICE_KEY: str
    CLERK_JWT_ISSUER: str
    RAZORPAY_KEY_ID: str
    RAZORPAY_KEY_SECRET: str
    RAZORPAY_WEBHOOK_SECRET: str = "dummy"
    CRON_SECRET: str = "changeme"

    class Config:
        env_file = ".env"


settings = Settings()
