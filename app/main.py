############################################
# ИМПОРТ СТАНДАРТНЫХ БИБЛИОТЕК
############################################
import json
from datetime import datetime, timedelta
from typing import Optional, List

############################################
# СТОРОННИЕ БИБЛИОТЕКИ
############################################
import requests
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

############################################
# ВНУТРЕННИЕ УТИЛИТЫ ПРОЕКТА
############################################
from utils.config import (
    get_s3,          # Подключение к Object Storage
    next_id,         # Генерация уникального ID задачи
    get_mq,          # Подключение к Message Queue
    logger,          # Логгер
    YandexConfig,    # Конфигурация Yandex Cloud
    PathsConfig      # Конфигурация путей в S3
)

############################################
# ЗАГРУЗКА КОНФИГУРАЦИЙ
############################################
yandex_cfg = YandexConfig()   # Конфигурация облака и API
paths_cfg = PathsConfig()     # Шаблоны путей для хранения файлов

############################################
# ИНИЦИАЛИЗАЦИЯ FASTAPI
############################################
app = FastAPI(title="Note Generator")

# Подключение шаблонов Jinja2
templates = Jinja2Templates(directory="templates")

############################################
# ПРОВЕРКА ССЫЛКИ НА ЯНДЕКС.ДИСК
############################################
def validate_yandex_disk_link(public_url: str) -> Optional[dict]:
    """
    Проверяет публичную ссылку Яндекс.Диска через API.
    Возвращает метаданные файла или None, если ссылка некорректна.
    """
    params = {"public_key": public_url}

    try:
        # Отправляем запрос к API Яндекс.Диска
        resp = requests.get(
            yandex_cfg.api_url,
            params=params,
            timeout=10
        )

        # Если ответ успешный — возвращаем JSON
        if resp.status_code == 200:
            return resp.json()
        else:
            return None

    except Exception as e:
        # Логируем ошибку запроса
        logger.exception(f"Error validating Yandex Disk link: {e}")
        return None

############################################
# СОХРАНЕНИЕ ЗАДАЧИ В OBJECT STORAGE
############################################
def save_task_to_bucket(task: dict):
    """
    Сохраняет задачу в Object Storage в виде JSON-файла.
    """
    s3 = get_s3()

    # Формируем путь к файлу задачи
    key = paths_cfg.task_json_key_template.format(task_id=task['id'])

    # Загружаем JSON в бакет
    s3.put_object(
        Bucket=yandex_cfg.yandex_bucket,
        Key=key,
        Body=json.dumps(task, ensure_ascii=False).encode('utf-8'),
        ContentType="application/json"
    )

############################################
# ПОЛУЧЕНИЕ СПИСКА ВСЕХ ЗАДАЧ ИЗ BUCKET
############################################
def list_tasks_from_bucket() -> List[dict]:
    """
    Читает все JSON-файлы задач из Object Storage
    и возвращает список задач.
    """
    s3 = get_s3()
    tasks = []

    # Используем paginator для корректной работы с большим количеством объектов
    paginator = s3.get_paginator("list_objects_v2")

    try:
        for page in paginator.paginate(
            Bucket=yandex_cfg.yandex_bucket,
            Prefix="tasks/"
        ):
            for item in page.get("Contents", []):
                key = item["Key"]

                # Пропускаем не JSON-файлы
                if not key.endswith(".json"):
                    continue

                # Читаем содержимое файла
                obj = s3.get_object(
                    Bucket=yandex_cfg.yandex_bucket,
                    Key=key
                )
                body = obj["Body"].read().decode("utf-8")
                task = json.loads(body)
                tasks.append(task)

    except s3.exceptions.NoSuchBucket:
        logger.error(
            "Bucket %s not found",
            yandex_cfg.yandex_bucket
        )

    return tasks

############################################
# ГЛАВНАЯ СТРАНИЦА (ФОРМА)
############################################
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """
    Отображает главную страницу с формой создания задачи.
    """
    return templates.TemplateResponse(
        "index.html",
        {"request": request}
    )

############################################
# ОБРАБОТКА ФОРМЫ СОЗДАНИЯ ЗАДАЧИ
############################################
@app.post("/submit")
def submit_task(
    title: str = Form(...),
    yandex_disk_url: str = Form(...)
):
    """
    Создаёт новую задачу, валидирует входные данные
    и отправляет задачу в очередь.
    """
    mq = get_mq()
    task_id = next_id()

    # Приводим время к московскому
    moscow_time = (
        datetime.now() + timedelta(hours=3)
    ).strftime("%Y-%m-%d %H:%M:%S")

    # Базовая структура задачи
    task = {
        "id": task_id,
        "title": title,
        "created_at": moscow_time,
        "status": "queued",
        "yandex_disk_url": yandex_disk_url,
        "result_pdf_url": None,
        "error_message": None,
        "metadata": None
    }

    ########################################
    # ПРОВЕРКА ЗАГОЛОВКА
    ########################################
    if not title.strip():
        task["status"] = "error"
        task["error_message"] = "Title is required"
        save_task_to_bucket(task)
        return RedirectResponse(
            url="/tasks",
            status_code=303
        )

    ########################################
    # ПРОВЕРКА ССЫЛКИ НА ЯНДЕКС.ДИСК
    ########################################
    meta = validate_yandex_disk_link(yandex_disk_url)

    if not meta or not meta.get("file"):
        task["status"] = "error"
        task["error_message"] = (
            f"Invalid Yandex Disk link (task_id={task_id})"
        )
        save_task_to_bucket(task)
        return RedirectResponse(
            url="/tasks",
            status_code=303
        )

    # Сохраняем метаданные файла
    task["metadata"] = meta
    save_task_to_bucket(task)

    ########################################
    # ОТПРАВКА ЗАДАЧИ В MESSAGE QUEUE
    ########################################
    try:
        mq.send_message(
            QueueUrl=yandex_cfg.ymq_queue_url,
            MessageBody=json.dumps(
                {"task_id": task_id}
            )
        )
    except Exception:
        task["status"] = "error"
        task["error_message"] = "Failed to enqueue task"
        save_task_to_bucket(task)

    return RedirectResponse(
        url="/tasks",
        status_code=303
    )

############################################
# HTML-СТРАНИЦА СО СПИСКОМ ЗАДАЧ
############################################
@app.get("/tasks", response_class=HTMLResponse)
def get_tasks(request: Request):
    """
    Отображает список всех задач, отсортированных по дате.
    """
    tasks = list_tasks_from_bucket()

    # Парсинг даты для сортировки
    def parse_dt(s):
        try:
            return datetime.strptime(
                s,
                "%Y-%m-%d %H:%M:%S"
            )
        except Exception:
            return datetime.min

    tasks_sorted = sorted(
        tasks,
        key=lambda x: parse_dt(x.get("created_at", "")),
        reverse=True
    )

    return templates.TemplateResponse(
        "task_list.html",
        {
            "request": request,
            "tasks": tasks_sorted
        }
    )

############################################
# JSON API СО СПИСКОМ ЗАДАЧ
############################################
@app.get("/tasks/json", response_class=JSONResponse)
def get_tasks_json():
    """
    Возвращает список задач в формате JSON.
    """
    return list_tasks_from_bucket()
