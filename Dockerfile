FROM python:3.13-slim@sha256:27b7c9d4f13ca20bb1170148f02095d50a5dfce1f7f2dabf5ca273727e43b7ea
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 VI_MODE=private-beta PORT=10000
WORKDIR /app
RUN useradd --uid 10001 --create-home investigator
COPY requirements-beta.txt ./
RUN pip install --no-cache-dir -r requirements-beta.txt
COPY pyproject.toml vi_benchmark.py vi_grade.py vi_evaluate.py vi_review.py ./
COPY investigator/ ./investigator/
RUN pip install --no-cache-dir --no-deps '.[app]' && mkdir -p .cache/visual-investigator && chown -R investigator:investigator .cache
USER investigator
EXPOSE 10000
CMD ["python", "-m", "investigator.server", "--host", "0.0.0.0"]
