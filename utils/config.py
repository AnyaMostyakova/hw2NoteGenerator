import os
from datetime import datetime
from threading import Lock
from dataclasses import dataclass

import boto3
import logging

@dataclass(frozen=True)
class YandexConfig:
    yc_api_key: str = os.environ.get("YC_API_KEY")
    ymq_queue_url: str = os.environ.get("YMQ_QUEUE_URL")
    yandex_bucket: str = os.environ.get("YANDEX_BUCKET")
    api_url: str = os.environ.get("API_URL", "https://cloud-api.yandex.net/v1/disk/public/resources")
    yc_secret_key: str = os.environ.get("YC_SECRET_KEY")
    yc_folder_id: str = os.environ.get("YC_FOLDER_ID")
    gpt_api_url: str = os.environ.get("GPT_API_URL", "https://llm.api.cloud.yandex.net/foundationModels/v1/completion")
    recognize_url: str = os.environ.get("RECOGNIZE_URL",
                                        "https://transcribe.api.cloud.yandex.net/speech/stt/v2/longRunningRecognize")
    operation_api_base: str = os.environ.get("OPERATION_API_BASE", "https://operation.api.cloud.yandex.net/operations")
    mq_client_endpoint: str = os.environ.get("MQ_CLIENT_ENDPOINT", "https://message-queue.api.cloud.yandex.net")
    s3_endpoint: str = os.environ.get("S3_ENDPOINT", "https://storage.yandexcloud.net")

@dataclass(frozen=True)
class PathsConfig:
    task_json_key_template: str = "tasks/task_{task_id}.json"
    video_tmp_path_template: str = "/tmp/video_{task_id}.mp4"
    audio_key_template: str = "tmp/audio_{task_id}.ogg"
    file_url_template: str = "https://{bucket}.storage.yandexcloud.net/{key}"
    pdf_font_name: str = "deja_vu"
    pdf_font_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    pdf_task_key_template: str = "tasks/task_{task_id}.pdf"


@dataclass(frozen=True)
class GPTConfig:
    gpt_model_uri: str = "gpt://{folder_id}/yandexgpt"
    prompt: str = (
        "Сделай полный, структурированный и подробный конспект лекции '{title}' из текста:\n"
        "{text}\n"
        "Включи основные идеи, примеры, пояснения и выводы.\n"
        "Используй обычный текст, без Markdown: не используй *курсив*, **жирный**, списки со звездочками или тире."
    )

yandex_cfg = YandexConfig()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("note-generator")


def get_s3():
    return boto3.client(
        's3',
        endpoint_url=yandex_cfg.s3_endpoint,
        region_name='ru-central1',
        aws_access_key_id=os.environ.get("YANDEX_ACCESS_KEY"),
        aws_secret_access_key=os.environ.get("YANDEX_SECRET_KEY"),
    )

def get_mq():
    return boto3.client(
        service_name='sqs',
        endpoint_url=yandex_cfg.mq_client_endpoint,
        region_name='ru-central1',
        aws_access_key_id=os.environ.get('YANDEX_ACCESS_KEY'),
        aws_secret_access_key=os.environ.get('YANDEX_SECRET_KEY')
    )

_id_lock = Lock()
_id_counter = 0
def next_id():
    global _id_counter
    with _id_lock:
        _id_counter += 1
        return int(datetime.now().timestamp()) * 1000 + _id_counter
