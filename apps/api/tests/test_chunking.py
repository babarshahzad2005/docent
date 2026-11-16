from docent_api.chunking import MAX_CHARS, Chunk, chunk_markdown, chunk_plain_text


def contents(chunks: list[Chunk]) -> list[str]:
    return [c.content for c in chunks]


def test_chunks_carry_the_headings_above_them() -> None:
    text = (
        "# Leave policy\n\nIntro.\n\n## Carry-over\n\nUp to 10 days.\n\n"
        "## Requests\n\nTwo weeks ahead.\n\n# Pay\n\nMonthly."
    )

    chunks = chunk_markdown(text)

    assert [(c.heading_path, c.content) for c in chunks] == [
        (("Leave policy",), "Intro."),
        (("Leave policy", "Carry-over"), "Up to 10 days."),
        (("Leave policy", "Requests"), "Two weeks ahead."),
        (("Pay",), "Monthly."),
    ]
    assert [c.ordinal for c in chunks] == [0, 1, 2, 3]


def test_headings_include_the_path_when_embedded() -> None:
    chunk = chunk_markdown("# Leave\n## Carry-over\nUp to 10 days.")[0]

    assert chunk.text_for_embedding == "Leave > Carry-over\n\nUp to 10 days."


def test_small_paragraphs_in_a_section_are_packed_together() -> None:
    chunks = chunk_markdown("# A\n\none\n\ntwo\n\nthree")

    assert contents(chunks) == ["one\n\ntwo\n\nthree"]


def test_chunks_never_cross_a_heading() -> None:
    chunks = chunk_markdown("# A\n\none\n\n# B\n\ntwo")

    assert contents(chunks) == ["one", "two"]


def test_long_sections_are_split_near_the_target_size() -> None:
    paragraph = "word " * 120  # about 600 characters
    chunks = chunk_plain_text("\n\n".join([paragraph.strip()] * 10))

    assert len(chunks) > 1
    assert all(len(c.content) <= MAX_CHARS for c in chunks)
    assert "".join(c.content.replace("\n\n", " ") for c in chunks).count("word") == 1200


def test_a_huge_paragraph_is_split_at_sentences_then_words() -> None:
    sentences = " ".join(f"Sentence {n} says something useful about leave." for n in range(200))
    unbroken = "x" * (MAX_CHARS * 2 + 10)

    chunks = chunk_plain_text(sentences + "\n\n" + unbroken)

    assert all(len(c.content) <= MAX_CHARS for c in chunks)
    assert chunks[0].content.startswith("Sentence 0 says")
    assert chunks[0].content.endswith(".")
    assert sum(c.content.count("x") for c in chunks[-3:]) == len(unbroken)


def test_headings_inside_code_blocks_are_text() -> None:
    chunks = chunk_markdown("# Setup\n\n```bash\n# install it\npip install x\n```")

    assert [c.heading_path for c in chunks] == [("Setup",)]
    assert "# install it" in chunks[0].content


def test_front_matter_and_closing_hashes_are_dropped() -> None:
    chunks = chunk_markdown("---\ntitle: Leave\n---\n## Carry-over ##\n\nUp to 10 days.")

    assert [(c.heading_path, c.content) for c in chunks] == [(("Carry-over",), "Up to 10 days.")]


def test_text_without_headings_has_an_empty_path() -> None:
    chunks = chunk_plain_text("First paragraph.\r\n\r\nSecond paragraph.")

    assert [(c.heading_path, c.content) for c in chunks] == [
        ((), "First paragraph.\n\nSecond paragraph.")
    ]


def test_empty_documents_have_no_chunks() -> None:
    assert chunk_plain_text("") == []
    assert chunk_markdown("# Only a heading\n\n   \n") == []


def test_identical_passages_hash_the_same_and_headings_change_the_hash() -> None:
    a, b, c = chunk_markdown("# A\n\nSame.\n\n# A\n\nSame.\n\n# B\n\nSame.")

    assert a.content_hash == b.content_hash
    assert a.content_hash != c.content_hash
