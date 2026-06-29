from pathlib import Path

import pytest

from stock_pipeline.data_distribution import (
    DataDistributionError,
    EmailDistributionConfig,
    send_email_distribution,
)


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.login_args = None
        self.sent = None
        self.quit_called = False
        FakeSMTP.instances.append(self)

    def login(self, username, password):
        self.login_args = (username, password)

    def sendmail(self, sender, recipients, message):
        self.sent = (sender, recipients, message)

    def quit(self):
        self.quit_called = True


def test_send_email_distribution_sends_attachment(tmp_path):
    FakeSMTP.instances.clear()
    report = tmp_path / "daily.csv"
    report.write_text("code,value\n000001,1\n", encoding="utf-8")
    config = EmailDistributionConfig(
        host="smtp.qq.com",
        port=465,
        username="sender@qq.com",
        password="smtp-secret",
        sender="sender@qq.com",
        recipients=("owner@qq.com",),
    )

    result = send_email_distribution(
        "日报",
        "任务完成",
        config,
        attachment_paths=[report],
        smtp_factory=FakeSMTP,
    )

    smtp = FakeSMTP.instances[0]
    assert result == {"ok": True, "recipients": ["owner@qq.com"], "attachments": ["daily.csv"]}
    assert smtp.host == "smtp.qq.com"
    assert smtp.port == 465
    assert smtp.login_args == ("sender@qq.com", "smtp-secret")
    assert smtp.sent[0] == "sender@qq.com"
    assert smtp.sent[1] == ["owner@qq.com"]
    assert "daily.csv" in smtp.sent[2]
    assert "Content-Disposition: attachment" in smtp.sent[2]
    assert smtp.quit_called is True


def test_send_email_distribution_rejects_missing_attachment(tmp_path):
    config = EmailDistributionConfig(
        host="smtp.qq.com",
        port=465,
        username="sender@qq.com",
        password="smtp-secret",
        sender="sender@qq.com",
        recipients=("owner@qq.com",),
    )

    with pytest.raises(DataDistributionError, match="Attachment not found"):
        send_email_distribution("日报", "任务完成", config, attachment_paths=[Path(tmp_path / "missing.csv")])
