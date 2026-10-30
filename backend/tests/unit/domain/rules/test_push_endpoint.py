"""The shape a Web Push endpoint must have before the server will ever post to it (R11, I14).

The endpoint is a URL the client chose, and the server posts the push to it, so a bad one would turn
the server into a way to reach an inside address. The rule is structural (no network lookup): https,
no credentials, a real DNS name, the default port.
"""

import pytest

from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.push_endpoint import MAX_ENDPOINT_LENGTH, check_push_endpoint

GOOD = [
    "https://fcm.googleapis.com/fcm/send/sample-token",
    "https://updates.push.services.mozilla.com/wpush/v2/sample",
    "https://web.push.apple.com/sample",
    "https://push.example/sample-endpoint",
    "https://wns2-par02p.notify.windows.com:443/w/?token=sample",
    "HTTPS://Push.Example/Sample",
]

BAD = [
    "http://push.example/sample",
    "ftp://push.example/sample",
    "https://user:secret@push.example/sample",
    "https://localhost/sample",
    "https://127.0.0.1/sample",
    "https://[::1]/sample",
    "https://169.254.169.254/latest/meta-data",
    "https://10.0.0.5/sample",
    "https://0x7f.0.0.1/sample",
    "https://2130706433/sample",
    "https://intranet/sample",
    "https://service.internal/sample",
    "https://printer.local/sample",
    "https://push.example:8443/sample",
    "https://push.example:22/sample",
    "https:///sample",
    "https://push..example/sample",
    "https://-bad.example/sample",
    "https://push.example/sample#fragment",
    "//push.example/sample",
    "push.example/sample",
    "",
    "   ",
    "https://push.example/ sample",
    "https://push.example/\nsample",
]


@pytest.mark.parametrize("endpoint", GOOD)
def test_a_real_push_service_endpoint_passes(endpoint: str) -> None:
    assert check_push_endpoint(endpoint) == endpoint


@pytest.mark.parametrize("endpoint", BAD)
def test_an_endpoint_that_could_reach_an_inside_address_is_refused(endpoint: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        check_push_endpoint(endpoint)
    assert refused.value.field == "subscription"
    assert endpoint.strip() == "" or endpoint.strip() not in refused.value.message


@pytest.mark.parametrize("value", [None, 5, b"https://push.example/x", ["https://push.example/x"]])
def test_a_value_that_is_not_text_is_refused(value: object) -> None:
    with pytest.raises(ValidationFailed):
        check_push_endpoint(value)


def test_an_endpoint_over_the_length_limit_is_refused() -> None:
    long = "https://push.example/" + "a" * MAX_ENDPOINT_LENGTH
    with pytest.raises(ValidationFailed):
        check_push_endpoint(long)
    assert check_push_endpoint(long[:MAX_ENDPOINT_LENGTH]) == long[:MAX_ENDPOINT_LENGTH]
