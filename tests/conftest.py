import pytest


@pytest.fixture(scope="session", autouse=True)
def isolated_test_runtime(tmp_path_factory):
    root = tmp_path_factory.mktemp("novel-runtime")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("NOVEL_MODE", "demo")
        patch.setenv("NOVEL_DATABASE_URL", f"sqlite:///{root / 'tests.db'}")
        patch.setenv("NOVEL_DATA_DIR", str(root / "data"))
        yield
