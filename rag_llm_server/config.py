import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')


class Config:
    VOLC_AK = os.getenv('VOLC_ACCESS_KEY', '')
    VOLC_SK = os.getenv('VOLC_SECRET_KEY', '')
    ARK_ENDPOINT_ID = os.getenv('ARK_ENDPOINT_ID', '')
    ARK_API_KEY = os.getenv('ARK_API_KEY', '')
    ARK_BASE_URL = os.getenv('ARK_BASE_URL', 'https://ark.cn-beijing.volces.com/api/v3')
    RTC_APP_ID = os.getenv('RTC_APP_ID', '')
    RTC_APP_KEY = os.getenv('RTC_APP_KEY', '')
    RTC_API_VERSION = '2025-06-01'
    SERVER_URL = os.getenv('SERVER_URL', '').rstrip('/')
    CALLBACK_API_KEY = os.getenv('CALLBACK_API_KEY', '')
    MOCK_MODE = os.getenv('MOCK_MODE', 'false').lower() == 'true'
    KB_MODE = os.getenv('KB_MODE', 'cloud')
    MILVUS_URI = os.getenv('MILVUS_URI', 'http://127.0.0.1:19530').rstrip('/')
    MILVUS_TOKEN = os.getenv('MILVUS_TOKEN', '')
    MILVUS_COLLECTION = os.getenv('MILVUS_COLLECTION', 'voice_commerce_v1')
    MILVUS_DATABASE = os.getenv('MILVUS_DATABASE', 'default')
    MILVUS_MIN_SCORE = float(os.getenv('MILVUS_MIN_SCORE', '0.45'))
    MILVUS_TIMEOUT = float(os.getenv('MILVUS_TIMEOUT', '2'))
    EMBEDDING_BASE_URL = os.getenv('EMBEDDING_BASE_URL', ARK_BASE_URL).rstrip('/')
    EMBEDDING_API_KEY = os.getenv('EMBEDDING_API_KEY', '') or ARK_API_KEY
    EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', '')
    EMBEDDING_API_PATH = os.getenv('EMBEDDING_API_PATH', '/embeddings/multimodal')
    EMBEDDING_DIMENSIONS = int(os.getenv('EMBEDDING_DIMENSIONS', '2048'))
    EMBEDDING_TIMEOUT = float(os.getenv('EMBEDDING_TIMEOUT', '3'))
    KB_COLLECTION_NAME = os.getenv('KB_COLLECTION_NAME', '')
    KB_PROJECT_NAME = os.getenv('KB_PROJECT_NAME', 'default')
    VOLC_ACCOUNT_ID = os.getenv('VOLC_ACCOUNT_ID', '')
    VOICE_CONFIG_FILE = ROOT / 'voice_config.json'

    def require(self, *names):
        missing = [name for name in names if not getattr(self, name, '')]
        if missing:
            raise ValueError('缺少配置: ' + ', '.join(missing))


settings = Config()
