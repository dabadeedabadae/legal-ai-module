from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    redis_url: str
    ollama_host: str
    ollama_model: str
    laravel_api_key: str
    adilet_base_url: str
    parser_delay_seconds: int = 2
    groq_api_key: str = ""
    llm_provider: str = "groq"

    class Config:
        env_file = ".env"

settings = Settings()
