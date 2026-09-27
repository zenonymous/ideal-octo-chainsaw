FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY gotracker ./gotracker
RUN pip install --no-cache-dir . && useradd --system --no-create-home gotracker
USER gotracker

ENTRYPOINT ["gotracker"]
# Poll every 5 minutes. Override, e.g. `docker run ... report -o - > report.html`.
CMD ["poll", "--every", "300"]
