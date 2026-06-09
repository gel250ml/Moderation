import os
# from pathlib import Path
# from dotenv import load_dotenv

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
# env_path = Path(__file__).resolve().parents[2] / ".env"
# load_dotenv(dotenv_path=env_path)
MOD_TO_B2B_KEY = os.getenv("MOD_TO_B2B_KEY")
B2C_URL = os.getenv("B2C_URL")
B2B_TO_B2C_KEY = os.getenv("B2B_TO_B2C_KEY")
