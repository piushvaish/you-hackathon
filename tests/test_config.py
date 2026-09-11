from pathlib import Path

import pytest

from kojable_agent.config import ConfigurationError, Settings


def test_missing_ydc_api_key_is_actionable(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="YDC_API_KEY"):
        Settings.load(tmp_path, {"DAYTONA_API_KEY": "daytona"})


def test_missing_daytona_api_key_is_actionable(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="DAYTONA_API_KEY"):
        Settings.load(tmp_path, {"YDC_API_KEY": "you"})


def test_root_dotenv_loads_and_environment_wins(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "YDC_API_KEY=from-file\nDAYTONA_API_KEY=from-file\nONE_SECRET=one-from-file\n",
        encoding="utf-8",
    )
    settings = Settings.load(tmp_path, {"YDC_API_KEY": "from-env"})
    assert settings.ydc_api_key == "from-env"
    assert settings.daytona_api_key == "from-file"
    assert settings.one_secret == "one-from-file"
