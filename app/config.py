from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    vapi_secret: str = "changeme"
    airtable_token: str = ""
    airtable_base_id: str = ""
    customers_table: str = "Customers"
    interactions_table: str = "Interactions"
    gemini_api_key: str = ""  # Phase 2
    vapi_private_key: str = ""  # Phase 2: server->VAPI API calls (e.g. GET /call/{id})


settings = Settings()
