import os
from pathlib import Path
from unittest.mock import patch

import pytest

from migrate.config import ConfigError, MigrationConfig, _validate


class TestValidation:
    def test_rejects_blank(self) -> None:
        with pytest.raises(ConfigError, match="blank"):
            _validate("", "test_field")

    def test_rejects_whitespace_only(self) -> None:
        with pytest.raises(ConfigError, match="blank"):
            _validate("   ", "test_field")

    def test_rejects_placeholder_replace_me(self) -> None:
        with pytest.raises(ConfigError, match="replace-me"):
            _validate("replace-me", "test_field")

    def test_rejects_placeholder_invalid(self) -> None:
        with pytest.raises(ConfigError, match="placeholder.invalid"):
            _validate("user@placeholder.invalid", "test_field")

    def test_rejects_account_placeholder(self) -> None:
        with pytest.raises(ConfigError, match="account-placeholder"):
            _validate("account-placeholder", "test_field")

    def test_accepts_real_value(self) -> None:
        assert _validate("real-account-id-123", "test") == "real-account-id-123"

    def test_strips_whitespace(self) -> None:
        assert _validate("  value  ", "test") == "value"


class TestMigrationConfigLoad:
    def test_fails_on_missing_file(self) -> None:
        with pytest.raises(ConfigError, match="not found"):
            MigrationConfig.load("/nonexistent/path.yaml")

    def test_fails_on_empty_processes(self, tmp_path: Path) -> None:
        config_file = tmp_path / "migration.yaml"
        config_file.write_text("""
boomi:
  account_id_env: BOOMI_ACCOUNT_ID
  username_env: BOOMI_USERNAME
  api_token_env: BOOMI_API_TOKEN
solace_semp:
  base_url_env: SOLACE_SEMP_BASE_URL
  message_vpn_env: SOLACE_MESSAGE_VPN
  username_env: SOLACE_SEMP_USERNAME
  password_env: SOLACE_SEMP_PASSWORD
connector_profile:
  sub_type: test
  connection_fields: {host: h, vpn: v, username: u, password: p}
  operation_fields: {destination: d, destination_type: dt, delivery_mode: dm}
connection:
  host_env: SOLACE_HOST
  vpn_env: SOLACE_VPN
  username_env: SOLACE_USER
  password_env: SOLACE_PASS
target_folder_id: "folder-guid"
processes: []
""")
        env = {
            "BOOMI_ACCOUNT_ID": "acc", "BOOMI_USERNAME": "user", "BOOMI_API_TOKEN": "token",
            "SOLACE_SEMP_BASE_URL": "https://broker:943", "SOLACE_MESSAGE_VPN": "vpn",
            "SOLACE_SEMP_USERNAME": "admin", "SOLACE_SEMP_PASSWORD": "pass",
            "SOLACE_HOST": "tcp://h:55555", "SOLACE_VPN": "vpn",
            "SOLACE_USER": "user", "SOLACE_PASS": "pass",
        }
        with patch.dict(os.environ, env):
            with pytest.raises(ConfigError, match="(?i)at least one process"):
                MigrationConfig.load(config_file)

    def test_fails_on_missing_env_var(self, tmp_path: Path) -> None:
        config_file = tmp_path / "migration.yaml"
        config_file.write_text("""
boomi:
  account_id_env: MISSING_VAR
  username_env: BOOMI_USERNAME
  api_token_env: BOOMI_API_TOKEN
solace_semp:
  base_url_env: X
  message_vpn_env: X
  username_env: X
  password_env: X
connector_profile:
  sub_type: test
  connection_fields: {host: h, vpn: v, username: u, password: p}
  operation_fields: {destination: d, destination_type: dt, delivery_mode: dm}
connection:
  host_env: X
  vpn_env: X
  username_env: X
  password_env: X
target_folder_id: "f"
processes:
  - id: p1
    name: Test
    send_destination: topic/v1
""")
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigError, match="not set"):
                MigrationConfig.load(config_file)
