import json
import os
import subprocess
import time
from datetime import datetime

import requests
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

from app.main import validate_yandex_disk_link
from utils.config import get_s3, next_id, get_mq, logger, YandexConfig, PathsConfig, GPTConfig

yandex_cfg = YandexConfig()
paths_cfg = PathsConfig()
gpt_cfg = GPTConfig()


def load_task_from_bucket(task_id: int) -> dict:
    s3 = get_s3()
    key = paths_cfg.task_json_key_template.format(task_id=task_id)
    obj = s3.get_object(Bucket=yandex_cfg.yandex_bucket, Key=key)
    return json.loads(obj["Body"].read())


def update_task_status(task: dict, status: str, error_message: str = None):
    s3 = get_s3()
    task["status"] = status
    if error_message:
        task["error_message"] = f"Task ID {task['id']}: {error_message}"
    key = paths_cfg.task_json_key_template.format(task_id=task['id'])
    s3.put_object(
        Bucket=yandex_cfg.yandex_bucket,
        Key=key,
        Body=json.dumps(task, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json"
    )


def download_video(url: str) -> str:
    local_path = paths_cfg.video_tmp_path_template.format(task_id=next_id())
    r = requests.get(url, stream=True)
    r.raise_for_status()
    with open(local_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    return local_path


def extract_audio(video_file: str) -> str:
    audio_file = video_file.replace(".mp4", ".ogg")
    cmd = [
        "ffmpeg",
        "-i", video_file,
        "-vn",
        "-c:a", "libopus",
        "-ar", "48000",
        "-b:a", "65536",
        audio_file
    ]
    subprocess.run(cmd, check=True)

    if not os.path.exists(audio_file):
        raise RuntimeError(f"Audio file was not created: {audio_file}")

    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_file
        ],
        capture_output=True,
        text=True
    )
    duration = float(result.stdout.strip() or 0)
    if duration <= 0:
        raise RuntimeError(f"Audio file has zero duration: {audio_file}")

    return audio_file


def upload_audio_to_bucket(audio_file: str, task_id: int) -> str:
    s3 = get_s3()
    key = paths_cfg.audio_key_template.format(task_id=task_id)
    s3.upload_file(audio_file, yandex_cfg.yandex_bucket, key)
    return paths_cfg.file_url_template.format(bucket=yandex_cfg.yandex_bucket, key=key)


def start_long_running_stt(file_uri: str) -> str:
    payload = {
        "config": {
            "specification": {
                "languageCode": "ru-RU",
                "model": "general",
                "profanityFilter": False,
                "literature_text": True,
                "audioEncoding": "OGG_OPUS",
                "rawResults": True

            }
        },
        "audio": {
            "uri": file_uri
        }
    }
    headers = {"Authorization": f"Api-Key {yandex_cfg.yc_api_key}"}
    r = requests.post(yandex_cfg.recognize_url, headers=headers, json=payload)
    r.raise_for_status()
    return r.json()["id"]


def wait_long_running_stt(operation_id: str, interval: int = 5) -> str:
    url = f"{yandex_cfg.operation_api_base}/{operation_id}"
    headers = {"Authorization": f"Api-Key {yandex_cfg.yc_api_key}"}
    while True:
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        data = r.json()
        if data.get("done"):
            chunks = data.get("response", {}).get("chunks", [])
            text = " ".join(
                chunk["alternatives"][0]["text"]
                for chunk in chunks
                if chunk.get("alternatives")
            )
            return text
        time.sleep(interval)


def generate_summary(text: str, title: str) -> str:
    headers = {
        "Authorization": f"Api-Key {yandex_cfg.yc_api_key}",
        "x-folder-id": yandex_cfg.yc_folder_id
    }
    payload = {
        "modelUri": gpt_cfg.gpt_model_uri.format(folder_id=yandex_cfg.yc_folder_id),
        "completionOptions": {
            "stream": False,
            "temperature": 0.5,
            "maxTokens": 2000
        },
        "messages": [
            {
                "role": "user",
                "text": gpt_cfg.prompt.format(title=title, text=text)
            }
        ]
    }
    r = requests.post(yandex_cfg.gpt_api_url, headers=headers, json=payload)
    if r.status_code != 200:
        raise Exception(f"YandexGPT error: {r.text}")

    data = r.json()

    try:
        return data["result"]["alternatives"][0]["message"]["text"].strip()
    except Exception:
        raise Exception(f"Unexpected response format: {data}")


def make_pdf(text: str, title: str) -> str:
    pdf_file = f"/tmp/{title}_{next_id()}.pdf"

    pdfmetrics.registerFont(TTFont(paths_cfg.pdf_font_name, paths_cfg.pdf_font_path))

    title_style = ParagraphStyle(
        name="TitleStyle",
        fontName=paths_cfg.pdf_font_name,
        fontSize=18,
        leading=22
    )
    normal_style = ParagraphStyle(
        name="NormalStyle",
        fontName=paths_cfg.pdf_font_name,
        fontSize=12,
        leading=14
    )

    doc = SimpleDocTemplate(pdf_file, pagesize=A4)

    story = [
        Paragraph(title, title_style),
        Spacer(1, 16)
    ]

    for line in text.split("\n"):
        story.append(Paragraph(line, normal_style))
        story.append(Spacer(1, 4))

    doc.build(story)
    return pdf_file


def save_pdf_to_bucket(task_id: int, pdf_file: str) -> str:
    s3 = get_s3()
    key = paths_cfg.pdf_task_key_template.format(task_id=task_id)
    s3.upload_file(pdf_file, yandex_cfg.yandex_bucket, key)
    url = s3.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": yandex_cfg.yandex_bucket, "Key": key},
        ExpiresIn=3600
    )
    return url


def process_task_wrapper(task_id: int):
    task = None
    try:
        task = load_task_from_bucket(task_id)
        update_task_status(task, "processing")

        meta = validate_yandex_disk_link(task["yandex_disk_url"])
        if not meta or not meta.get("file"):
            update_task_status(task, "error", "Invalid Yandex Disk link")
            return

        video_file = download_video(meta["file"])
        audio_file = extract_audio(video_file)
        audio_uri = upload_audio_to_bucket(audio_file, task["id"])

        operation_id = start_long_running_stt(audio_uri)
        recognized_text = wait_long_running_stt(operation_id)

        logger.info(f"STT text: {recognized_text[:500]}")
        if not recognized_text.strip():
            logger.error("STT get empty text")

        summary = generate_summary(recognized_text, task["title"])
        pdf_file = make_pdf(summary, task["title"])
        logger.info(f"PDF generated: {pdf_file}")

        pdf_url = save_pdf_to_bucket(task_id, pdf_file)
        logger.info(f"PDF loaded: {pdf_url}")

        task["result_pdf_url"] = pdf_url
        update_task_status(task, "completed")
        logger.info(f"Task status uploaded: {task['status']}")
    except Exception as e:
        if task:
            update_task_status(task, "error", str(e))
        logger.info(f"[{datetime.now()}] Task {task_id} failed: {e}")


def poll_queue():
    while True:
        mq = get_mq()
        response = mq.receive_message(
            QueueUrl=yandex_cfg.ymq_queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=10
        )
        messages = response.get("Messages", [])
        if not messages:
            continue
        for msg in messages:
            body = json.loads(msg["Body"])
            task_id = body.get("task_id")
            if task_id:
                process_task_wrapper(task_id)
            mq.delete_message(
                QueueUrl=yandex_cfg.ymq_queue_url,
                ReceiptHandle=msg["ReceiptHandle"]
            )


if __name__ == "__main__":
    poll_queue()
