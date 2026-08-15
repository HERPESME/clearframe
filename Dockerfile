FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml LICENSE README.md ./
COPY src ./src
COPY webapp/dist ./webapp/dist

RUN pip install --no-cache-dir .

ENV CLEARFRAME_MODE=demo
EXPOSE 8080

CMD ["python", "-m", "clearframe", "serve", "--host", "0.0.0.0", "--port", "8080", "--out", "/data/out"]
