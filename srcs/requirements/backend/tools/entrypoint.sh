#!/bin/sh
set -e

python manage.py wait_for_db
python manage.py migrate --noinput

if [ "${DJANGO_DEBUG:-0}" != "1" ]; then
    python manage.py collectstatic --noinput --clear > /dev/null
fi

python manage.py ensure_superuser

exec "$@"
