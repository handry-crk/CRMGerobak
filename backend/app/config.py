from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Konfigurasi runtime dari environment (.env)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Stamp Bojot"
    mongo_url: str = "mongodb://localhost:27017"
    mongo_db: str = "stamp_bojot"
    public_base_url: str = "http://localhost:5173"  # URL frontend; dipakai di QR stiker
    secret_key: str = "ganti-dengan-rahasia-panjang"
    default_admin_name: str = "Admin"
    default_admin_pin: str = "1234"
    reset_admin_pin: bool = False  # true = saat start, PIN akun "Admin" bawaan di-set ulang ke default_admin_pin & dibuka kuncinya
    metrics_api_key: str = "ganti-api-key-metrics"
    admin_email: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "Stamp Bojot <noreply@cimolbojotaa.com>"
    backup_dir: str = "backups"
    enable_scheduler: bool = True
    use_mock_db: bool = False  # True = in-memory (mongomock) untuk coba cepat tanpa MongoDB; data hilang saat restart
    cors_origins: str = "*"


config = Config()
