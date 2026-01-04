############################################
# ОБЩИЙ ПРЕФИКС ДЛЯ ВСЕХ РЕСУРСОВ
############################################
variable "prefix" {
  # Используется в именах:
  # - service account
  # - bucket
  # - registry
  # - serverless containers
  default = "vvot10"
}

############################################
# ИДЕНТИФИКАТОРЫ YANDEX CLOUD
############################################
variable "YC_CLOUD_ID" {
  # ID облака в Yandex Cloud
  # Пример: b1gxxxxxxxxxxxxxxxxx
  description = "Yandex Cloud ID"
  type        = string
}

variable "YC_FOLDER_ID" {
  # ID каталога (folder), в котором создаются все ресурсы
  # Пример: b1gxxxxxxxxxxxxxxxxx
  description = "Yandex Cloud Folder ID"
  type        = string
}

############################################
# DOCKER-ОБРАЗ ОСНОВНОГО ПРИЛОЖЕНИЯ (APP)
############################################
variable "DOCKER_IMAGE_URL" {
  # URL Docker-образа приложения
  # Пример: cr.yandex/<registry-id>/<repo>:latest
  description = "Docker (app) Image URL"
  type        = string
  default     = ""
}

variable "DOCKER_IMAGE_DIGEST" {
  # Digest Docker-образа (sha256:...)
  # Используется для фиксирования версии образа
  description = "Docker (app) Image digest"
  type        = string
  default     = ""
}

############################################
# DOCKER-ОБРАЗ ФОНОВОГО ВОРКЕРА (WORKER)
############################################
variable "DOCKER_WORKER_IMAGE_URL" {
  # URL Docker-образа воркера
  # Обычно используется для фоновой обработки задач
  description = "Docker (worker) Image URL"
  type        = string
  default     = ""
}

variable "DOCKER_WORKER_IMAGE_DIGEST" {
  # Digest Docker-образа воркера
  # Позволяет гарантировать запуск нужной версии
  description = "Docker (worker) Image digest"
  type        = string
  default     = ""
}
