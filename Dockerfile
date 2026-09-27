FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY gotracker ./gotracker
RUN pip install --no-cache-dir . && useradd --system --no-create-home gotracker
USER gotracker

ENTRYPOINT ["gotracker"]
# Poll every 5 minutes. Override, e.g. `docker run --rm --env-file .env IMAGE report -o - > report.html`
# (no -t: a TTY would merge the log lines on stderr into the HTML).
CMD ["poll", "--every", "300"]
