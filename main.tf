############################################
# БАЗОВЫЕ НАСТРОЙКИ TERRAFORM И ПРОВАЙДЕРА
############################################
terraform {
  # Указываем обязательные провайдеры
  required_providers {
    yandex = {
      source  = "yandex-cloud/yandex"
      version = ">= 0.90"
    }
  }

  # Минимально допустимая версия Terraform
  required_version = ">= 1.3"
}

############################################
# ПРОВАЙДЕР YANDEX CLOUD
############################################
provider "yandex" {
  # ID облака
  cloud_id  = var.YC_CLOUD_ID

  # ID каталога (folder)
  folder_id = var.YC_FOLDER_ID
}

############################################
# SERVICE ACCOUNT (СЕРВИСНЫЙ АККАУНТ)
############################################
resource "yandex_iam_service_account" "sa" {
  # Имя сервисного аккаунта
  name = "${var.prefix}-service-account"
}

############################################
# НАЗНАЧЕНИЕ РОЛЕЙ СЕРВИСНОМУ АККАУНТУ
############################################
resource "yandex_resourcemanager_folder_iam_member" "sa_roles" {
  # Назначаем сразу несколько ролей через for_each
  for_each = toset([
    "storage.editor",                     # Работа с Object Storage
    "container-registry.admin",            # Управление Container Registry
    "container-registry.images.pusher",    # Загрузка Docker-образов
    "ymq.admin",                           # Управление очередями YMQ
    "serverless.containers.invoker",       # Запуск serverless-контейнеров
    "ai.admin",                            # Администрирование AI-сервисов
    "ai.speechkit-stt.user",               # Распознавание речи
    "ai.languageModels.user",              # Работа с языковыми моделями
    "functions.functionInvoker",           # Вызов cloud-функций
  ])

  folder_id = var.YC_FOLDER_ID
  role      = each.key
  member    = "serviceAccount:${yandex_iam_service_account.sa.id}"
}

############################################
# STATIC ACCESS KEY ДЛЯ SERVICE ACCOUNT
############################################
resource "yandex_iam_service_account_static_access_key" "sa_static_key" {
  service_account_id = yandex_iam_service_account.sa.id

  # Ключ создаётся только после назначения ролей
  depends_on = [
    yandex_resourcemanager_folder_iam_member.sa_roles
  ]
}

############################################
# API KEY ДЛЯ AI / SPEECHKIT
############################################
resource "yandex_iam_service_account_api_key" "stt_key" {
  service_account_id = yandex_iam_service_account.sa.id

  # Разрешения для работы с AI
  scopes = [
    "yc.ai.speechkitStt.execute",
    "yc.ai.languageModels.execute"
  ]
}

############################################
# OUTPUT: КЛЮЧИ (SENSITIVE)
############################################
output "stt_api_key" {
  value     = yandex_iam_service_account_api_key.stt_key.secret_key
  sensitive = true
}

output "sa_static_key_access_key" {
  value     = yandex_iam_service_account_static_access_key.sa_static_key.access_key
  sensitive = true
}

output "sa_static_key_secret_key" {
  value     = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
  sensitive = true
}

############################################
# OBJECT STORAGE BUCKET
############################################
resource "yandex_storage_bucket" "tasks_bucket" {
  # Имя бакета
  bucket = "${var.prefix}-bucket"

  folder_id     = var.YC_FOLDER_ID
  force_destroy = true

  # Доступ по static access key
  access_key = yandex_iam_service_account_static_access_key.sa_static_key.access_key
  secret_key = yandex_iam_service_account_static_access_key.sa_static_key.secret_key

  # Запрещаем анонимный доступ
  anonymous_access_flags {
    read         = false
    list         = false
    config_read = false
  }

  # Автоочистка временных файлов
  lifecycle_rule {
    id      = "cleanup-temp"
    enabled = true

    expiration {
      days = 1
    }
  }
}

