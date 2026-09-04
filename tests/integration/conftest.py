"""Real RabbitMQ and Redis, in containers.

Why these are not `task_always_eager` tests: eager mode runs the task inline, in-process, skipping
JSON serialisation, the broker, and the Redis stream entirely -- which is precisely the machinery
most likely to be wrong. The whole point of this directory is to exercise the parts a fake cannot.
"""

import os
import pathlib
from collections.abc import Iterator

import pytest


pytest.importorskip("testcontainers", reason="integration tests need testcontainers + Docker")

from testcontainers.rabbitmq import RabbitMqContainer
from testcontainers.redis import RedisContainer


def _docker_is_available() -> bool:
    try:
        import docker

        docker.from_env().ping()
    except Exception:
        return False
    return True


#: Skip rather than error when there is no container runtime, so `pytest -m integration` on a
#: laptop without Docker reports honestly instead of dumping connection tracebacks.
requires_docker = pytest.mark.skipif(
    not _docker_is_available(), reason="no reachable Docker daemon"
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip only *this* directory's tests when there is no Docker.

    The hook is handed every collected item in the session, not just the ones under this conftest,
    so it must filter by path -- otherwise it silently skips the whole suite.
    """
    if _docker_is_available():
        return
    here = pathlib.Path(__file__).parent
    skip = pytest.mark.skip(reason="no reachable Docker daemon")
    for item in items:
        path = getattr(item, "path", None)
        if path is not None and here in pathlib.Path(path).parents:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    with RedisContainer("redis:8-alpine") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"


@pytest.fixture(scope="session")
def broker_url() -> Iterator[str]:
    with RabbitMqContainer("rabbitmq:4-alpine") as container:
        params = container.get_connection_params()
        yield f"amqp://guest:guest@{params.host}:{params.port}//"


@pytest.fixture(scope="session")
def worker_env(
    redis_url: str, broker_url: str, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[dict[str, str]]:
    """Point the whole package at the containers.

    Environment rather than fixture injection because the Celery app reads its broker URL at
    *import* time, and the worker imports the app itself.
    """
    data_dir = tmp_path_factory.mktemp("integration-data")
    (data_dir / "jobs").mkdir()

    env = {
        "BOT_TOKEN": "42:TESTTOKEN",
        "DATA_DIR": str(data_dir),
        "REDIS_URL": redis_url,
        "CELERY_BROKER_URL": broker_url,
        "CELERY_RESULT_BACKEND": redis_url.replace("/0", "/1"),
        "LOG_JSON": "false",
        "PROGRESS_MIN_INTERVAL": "0",
        "PROGRESS_MIN_RATIO": "0.2",
    }
    previous = {key: os.environ.get(key) for key in env}
    os.environ.update(env)

    from pdfbot.config import get_settings

    get_settings.cache_clear()
    yield env

    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    get_settings.cache_clear()
