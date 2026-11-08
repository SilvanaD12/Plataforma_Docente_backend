#!/usr/bin/env bash
# Verificación de EN-011 en una base de datos temporal:
#   1. crea la base en011_verificacion en el contenedor db,
#   2. le aplica todas las migraciones con dbmate (prueba también que migran desde cero),
#   3. ejecuta verify_vector_store.sql,
#   4. elimina la base temporal (también si algo falla).
# La base de desarrollo no se modifica. Uso, desde backend/: ./database/verification/verify.sh
set -euo pipefail

cd "$(dirname "$0")/../.."

if [ ! -f .env ]; then
  echo "Falta el archivo .env. Créalo con: cp .env.example .env" >&2
  exit 1
fi
set -a
. ./.env
set +a

BD_TEMPORAL=en011_verificacion

psql_db() {
  docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" "$@"
}

eliminar_base_temporal() {
  psql_db -d postgres -q -c "DROP DATABASE IF EXISTS $BD_TEMPORAL" >/dev/null
}

echo "== Iniciando PostgreSQL (si no está en marcha) =="
docker compose up -d --wait db

echo "== Creando la base temporal $BD_TEMPORAL =="
eliminar_base_temporal
trap eliminar_base_temporal EXIT
psql_db -d postgres -q -c "CREATE DATABASE $BD_TEMPORAL"

echo "== Aplicando migraciones =="
docker compose run --rm \
  -e DATABASE_URL="postgres://$POSTGRES_USER:$POSTGRES_PASSWORD@db:5432/$BD_TEMPORAL?sslmode=disable" \
  dbmate --no-dump-schema up

echo "== Ejecutando la verificación =="
psql_db -d "$BD_TEMPORAL" < "./database/verification/verify_vector_store.sql"
