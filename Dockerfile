FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml LICENSE README.md ./
COPY src ./src
COPY webapp/dist ./webapp/dist

# The deployed image needs the cloud storage profile, live detectors and token
# verification. `cloud` brings google-genai and Video Intelligence; `gcp` brings
# Storage, Firestore and Tasks; `auth` brings firebase-admin.
#
# A plain `pip install .` — base dependencies, no Google packages at all —
# remains the supported local install, and the test suite runs under it. That is
# not sentimentality: it is what keeps 826 tests and the smoke script runnable
# with no credentials, and it only holds because every SDK import in this
# codebase sits inside a function body.
RUN pip install --no-cache-dir ".[cloud,gcp,auth]"

ENV CLEARFRAME_MODE=demo
EXPOSE 8080

# Overridden per service in cloudbuild.yaml — `serve` for the interface,
# `worker` for the container that runs analyses, `clearframe.mcp` for the tools.
CMD ["python", "-m", "clearframe", "serve", "--host", "0.0.0.0", "--port", "8080", "--out", "/data/out"]
