"""A `Sender` for tests: records every email and answers with a chosen `SendResult`, or
raises `raises` when set."""

from dataclasses import dataclass, field

from app.emails.sender import SendResult


@dataclass(frozen=True)
class SentEmail:
    to: str
    subject: str
    text: str
    html: str
    reply_to: str | None


@dataclass
class FakeSender:
    result: SendResult = field(default_factory=lambda: SendResult("sent", id="fake"))
    raises: Exception | None = None
    outbox: list[SentEmail] = field(default_factory=list)

    def send(
        self, to: str, subject: str, text: str, html: str, reply_to: str | None = None
    ) -> SendResult:
        self.outbox.append(SentEmail(to, subject, text, html, reply_to))
        if self.raises is not None:
            raise self.raises
        return self.result
