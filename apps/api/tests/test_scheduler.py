from docent_api.scheduler import hash_token, job_command


def test_the_job_calls_the_api_only_when_work_is_waiting() -> None:
    command = job_command("https://api.example.test/")

    assert "url := 'https://api.example.test/ingestion/scheduled'" in command
    assert "where exists" in command
    assert "status in ('queued', 'parsing', 'embedding')" in command
    assert "vault.decrypted_secrets" in command
    assert "app.storage_deletions" in command  # files of deleted Documents count as work


def test_the_api_url_cant_break_out_of_the_job_sql() -> None:
    assert "https://x.test/a''b/ingestion/scheduled" in job_command("https://x.test/a'b")


def test_tokens_are_stored_as_hashes() -> None:
    assert hash_token("secret") != "secret"
    assert hash_token("secret") == hash_token("secret")
