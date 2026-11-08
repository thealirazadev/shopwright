from app.ingest.chunking import html_to_text, split_text


def test_html_is_reduced_to_readable_text() -> None:
    html = (
        "<h2>Care</h2><p>Machine   wash cold.</p>"
        "<script>alert(1)</script><ul><li>No bleach</li></ul>"
    )

    assert html_to_text(html) == "Care\n\nMachine wash cold.\n\nNo bleach"


def test_paragraphs_are_packed_without_exceeding_the_limit() -> None:
    text = "\n\n".join(["alpha " * 30, "beta " * 30, "gamma " * 30])

    chunks = split_text(text, max_chars=200)

    assert all(0 < len(chunk) <= 200 for chunk in chunks)
    assert " ".join(chunks).split() == text.split()


def test_a_long_paragraph_is_split_on_spaces() -> None:
    chunks = split_text("word " * 100, max_chars=60)

    assert all(len(chunk) <= 60 for chunk in chunks)
    assert all(not chunk.endswith("wor") for chunk in chunks)
