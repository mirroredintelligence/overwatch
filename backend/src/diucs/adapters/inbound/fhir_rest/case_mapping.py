"""The ServiceRequest of an advisor case, both ways (R07, DEC-397, W7A).

Pure: no store, no clock. `parse_case_details` reads what a body says about a case (a part it leaves
out is None, which means unchanged); `case_to_fhir` writes the case as a ServiceRequest.

Shapes the front end reads and writes (docs/delivery/fragments/W7A-routes.md):

- the age band is an extension on the contained Patient stub, the referrer type an extension on the
  request;
- the urgency is the extension `urgency` (within-2-hrs, today or planned). The FHIR `priority`
  carries urgent for within-2-hrs and routine for today and planned, because FHIR has no planned
  priority. A body with a priority and no urgency extension reads as before (urgent is within
  2 hrs, routine is today). A priority that disagrees with the extension is refused (DEC-773);
- a referrer's score is one complex extension, `score`, with a `method` and a `value`;
- the answer carries the case reference as the identifier, the open time as authoredOn, and, once
  closed, the close time and the outcome as extensions.

A refusal names the part and never echoes its value: a score and an age band are clinical data.
"""

from dataclasses import dataclass
from typing import Any, Final

from diucs.application.idempotency import format_instant
from diucs.application.use_cases.filter_options import FilterOptionsResult, Option
from diucs.domain.codes import (
    BASE_URL,
    AcuityMethod,
    AgeBand,
    NeedCategory,
    ReferrerType,
    Urgency,
    code_system_url,
)
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.case import Case, priority_for
from diucs.domain.model.scores import (
    AmbulanceCategory,
    ClinicalFrailty,
    ManchesterTriage,
    News2,
    PathwaysDx,
    Score,
    ScoreCorrectionReason,
    method_of,
)

STRUCTURE: Final = f"{BASE_URL}StructureDefinition/"
AGE_BAND_EXTENSION: Final = f"{STRUCTURE}age-band"
REFERRER_EXTENSION: Final = f"{STRUCTURE}referrer-type"
URGENCY_EXTENSION: Final = f"{STRUCTURE}urgency"
SCORE_EXTENSION: Final = f"{STRUCTURE}score"
SCORE_REASON_EXTENSION: Final = f"{STRUCTURE}score-correction-reason"
"""Why a recorded score is changed, on the request of a PUT (Q7, DEC-1171): one of the codes of
`ScoreCorrectionReason`. Sent with the scores it corrects, and refused when nothing is corrected."""
SCORE_CORRECTIONS_EXTENSION: Final = f"{STRUCTURE}score-corrections"
"""How many times a recorded score was corrected (valueInteger), on the answer, only when above
zero. The screen says "corrected" from it; the original score and the reason are in the audit."""
CLOSED_AT_EXTENSION: Final = f"{STRUCTURE}closed-at"
OUTCOME_EXTENSION: Final = f"{STRUCTURE}outcome"
DISTRICT_EXTENSION: Final = f"{STRUCTURE}postcode-district"
"""A postcode district chosen on its own, on the contained Patient (W50, W9H DEC-1045): the
advisor's pick from the chips offered when the postcode was not found or is out of area."""
REFERENCE_SYSTEM: Final = f"{BASE_URL}case-reference"
REFUSED_PATIENT_ELEMENTS: Final = ("name", "identifier", "birthDate", "telecom")
PATIENT_REFUSED: Final = "No patient names or identifiers are stored."
URGENT: Final = "urgent"
ROUTINE: Final = "routine"


@dataclass(frozen=True, slots=True)
class CaseDetails:
    """What a ServiceRequest body says about a case. None is "not said", which leaves the stored
    value as it is."""

    referrer_type: ReferrerType | None
    age_band: AgeBand | None
    postcode: str | None
    needs: tuple[NeedCategory, ...] | None
    urgency: Urgency | None
    scores: tuple[Score, ...] | None
    district: str | None = None
    score_correction_reason: ScoreCorrectionReason | None = None

    @property
    def is_empty(self) -> bool:
        return (
            self.referrer_type is None
            and self.age_band is None
            and self.postcode is None
            and self.needs is None
            and self.urgency is None
            and self.scores is None
            and self.district is None
            and self.score_correction_reason is None
        )


def refuse_patient_details(service_request: dict[str, Any]) -> None:
    """A stub Patient carries an age band and a postcode only (R07)."""
    for contained in service_request.get("contained", []):
        if contained.get("resourceType") != "Patient":
            continue
        for element in REFUSED_PATIENT_ELEMENTS:
            if element in contained:
                raise ValidationFailed(element, PATIENT_REFUSED)


def _patient(service_request: dict[str, Any]) -> dict[str, Any] | None:
    for contained in service_request.get("contained", []):
        if isinstance(contained, dict) and contained.get("resourceType") == "Patient":
            return contained
    return None


