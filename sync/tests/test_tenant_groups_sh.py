"""infra/tenant-groups.sh ensure-user: SUPPRESS -> set password -> SES email, via a stubbed `aws`."""
import os
import stat
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "infra" / "tenant-groups.sh"

STUB = """#!/usr/bin/env bash
echo "$*" >> "$AWS_LOG"
case "$*" in
  *admin-get-user*) echo "An error occurred (UserNotFoundException)" >&2; exit 254 ;;
esac
"""


def run(tmp_path, *args):
    stub = tmp_path / "aws"
    stub.write_text(STUB)
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.log"
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "AWS_LOG": str(log),
           "USER_POOL_ID": "pool-1", "SITE_DOMAIN": "example.test", "COGNITO_CLIENT_ID": "cid123"}
    out = subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True)
    calls = log.read_text().splitlines() if log.exists() else []
    return out, calls


def test_ensure_user_suppresses_sets_password_then_emails(tmp_path):
    out, calls = run(tmp_path, "ensure-user", "new@example.com")
    assert out.returncode == 0, out.stderr
    assert out.stdout.startswith("invited new@example.com")
    steps = [c.split()[1] for c in calls]
    assert steps == ["admin-get-user", "admin-create-user", "admin-set-user-password", "send-email"]
    assert "--message-action SUPPRESS" in calls[1]
    assert "--permanent" in calls[2]
    password = calls[2].split("--password ")[1].split(" ")[0]
    assert password not in out.stdout and password not in out.stderr
    assert "--from-email-address noreply@example.test" in calls[3]
    assert "login_hint=new@example.com" in calls[3]
    assert "client_id=cid123" in calls[3]


def test_reinvite_only_sends_email(tmp_path):
    out, calls = run(tmp_path, "reinvite", "a@example.com")
    assert out.returncode == 0, out.stderr
    assert [c.split()[1] for c in calls] == ["send-email"]
