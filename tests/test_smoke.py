def test_python_version() -> None:
    import sys

    assert sys.version_info >= (3, 11)
