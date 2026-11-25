from pathlib import Path

def test_example_env_has_no_real_payment_secret():
    text=Path(".env.example").read_text()
    assert "FLW_SECRET_KEY=\n" in text
