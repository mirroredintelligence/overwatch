"""Writes frontend/test/fixtures/backend-shapes.ts: the JSON the back end answers for the advisor
call flow and the bookings, produced by the back end's own mapping functions (W8A). Sample values
only. Run from backend/:

    uv run python ../frontend/test/fixtures/backend-shapes.gen.py > ../frontend/test/fixtures/backend-shapes.ts

Re-run it when a mapping changes, so a front-end test never holds a shape the back end does not send.
"""

import json
from datetime import UTC, date, datetime, timedelta

from diucs.adapters.fhir_shared.booking_task import booking_to_fhir
from diucs.adapters.inbound.fhir_rest.case_mapping import case_to_fhir, filter_result_to_fhir
from diucs.adapters.inbound.fhir_rest.routes_criteria import _view_basic
from diucs.adapters.inbound.link_pages.booking_links import change_view_body, view_body
from diucs.application.ports.outbound.geo import LatLon, TravelRange
from diucs.application.use_cases.criteria import CriteriaVersionView
from diucs.application.use_cases.filter_options import (
    FilterOptionsResult,
    NotSuitable,
    Option,
)
from diucs.domain.codes import (
    AgeBand,
    BestFitNotUsedReason,
    BookingStatus,
    CriteriaStatus,
    NeedCategory,
    Outcome,
    ReferrerType,
    ServiceCategory,
    Status,
    Urgency,
)
from diucs.domain.model.booking import Booking
from diucs.domain.model.case import Case
from diucs.domain.model.scores import News2

T0 = datetime(2026, 10, 30, 14, 0, tzinfo=UTC)

case = Case(
    id="case-1",
    reference="4821",
    referrer_type=ReferrerType.AMBULANCE_CREW,
    age_band=AgeBand.A80_PLUS,
    postcode="DT4",
    needs=(NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY),
    urgency=Urgency.WITHIN_2_HRS,
    scores=(News2(2),),
    opened_at=T0,
)
blank = Case(
    id="case-1", reference="4821", referrer_type=None, age_band=None, postcode=None,
    needs=(), urgency=None, scores=(), opened_at=T0,
)
closed = case.close(Outcome.ACCEPTED_AND_BOOKED, T0 + timedelta(minutes=9), "svc-1", BestFitNotUsedReason.FULL)

options = FilterOptionsResult(
    options=(
        Option(
            service_id="svc-1", name="UCR West", status=Status.ACCEPTING, effective_available=3,
            over_by=None, unit_label="referrals in the next 2 hrs", data_age=timedelta(minutes=9),
            travel=TravelRange(15, 25, "road estimate"), fits=("Falls without injury", "Frailty"),
            warnings=("Limited: phone to confirm",), criteria_id="cr-1", criteria_version=3,
            category=ServiceCategory.URGENT_COMMUNITY_RESPONSE, position=LatLon(50.71, -2.45),
        ),
        Option(
            service_id="svc-2", name="Weymouth Beds", status=Status.OVER_CAPACITY, effective_available=None,
            over_by=1, unit_label="beds", data_age=None, travel=None, fits=(), warnings=(),
            criteria_id="cr-2", criteria_version=1, category=None, position=None,
        ),
    ),
    not_suitable=(NotSuitable("svc-3", "Dorchester SDEC", "Not accepting"),),
    generated_at=T0,
    patient=LatLon(50.71, -2.44),
    not_found=False,
    out_of_area=False,
)
no_postcode = FilterOptionsResult(
    options=(), not_suitable=(), generated_at=T0, patient=None, not_found=True, out_of_area=True,
)


def booking(*path: BookingStatus, reason: str | None = None) -> dict:
    b = Booking(
        id="bk-1", reference="4821", service_id="svc-1", case_id="case-1", requester_id="adv-1",
        status=BookingStatus.REQUESTED, requested_at=T0, reply_by=T0 + timedelta(minutes=10),
    )
    for step, target in enumerate(path):
        last = step == len(path) - 1
        b = b.with_status(target, T0 + timedelta(minutes=3 + step), reason if last else None)
    return booking_to_fhir(b)


criteria = CriteriaVersionView(
    criteria_id="cr-1", version=3, status=CriteriaStatus.CURRENT, review_by=date(2026, 12, 12),
    author_role_id="role-1", age_min=18, age_max=None,
    accepts=frozenset({NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY}),
    excludes=frozenset({NeedCategory.SUSPECTED_FRACTURE}),
)

bookings = {
    "requested": booking(),
    "confirmed": booking(BookingStatus.CONFIRMED),
    "declined": booking(BookingStatus.DECLINED, reason="full"),
    "expired": booking(BookingStatus.EXPIRED),
    "cancelledBefore": booking(BookingStatus.CANCELLED_BEFORE),
    "cancelledAfter": booking(BookingStatus.CONFIRMED, BookingStatus.CANCELLED_AFTER),
    "withdrawn": booking(BookingStatus.CONFIRMED, BookingStatus.WITHDRAWN, reason="now-full"),
    "notReached": booking(BookingStatus.CONFIRMED, BookingStatus.NOT_REACHED, reason="no-answer"),
}
requested_b = Booking(
    id="bk-1", reference="4821", service_id="svc-1", case_id="case-1", requester_id="adv-1",
    status=BookingStatus.REQUESTED, requested_at=T0, reply_by=T0 + timedelta(minutes=10),
)
confirmed_b = requested_b.with_status(BookingStatus.CONFIRMED, T0 + timedelta(minutes=3))

shapes = {
    "caseFull": case_to_fhir(case),
    "caseBlank": case_to_fhir(blank),
    "caseClosed": case_to_fhir(closed),
    "options": filter_result_to_fhir(options),
    "optionsNoPostcode": filter_result_to_fhir(no_postcode),
    "criteriaHistory": {
        "resourceType": "Bundle", "type": "searchset", "total": 1,
        "entry": [{"resource": _view_basic(criteria, "svc-1")}],
    },
    "bookings": bookings,
    "linkRequestView": {
        "state": "ok", "purpose": "booking-request",
        **view_body(requested_b, "UCR West", case, "0300 123 4567"), "csrfToken": "csrf-sample",
    },
    "linkChangeView": {
        "state": "ok", "purpose": "booking-change",
        **change_view_body(confirmed_b, "UCR West", case, "0300 123 4567"), "csrfToken": "csrf-sample",
    },
}

print("// GENERATED by backend-shapes.gen.py from the back end's own mapping functions (W8A). Do not edit.")
print("// Sample values only: no patient data.")
for name, value in shapes.items():
    const = "".join("_" + c if c.isupper() else c.upper() for c in name).lstrip("_")
    print(f"export const {const} = {json.dumps(value, indent=2)};\n")
