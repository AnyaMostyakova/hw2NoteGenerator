#!/bin/bash

set -e

REGISTRY_ID=$(terraform output -raw registry_id)

echo "Проверка на наличие образов.."
IMAGE_IDS=$(yc container image list --registry-id "$REGISTRY_ID" --format json | jq -r '.[].id')

if [ -z "$IMAGE_IDS" ]; then
  echo "Пусто. Образы отсутствуют"
else
  for IMAGE_ID in $IMAGE_IDS; do
    echo "Удаление образа с ID: $IMAGE_ID"
    yc container image delete "$IMAGE_ID"
  done
fi

echo "Все образы удалены. Запуск terraform destroy.."
terraform destroy -auto-approve \
  -var "DOCKER_IMAGE_URL=$IMAGE_NAME" \
  -var "DOCKER_IMAGE_DIGEST=$DIGEST" \
  -var "DOCKER_WORKER_IMAGE_URL=$WORKER_IMAGE_NAME" \
  -var "DOCKER_WORKER_IMAGE_DIGEST=$WORKER_DIGEST"
