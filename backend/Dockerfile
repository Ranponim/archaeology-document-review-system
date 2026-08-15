FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY . ./

CMD ["rq", "worker", "--url", "redis://redis:6379/0"]
