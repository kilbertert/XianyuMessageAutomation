from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(name: str) -> str:
    return (ROOT / "scripts" / name).read_text(encoding="utf-8")


def test_service_secret_is_not_put_on_task_command_line() -> None:
    source = _source("install_gateway_service.ps1")

    assert "ConvertFrom-SecureString" in source
    assert "gateway-secret.dpapi" in source
    assert "ANDROID_GATEWAY_SHARED_SECRET" not in source
    assert "$SharedSecret" not in source.split("$taskArguments =", 1)[1]


def test_service_runs_in_interactive_user_session_and_restarts() -> None:
    source = _source("install_gateway_service.ps1")

    assert "New-ScheduledTaskTrigger -AtLogOn" in source
    assert "-LogonType Interactive" in source
    assert "-RestartCount 999" in source
    assert "-AllowStartIfOnBatteries" in source
    assert "-DontStopIfGoingOnBatteries" in source
    assert "$inheritanceFlags" in source


def test_supervisor_uses_dpapi_secret_and_gateway_command() -> None:
    source = _source("gateway_service.ps1")

    assert "ConvertTo-SecureString" in source
    assert "ZeroFreeBSTR" in source
    assert "gateway --interval 0.5" in source
    assert "while ($true)" in source


def test_uninstaller_deletes_only_the_exact_secret_path() -> None:
    source = _source("uninstall_gateway_service.ps1")

    assert "[IO.File]::Delete($secretPath)" in source
    assert "Remove-Item" not in source