############################################
# MESSAGE QUEUE (YMQ)
############################################
resource "yandex_message_queue" "tasks_queue" {
  # Очередь создаётся после назначения ролей
  depends_on = [yandex_resourcemanager_folder_iam_member.sa_roles]

  name = "${var.prefix}-tasks"

  # Время скрытия сообщения после получения
  visibility_timeout_seconds = 60

  # Long polling
  receive_wait_time_seconds = 20

  # Хранение сообщений
  message_retention_seconds = 3600

  access_key = yandex_iam_service_account_static_access_key.sa_static_key.access_key
  secret_key = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
}

output "ymq_queue_url" {
  value     = yandex_message_queue.tasks_queue.id
  sensitive = true
}

############################################
# CONTAINER REGISTRY
############################################
resource "yandex_container_registry" "registry" {
  name = "${var.prefix}-registry"
}

resource "yandex_container_repository" "app_repo" {
  # Репозиторий для основного приложения
  name = "${yandex_container_registry.registry.id}/${var.prefix}-app"
}

resource "yandex_container_repository" "worker_repo" {
  # Репозиторий для воркера
  name = "${yandex_container_registry.registry.id}/${var.prefix}-worker"
}

############################################
# OUTPUT: DOCKER URLS
############################################
output "registry_id" {
  value = yandex_container_registry.registry.id
}

output "docker_push_url_app" {
  value = "cr.yandex/${yandex_container_repository.app_repo.name}"
}

output "docker_push_url_worker" {
  value = "cr.yandex/${yandex_container_repository.worker_repo.name}"
}

############################################
# SERVERLESS CONTAINER: APP
############################################
resource "yandex_serverless_container" "app" {
  name        = "${var.prefix}-app"
  memory      = 512
  concurrency = 2

  service_account_id = yandex_iam_service_account.sa.id

  image {
    url    = var.DOCKER_IMAGE_URL
    digest = var.DOCKER_IMAGE_DIGEST

    # Переменные окружения контейнера
    environment = {
      YMQ_QUEUE_URL       = yandex_message_queue.tasks_queue.id
      YANDEX_BUCKET       = "${var.prefix}-bucket"
      YC_FOLDER_ID        = var.YC_FOLDER_ID
      YANDEX_ACCESS_KEY   = yandex_iam_service_account_static_access_key.sa_static_key.access_key
      YANDEX_SECRET_KEY   = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
      YC_API_KEY          = yandex_iam_service_account_api_key.stt_key.secret_key
    }
  }

  runtime {
    type = "http"
  }

  # Минимум один инстанс всегда запущен
  provision_policy {
    min_instances = 1
  }
}

############################################
# ПУБЛИЧНЫЙ ДОСТУП К APP
############################################
resource "yandex_serverless_container_iam_binding" "public" {
  container_id = yandex_serverless_container.app.id
  role         = "serverless.containers.invoker"
  members      = ["system:allUsers"]
}

############################################
# SERVERLESS CONTAINER: WORKER
############################################
resource "yandex_serverless_container" "worker" {
  name        = "${var.prefix}-worker"
  memory      = 512
  concurrency = 1

  service_account_id = yandex_iam_service_account.sa.id

  image {
    url    = var.DOCKER_WORKER_IMAGE_URL
    digest = var.DOCKER_WORKER_IMAGE_DIGEST

    environment = {
      YMQ_QUEUE_URL       = yandex_message_queue.tasks_queue.id
      YANDEX_BUCKET       = "${var.prefix}-bucket"
      YC_FOLDER_ID        = var.YC_FOLDER_ID
      YANDEX_ACCESS_KEY   = yandex_iam_service_account_static_access_key.sa_static_key.access_key
      YANDEX_SECRET_KEY   = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
      YC_API_KEY          = yandex_iam_service_account_api_key.stt_key.secret_key
    }
  }

  runtime {
    type = "http"
  }

  provision_policy {
    min_instances = 1
  }
}

############################################
# OUTPUT: PUBLIC URLS
############################################
output "public_url" {
  value = yandex_serverless_container.app.url
}

output "public_worker_url" {
  value = yandex_serverless_container.worker.url
}
