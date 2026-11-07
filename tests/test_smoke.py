def test_pytest_runs():
    import fastapi, pydantic, nacl, rfc8785, pdfplumber, pymupdf  # noqa: F401

    assert pydantic.VERSION.startswith("2.")
