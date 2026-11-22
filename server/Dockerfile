FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic.ini .
COPY alembic ./alembic
COPY entrypoint.sh .

RUN useradd --system --uid 10001 alkocop && mkdir -p /data/screenshots && chown -R alkocop /data
USER alkocop

ENV ALKOCOP_SCREENSHOT_DIR=/data/screenshots
EXPOSE 8000
ENTRYPOINT ["sh", "/srv/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