def _extension_code(holder: dict[str, Any] | None, url: str, field: str) -> str | None:
    found = [item for item in (holder or {}).get("extension", []) if item.get("url") == url]
    if not found:
        return None
    if len(found) > 1:
        raise ValidationFailed(field, "is given once")
    value = found[0].get("valueCode")
    if not isinstance(value, str) or not value:
        raise ValidationFailed(field, "needs a code")
    return value


def _postcode(service_request: dict[str, Any]) -> str | None:
    patient = _patient(service_request)
    for address in (patient or {}).get("address", []):
        postal = address.get("postalCode")
        if isinstance(postal, str):
            return postal
    return None


def _referrer(service_request: dict[str, Any]) -> ReferrerType | None:
    code = _extension_code(service_request, REFERRER_EXTENSION, "referrer-type")
    if code is None:
        return None
    try:
        return ReferrerType(code)
    except ValueError:
        raise ValidationFailed("referrer-type", "is not a listed referrer type") from None


def _age_band(service_request: dict[str, Any]) -> AgeBand | None:
    code = _extension_code(_patient(service_request), AGE_BAND_EXTENSION, "age-band")
    if code is None:
        return None
    try:
        return AgeBand(code)
    except ValueError:
        raise ValidationFailed("age-band", "is not a listed age band") from None


def _needs(service_request: dict[str, Any]) -> tuple[NeedCategory, ...] | None:
    needs: list[NeedCategory] = []
    system = code_system_url("need-category")
    for concept in service_request.get("reasonCode", []):
        for coding in concept.get("coding", []):
            if coding.get("system") == system:
                try:
                    needs.append(NeedCategory(coding["code"]))
                except KeyError, ValueError:
                    raise ValidationFailed("reasonCode", "is not a listed need") from None
    return tuple(needs) if needs else None


def _urgency(service_request: dict[str, Any]) -> Urgency | None:
    priority = service_request.get("priority")
    if priority not in (None, URGENT, ROUTINE):
        raise ValidationFailed("priority", "must be urgent or routine")
    code = _extension_code(service_request, URGENCY_EXTENSION, "urgency")
    if code is None:
        if priority is None:
            return None
        return Urgency.WITHIN_2_HRS if priority == URGENT else Urgency.TODAY
    try:
        urgency = Urgency(code)
    except ValueError:
        raise ValidationFailed("urgency", "is not a listed urgency") from None
    if priority is not None and priority_for(urgency) != priority:
        raise ValidationFailed("urgency", "does not match the priority")
    return urgency


def _score(item: dict[str, Any]) -> Score:
    parts = {part.get("url"): part for part in item.get("extension", []) if isinstance(part, dict)}
    value_part = parts.get("value", {})
    code = parts.get("method", {}).get("valueCode")
    try:
        method = AcuityMethod(code) if isinstance(code, str) else None
    except ValueError:
        method = None
    integer = value_part.get("valueInteger")
    text = value_part.get("valueString")
    if method is None:
        raise ValidationFailed("scores", "a score has a listed method")
    if isinstance(integer, int) and not isinstance(integer, bool):
        match method:
            case AcuityMethod.NEWS2:
                return News2(integer)
            case AcuityMethod.CFS:
                return ClinicalFrailty(integer)
            case AcuityMethod.AMBULANCE_CATEGORY:
                return AmbulanceCategory(integer)
    if isinstance(text, str):
        match method:
            case AcuityMethod.MANCHESTER:
                return ManchesterTriage(text)
            case AcuityMethod.PATHWAYS_DX:
                return PathwaysDx(text)
    raise ValidationFailed("scores", "a score has a value of the kind its method takes")


def _scores(service_request: dict[str, Any]) -> tuple[Score, ...] | None:
    items = [
        item for item in service_request.get("extension", []) if item.get("url") == SCORE_EXTENSION
    ]
    if not items:
        return None
    scores = tuple(_score(item) for item in items)
    if len({method_of(score) for score in scores}) != len(scores):
        raise ValidationFailed("scores", "at most one score per method")
    return scores


def _correction_reason(service_request: dict[str, Any]) -> ScoreCorrectionReason | None:
    code = _extension_code(service_request, SCORE_REASON_EXTENSION, "score-correction-reason")
    if code is None:
        return None
    try:
        return ScoreCorrectionReason(code)
    except ValueError:
        raise ValidationFailed(
            "score-correction-reason", "is not a listed reason for a correction"
        ) from None


def parse_case_details(service_request: dict[str, Any]) -> CaseDetails:
    return CaseDetails(
        referrer_type=_referrer(service_request),
        age_band=_age_band(service_request),
        postcode=_postcode(service_request),
        needs=_needs(service_request),
        urgency=_urgency(service_request),
        scores=_scores(service_request),
        district=_extension_code(_patient(service_request), DISTRICT_EXTENSION, "district"),
        score_correction_reason=_correction_reason(service_request),
    )


def _score_extension(score: Score) -> dict[str, Any]:
    value: dict[str, Any]
    match score:
        case News2() | ClinicalFrailty() | AmbulanceCategory():
            value = {"url": "value", "valueInteger": score.value}
        case ManchesterTriage():
            value = {"url": "value", "valueString": score.level}
        case PathwaysDx():
            value = {"url": "value", "valueString": score.code}
    return {
        "url": SCORE_EXTENSION,
        "extension": [{"url": "method", "valueCode": method_of(score).value}, value],
    }


