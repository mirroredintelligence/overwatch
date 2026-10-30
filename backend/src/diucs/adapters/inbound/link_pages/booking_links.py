"""Booking links (L02): the request link a service opens, and the change link it gets on confirm.

Stub (red): the pure rules below are not yet implemented.
"""

from datetime import timedelta
from typing import Any, Final

from diucs.application.use_cases.link_access import LinkAction
from diucs.domain.codes import BookingStatus, DeclineReason, NotReachedReason, WithdrawReason
from diucs.domain.model.booking import Booking
from diucs.domain.model.case import Case

REQUEST_PURPOSE: Final = "booking-request"
CHANGE_PURPOSE: Final = "booking-change"
CHANGE_TOKEN_LIFETIME: Final = timedelta(hours=24)  # [ASSUMED] L02 prompt


def check_request_action(action: LinkAction) -> DeclineReason | None:
    raise NotImplementedError


def check_change_action(action: LinkAction) -> WithdrawReason | NotReachedReason:
    raise NotImplementedError


def gone_state(status: BookingStatus) -> str:
    raise NotImplementedError


def view_body(booking: Booking, service_name: str, case: Case) -> dict[str, Any]:
    raise NotImplementedError
