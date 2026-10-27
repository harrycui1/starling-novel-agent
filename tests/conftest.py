"""Use an isolated database before importing the application singleton."""
import pytest


@pytest.fixture(scope="session")
def runtime(tmp_path_factory):
    directory = tmp_path_factory.mktemp("fulltext")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("NOVEL_DATABASE_URL", f"sqlite:///{directory / 'test.db'}")
        patch.setenv("NOVEL_DATA_DIR", str(directory / "data"))
        patch.setenv("NOVEL_MODE", "demo")
        from app.main import app
        yield app


@pytest.fixture
def client(runtime):
    from fastapi.testclient import TestClient
    with TestClient(runtime) as active:
        yield active
