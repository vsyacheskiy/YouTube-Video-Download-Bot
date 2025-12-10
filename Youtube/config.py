import os
from dotenv import load_dotenv

# Load variables from .env if present
load_dotenv()


class Config(object):
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    API_ID = int(os.getenv("API_ID", "0"))
    API_HASH = os.getenv("API_HASH", "")
    # Add your channel id. For force Subscribe.
    CHANNEL = os.getenv("CHANNEL", "")
    # Skip or add your proxy from https://github.com/rg3/youtube-dl/issues/1091#issuecomment-230163061
    HTTP_PROXY = ''
