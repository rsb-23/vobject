ARG PYTHON_VERSION
FROM python:${PYTHON_VERSION}-slim
WORKDIR /app

RUN pip install --upgrade pip
COPY ./requirements.txt /app/requirements.txt
RUN pip install -r requirements.txt

COPY tests /app/tests
COPY vobject /app/vobject
COPY ./.pre-commit-config.yaml /app/.pre-commit-config.yaml
COPY ./pyproject.toml /app/pyproject.toml

CMD ["python", "-m", "unittest", "discover"]
