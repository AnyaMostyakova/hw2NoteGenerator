#!/bin/bash

set -e

terraform apply -auto-approve -target=yandex_container_registry.registry \
                -target=yandex_container_repository.app_repo \
                -target=yandex_container_repository.worker_repo

APP_IMAGE_URL=$(terraform output -raw docker_push_url_app)
APP_IMAGE_NAME="$APP_IMAGE_URL:latest"
echo "APP_IMAGE_NAME = $APP_IMAGE_NAME"
docker build -f docker/app/Dockerfile -t $APP_IMAGE_NAME .
docker push $APP_IMAGE_NAME
APP_DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' $APP_IMAGE_NAME | cut -d'@' -f2)

WORKER_IMAGE_URL=$(terraform output -raw docker_push_url_worker)
WORKER_IMAGE_NAME="$WORKER_IMAGE_URL:latest"
echo "WORKER_IMAGE_NAME: $WORKER_IMAGE_NAME"
docker build -f docker/worker/Dockerfile -t $WORKER_IMAGE_NAME .
docker push $WORKER_IMAGE_NAME
WORKER_DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' $WORKER_IMAGE_NAME | cut -d'@' -f2)

terraform taint -allow-missing yandex_serverless_container.app || true
terraform taint -allow-missing yandex_serverless_container.worker || true

terraform apply -auto-approve \
  -var "DOCKER_IMAGE_URL=$APP_IMAGE_NAME" \
  -var "DOCKER_IMAGE_DIGEST=$APP_DIGEST" \
  -var "DOCKER_WORKER_IMAGE_URL=$WORKER_IMAGE_NAME" \
  -var "DOCKER_WORKER_IMAGE_DIGEST=$WORKER_DIGEST"

export YMQ_QUEUE_URL=$(terraform output -raw ymq_queue_url)
export PUBLIC_URL=$(terraform output -raw public_url)
export PUBLIC_WORKER_URL=$(terraform output -raw public_worker_url)

echo "Ссылка на приложение: $PUBLIC_URL"