def case_to_fhir(case: Case) -> dict[str, Any]:
    """The ServiceRequest of a case. Open: the district, age band, needs and scores are shown.
    Closed: the stored case holds no district or needs, so none are shown (DEC-398); the close time
    and the outcome are."""
    patient: dict[str, Any] = {"resourceType": "Patient", "id": "p"}
    if case.postcode is not None:
        patient["address"] = [{"postalCode": case.postcode}]
    if case.age_band is not None:
        patient["extension"] = [{"url": AGE_BAND_EXTENSION, "valueCode": case.age_band.value}]
    request: dict[str, Any] = {
        "resourceType": "ServiceRequest",
        "id": case.id,
        "identifier": [{"system": REFERENCE_SYSTEM, "value": case.reference}],
        "status": "active" if case.closed_at is None else "completed",
        "intent": "plan",
        "subject": {"reference": "#p"},
        "authoredOn": format_instant(case.opened_at),
        "contained": [patient],
    }
    extensions: list[dict[str, Any]] = []
    if case.referrer_type is not None:
        extensions.append({"url": REFERRER_EXTENSION, "valueCode": case.referrer_type.value})
    if case.urgency is not None:
        request["priority"] = priority_for(case.urgency)
        extensions.append({"url": URGENCY_EXTENSION, "valueCode": case.urgency.value})
    extensions.extend(_score_extension(score) for score in case.scores)
    if case.score_corrections:
        extensions.append(
            {"url": SCORE_CORRECTIONS_EXTENSION, "valueInteger": case.score_corrections}
        )
    if case.closed_at is not None:
        extensions.append(
            {"url": CLOSED_AT_EXTENSION, "valueDateTime": format_instant(case.closed_at)}
        )
    if case.outcome is not None:
        extensions.append({"url": OUTCOME_EXTENSION, "valueCode": case.outcome.value})
    if extensions:
        request["extension"] = extensions
    if case.needs:
        system = code_system_url("need-category")
        request["reasonCode"] = [
            {"coding": [{"system": system, "code": need.value}]} for need in case.needs
        ]
    return request


def _decimal(name: str, value: float) -> dict[str, Any]:
    return {"name": name, "valueDecimal": value}


def _option_part(option: Option) -> dict[str, Any]:
    parts: list[dict[str, Any]] = [
        {"name": "serviceId", "valueString": option.service_id},
        {"name": "name", "valueString": option.name},
        {"name": "status", "valueCode": option.status.value},
        {"name": "criteriaVersion", "valueInteger": option.criteria_version},
        {"name": "unitLabel", "valueString": option.unit_label},
    ]
    if option.category is not None:
        parts.append({"name": "category", "valueCode": option.category.value})
    if option.effective_available is not None:
        parts.append({"name": "effectiveAvailable", "valueInteger": option.effective_available})
    if option.over_by is not None:
        parts.append({"name": "overBy", "valueInteger": option.over_by})
    if option.position is not None:
        parts.append(_decimal("lat", option.position.lat))
        parts.append(_decimal("lon", option.position.lon))
    if option.travel is not None:
        parts.append({"name": "travelLow", "valueInteger": option.travel.low_minutes})
        parts.append({"name": "travelHigh", "valueInteger": option.travel.high_minutes})
        parts.append({"name": "travelSource", "valueString": option.travel.source})
    if option.data_age is not None:
        parts.append(
            {"name": "dataAgeSeconds", "valueInteger": int(option.data_age.total_seconds())}
        )
    parts.extend({"name": "fits", "valueString": fit} for fit in option.fits)
    parts.extend({"name": "checks", "valueString": check} for check in option.warnings)
    return {"name": "option", "part": parts}


def filter_result_to_fhir(result: FilterOptionsResult) -> dict[str, Any]:
    """The `$filter-options` answer as Parameters: the options, then the services that do not fit,
    then the patient's area and the map flags (each flag only when true), then the districts to
    choose from when a flag is true."""
    parameters: list[dict[str, Any]] = [_option_part(option) for option in result.options]
    parameters.extend(
        {
            "name": "notSuitable",
            "part": [
                {"name": "serviceId", "valueString": item.service_id},
                {"name": "name", "valueString": item.name},
                {"name": "reason", "valueString": item.reason},
            ],
        }
        for item in result.not_suitable
    )
    if result.patient is not None:
        parameters.append(_decimal("patientLat", result.patient.lat))
        parameters.append(_decimal("patientLon", result.patient.lon))
    if result.not_found:
        parameters.append({"name": "notFound", "valueBoolean": True})
    if result.out_of_area:
        parameters.append({"name": "outOfArea", "valueBoolean": True})
    # The districts to choose from, in the order to show them (W50): only with a flag, and the
    # services' own configuration, never anything about the case.
    parameters.extend({"name": "district", "valueString": item} for item in result.districts)
    return {"resourceType": "Parameters", "parameter": parameters}
