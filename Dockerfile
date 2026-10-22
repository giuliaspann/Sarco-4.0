# Immagine dell'app per AWS Lightsail (su Railway si usa ancora railway.json)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# collectstatic non legge il database: basta una chiave qualsiasi in fase di build
RUN DJANGO_SECRET_KEY=solo-build python manage.py collectstatic --noinput

RUN useradd --create-home app && chown -R app /app
USER app

EXPOSE 8000
# Come il preDeployCommand di Railway: migrazioni e primo utente ufficio, poi il server
CMD python manage.py prepara_deploy && exec gunicorn config.wsgi --bind 0.0.0.0:$PORT --workers 2 --timeout 90 --log-file -
