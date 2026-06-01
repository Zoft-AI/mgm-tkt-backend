import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY')
    CHAT_AGENT_BASE_URL = os.getenv("CHAT_AGENT_BASE_URL", "https://chat.zoft.ai:8000")
