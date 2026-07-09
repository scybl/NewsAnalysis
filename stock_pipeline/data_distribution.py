from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Callable, Iterable


class DataDistributionError(RuntimeError):
    """Raised when a data distribution email cannot be prepared or sent."""


@dataclass(frozen=True)
class EmailDistributionConfig:
    host: str
    port: int
    username: str
    password: str
    sender: str
    recipients: tuple[str, ...]
    use_ssl: bool = True
    timeout_seconds: int = 20


def send_email_distribution(
    subject: str,
    body: str,
    config: EmailDistributionConfig,
    attachment_paths: Iterable[str | Path] = (),
    smtp_factory: Callable[..., object] | None = None,
) -> dict:
    """Send a simple report email with optional local file attachments."""
    _validate_config(config)
    attachments = [_resolve_attachment(path) for path in attachment_paths]
    message = _build_message(subject, body, config, attachments)
    smtp_factory = smtp_factory or _default_smtp_factory(config.use_ssl)

    smtp = smtp_factory(config.host, config.port, timeout=config.timeout_seconds)
    try:
        smtp.login(config.username, config.password)
        smtp.sendmail(config.sender, list(config.recipients), message.as_string())
    finally:
        quit_method = getattr(smtp, "quit", None)
        if callable(quit_method):
            quit_method()

    return {
        "ok": True,
        "recipients": list(config.recipients),
        "attachments": [path.name for path in attachments],
    }


def _validate_config(config: EmailDistributionConfig) -> None:
    if not config.host.strip():
        raise DataDistributionError("SMTP host is required.")
    if config.port <= 0:
        raise DataDistributionError("SMTP port must be positive.")
    if not config.username.strip() or not config.password:
        raise DataDistributionError("SMTP username and password are required.")
    if not config.sender.strip():
        raise DataDistributionError("Sender email is required.")
    if not config.recipients:
        raise DataDistributionError("At least one recipient is required.")


def _resolve_attachment(path: str | Path) -> Path:
    attachment = Path(path).expanduser().resolve()
    if not attachment.is_file():
        raise DataDistributionError(f"Attachment not found: {attachment}")
    return attachment


def _build_message(
    subject: str,
    body: str,
    config: EmailDistributionConfig,
    attachments: list[Path],
) -> MIMEMultipart:
    message = MIMEMultipart()
    message["From"] = config.sender
    message["To"] = ", ".join(config.recipients)
    message["Subject"] = Header(subject or "ValueScope DataHub 数据分发", "utf-8")
    message.attach(MIMEText(body or "数据分发任务已完成。", "plain", "utf-8"))

    for path in attachments:
        part = MIMEApplication(path.read_bytes(), Name=path.name)
        part.add_header("Content-Disposition", "attachment", filename=path.name)
        message.attach(part)
    return message


def _default_smtp_factory(use_ssl: bool) -> Callable[..., object]:
    return smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
