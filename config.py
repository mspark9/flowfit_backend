import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


class Settings:
    openai_api_key: str = os.environ["OPENAI_API_KEY"]
    frontend_url: str  = os.environ.get("FRONTEND_URL", "http://localhost:5173")
    port: int          = int(os.environ.get("PORT", 8000))
    app_timezone: str  = os.environ.get("APP_TIMEZONE", "Asia/Seoul")

    tavily_api_key: str = os.environ.get("TAVILY_API_KEY", "")

    db_host:     str = os.environ["DB_HOST"]
    db_port:     int = int(os.environ.get("DB_PORT", 5432))
    db_user:     str = os.environ["DB_USER"]
    db_password: str = os.environ["DB_PASSWORD"]
    db_database: str = os.environ["DB_DATABASE"]


settings = Settings()
