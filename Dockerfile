FROM python:3.12-slim-bookworm

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY lulu-agent/app ./app
COPY lulu-agent/prompts ./prompts
COPY lulu-agent/skills ./skills
COPY lulu-agent/configs ./configs
COPY lulu-agent/data ./seed
COPY docker-entrypoint.sh /docker-entrypoint.sh

RUN chmod +x /docker-entrypoint.sh \
  && mkdir -p /app/data/songs /app/data/memory_workspaces

EXPOSE 8000
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
