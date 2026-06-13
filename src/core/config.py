import os
from pathlib import Path

from dotenv import load_dotenv


env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=env_path)

DB_HOST = os.getenv("DB_HOST", "postgres_db")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "myapp_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "your_secure_password_here")

B2B_URL = os.getenv("B2B_URL")
B2B_TO_MOD_KEY = os.getenv("B2B_TO_MOD_KEY")
MOD_TO_B2B_KEY = os.getenv("MOD_TO_B2B_KEY")

B2C_URL = os.getenv("B2C_URL")
B2B_TO_B2C_KEY = os.getenv("B2B_TO_B2C_KEY")
