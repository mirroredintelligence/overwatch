"""Cases on Neo4j: a Patient stub, a ServiceRequest and the referrer's score Observations (P21).

The mapping is pure (case_to_fhir and case_from_fhir). The repository writes through the G05
resource store, with three deliberate departures from the FHIR form, recorded in DEC-066:

- Patient.address is not a mapped element (DEC-053 item 13), so the postcode is a Patient property
  set after the put and read back by a query. Every put replaces the node's properties, so a
  closed case, which has no postcode to set, loses it on save.
- Patient.meta is refused by the store (DEC-053 item 10), so the stub's tag and security label are
  built by case_to_fhir and not stored.
- A ServiceRequest's reference is a copy of its identifier value, set after the put (DEC-063
  item 2 pattern).

Scores are Observations. The store refuses to put an existing Observation (DEC-053 item 3), so an
Observation is written once and never rewritten: with the case on add, or by a later save that
records a score of a method not yet recorded (U11: UpdateCase records the referrer's scores after
OpenCase). A recorded score is corrected (Q7, DEC-1171) by a new revision: every score of the case
is written again as a new Observation named with the revision (`sc-<case>-<n>-r<revision>`), the
request lists the new ones, and the original Observations stay in the graph, unlisted. The number of
corrections is an extension of the request. Any other change to a recorded score is refused.

The version of a case is the version of its ServiceRequest (H-192, DEC-1172): `get_versioned`
returns it and `save` takes the version the caller read, so a write over a newer version is refused
with StaleVersion before anything is written, and the store's own check after its lock refuses a
racing one.
"""

import re
from datetime import UTC, datetime
from typing import Any, Final

from neo4j.exceptions import ClientError

from diucs.adapters.outbound.graph_store.driver import ScopedTx, run_query
from diucs.adapters.outbound.graph_store.extensions import EXTENSIONS, by_short_name
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.outbound.graph_store.service_repository import (
    codeable_from_fhir,
    codeable_to_fhir,
)
from diucs.adapters.outbound.graph_store.service_scenarios import SCENARIOS
from diucs.adapters.outbound.graph_store.week_scenarios import WEEK_SCENARIOS
from diucs.domain.codes import (
    AcuityMethod,
    AgeBand,
    BestFitNotUsedReason,
    NeedCategory,
    Outcome,
    ReferrerType,
    Urgency,
    parse_code,
)
from diucs.domain.errors import (
    Conflict,
    InvalidTransition,
    NotFound,
    StaleVersion,
    ValidationFailed,
)
from diucs.domain.model.case import Case, priority_for
from diucs.domain.model.scores import (
    AmbulanceCategory,
    ClinicalFrailty,
    ManchesterTriage,
    News2,
    PathwaysDx,
    Score,
    method_of,
)
from diucs.domain.rules.postcode import normalise_district

_PATIENT: Final = "Patient"
_REQUEST: Final = "ServiceRequest"
_OBSERVATION: Final = "Observation"
_SERVICE: Final = "HealthcareService"

REFERENCE_SYSTEM: Final = "https://diucs.example/case-reference"
TAG_SYSTEM: Final = "https://diucs.example/CodeSystem/meta-tag"
TAG_CODE: Final = "pseudonymised-case-stub"
SECURITY_SYSTEM: Final = "http://terminology.hl7.org/CodeSystem/v3-Confidentiality"
SECURITY_CODE: Final = "R"
MANCHESTER_SYSTEM: Final = "https://diucs.example/CodeSystem/manchester-triage"
PATHWAYS_SYSTEM: Final = "https://diucs.example/CodeSystem/pathways-dx"
# A case reference is four digits with no leading zero (DEC-041, the format events.py uses).
CASE_REFERENCE: Final = re.compile(r"[1-9][0-9]{3}")
_PATIENT_KEYS: Final = frozenset({"resourceType", "id", "active", "meta", "address", "extension"})
_REQUEST_KEYS: Final = frozenset(
    {
        "resourceType",
        "id",
        "status",
        "intent",
        "authoredOn",
        "identifier",
        "subject",
        "supportingInfo",
        "priority",
        "reasonCode",
        "performer",
        "extension",
        "meta",
    }
)
_SCORE_KEYS: Final = frozenset(
    {"resourceType", "id", "status", "code", "subject", "valueInteger", "valueCodeableConcept"}
)

_PRIORITY: Final = "priority"
_REQUEST_STATUS_ACTIVE: Final = "active"
_REQUEST_STATUS_COMPLETED: Final = "completed"
_INTENT_PLAN: Final = "plan"
_STATUS_FINAL: Final = "final"
_PERFORMER_PREFIX: Final = f"{_SERVICE}/"

_EXT_AGE_BAND: Final = "ageBand"
_EXT_REFERRER_TYPE: Final = "referrerType"
_EXT_URGENCY: Final = "urgency"
_EXT_CLOSED_AT: Final = "closedAt"
_EXT_OUTCOME: Final = "outcome"
_EXT_BEST_FIT: Final = "bestFitNotUsed"
_EXT_SCORE_CORRECTIONS: Final = "scoreCorrections"

_LOOKUP_BY_REFERENCE: Final = NamedQuery(
    id="Q-CASE-BY-REF",
    cypher=(
        "MATCH (r:ServiceRequest {reference: $reference, tenantId: $tenant}) "
        "RETURN r.id AS id ORDER BY r.id"
    ),
    mode="read",
    scenario=SCENARIOS["Q-CASE-BY-REF"],
)
_SET_POSTCODE: Final = NamedQuery(
    id="Q-CASE-SET-POSTCODE",
    cypher=(
        "MATCH (p:Patient {key: $key, tenantId: $tenant}) "
        "SET p.postalCode = $postalCode RETURN count(p) AS set"
    ),
    mode="write",
    scenario=SCENARIOS["Q-CASE-SET-POSTCODE"],
)
_READ_POSTCODE: Final = NamedQuery(
    id="Q-CASE-READ-POSTCODE",
    cypher="MATCH (p:Patient {key: $key, tenantId: $tenant}) RETURN p.postalCode AS postalCode",
    mode="read",
    scenario=SCENARIOS["Q-CASE-READ-POSTCODE"],
)
_SET_REFERENCE: Final = NamedQuery(
    id="Q-CASE-SET-REFERENCE",
    cypher=(
        "MATCH (r:ServiceRequest {key: $key, tenantId: $tenant}) "
        "SET r.reference = $reference, r.openReference = $openReference RETURN count(r) AS set"
    ),
    mode="write",
    scenario=SCENARIOS["Q-CASE-SET-REFERENCE"],
)


def _register(query: NamedQuery) -> None:
    if query.id not in REGISTRY.ids():
        REGISTRY.register(query)


for _query in (_LOOKUP_BY_REFERENCE, _SET_POSTCODE, _READ_POSTCODE, _SET_REFERENCE):
    _register(_query)


def _patient_id(case_id: str) -> str:
    return f"pt-{case_id}"


def _score_id(case_id: str, index: int, revision: int = 0) -> str:
    """The id of the index-th score observation. Revision 0 is the first recording; a corrected
    case names its observations by the correction count, so a correction never rewrites one."""
    return f"sc-{case_id}-{index}" if revision == 0 else f"sc-{case_id}-{index}-r{revision}"


def _utc_text(value: datetime) -> str:
    """FHIR instant text in UTC with a Z. Fractions are kept without trailing zeros, which the
    store reads back identically (DEC-053 item 2)."""
    text = value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    if value.microsecond:
        text += "." + f"{value.microsecond:06d}".rstrip("0")
    return text + "Z"


def _datetime(text: Any, field: str) -> datetime:
    if not isinstance(text, str):
        raise ValidationFailed(field, "must be text")
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        raise ValidationFailed(field, "not a datetime") from None
    if value.utcoffset() is None:
        raise ValidationFailed(field, "must carry a zone")
    return value.astimezone(UTC)


def _extension(short_name: str, value: Any) -> dict[str, Any]:
    defn = by_short_name(short_name)
    if defn is None:  # a programming error: these names are registered at import
        raise LookupError(short_name)
    return {"url": defn.url, defn.value_key: value}


def _extension_values(resource: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for entry in resource.get("extension", []):
        defn = EXTENSIONS.get(entry.get("url"))
        if defn is None:
            raise ValidationFailed("extension", "not a registered extension")
        values[defn.short_name] = entry[defn.value_key]
    return values


def _required(values: dict[str, Any], name: str) -> Any:
    if name not in values:
        raise ValidationFailed(name, "required")
    return values[name]


def _coded_text(concept: Any, system: str, field: str) -> str:
    codings = concept.get("coding") if isinstance(concept, dict) else None
    if not isinstance(codings, list) or len(codings) != 1 or not isinstance(codings[0], dict):
        raise ValidationFailed(field, "needs exactly one coding")
    if codings[0].get("system") != system:
        raise ValidationFailed(field, "not from the expected code system")
    code = codings[0].get("code")
    if not isinstance(code, str):
        raise ValidationFailed(field, "code must be text")
    return code


def _check_district(postcode: str | None) -> None:
    # Only the district is stored (owner decision, DEC-067 item 1). The value is not echoed.
    if postcode is not None and normalise_district(postcode) != postcode:
        raise ValidationFailed("postcode", "must be a district, not a full postcode")


def _check_reference(reference: str) -> None:
    if CASE_REFERENCE.fullmatch(reference) is None:
        raise ValidationFailed("reference", "must be four digits with no leading zero")


def _check_closed_residue(case: Case) -> None:
    # A closed case holds no postcode or needs. Refused rather than cleared (DEC-067 item 6).
    if case.closed_at is not None and (case.postcode is not None or case.needs):
        raise ValidationFailed("closed", "a closed case holds no postcode or needs")


def _check_outcome(case: Case) -> None:
    # Read-side twin: case_from_fhir refuses an outcome without a close time (DEC-067 item 5).
    if case.outcome is not None and case.closed_at is None:
        raise ValidationFailed("outcome", "needs a close time")


def _refuse_unknown(resource: dict[str, Any], allowed: frozenset[str], field: str) -> None:
    # An element the mapping cannot represent is refused, never dropped (DEC-067 item 3).
    for key in resource:
        if key not in allowed:
            raise ValidationFailed(field, "an element the case mapping cannot represent")


def _check_priority(request: dict[str, Any], urgency_text: str | None) -> None:
    priority = request.get(_PRIORITY)
    if urgency_text is None:
        if priority is not None:
            raise ValidationFailed(_PRIORITY, "needs an urgency")
        return
    if priority != priority_for(parse_code(Urgency, urgency_text)):
        raise ValidationFailed(_PRIORITY, "does not match the urgency")


def _check_status(request: dict[str, Any], closed_text: str | None) -> None:
    expected = _REQUEST_STATUS_COMPLETED if closed_text is not None else _REQUEST_STATUS_ACTIVE
    if request.get("status") != expected:
        raise ValidationFailed("status", "does not match the close time")


def _score_to_fhir(
    case_id: str, patient_id: str, index: int, score: Score, revision: int = 0
) -> dict[str, Any]:
    resource: dict[str, Any] = {
        "resourceType": _OBSERVATION,
        "id": _score_id(case_id, index, revision),
        "status": _STATUS_FINAL,
        "code": codeable_to_fhir(method_of(score)),
        "subject": {"reference": f"{_PATIENT}/{patient_id}"},
    }
    match score:
        case News2() | ClinicalFrailty() | AmbulanceCategory():
            resource["valueInteger"] = score.value
        case ManchesterTriage():
            resource["valueCodeableConcept"] = {
                "coding": [{"system": MANCHESTER_SYSTEM, "code": score.level}]
            }
        case PathwaysDx():
            resource["valueCodeableConcept"] = {
                "coding": [{"system": PATHWAYS_SYSTEM, "code": score.code}]
            }
    return resource


def _score_from_fhir(resource: dict[str, Any]) -> Score:
    method = codeable_from_fhir(_required(resource, "code"), AcuityMethod, "code")
    match method:
        case AcuityMethod.NEWS2:
            return News2(_required(resource, "valueInteger"))
        case AcuityMethod.CFS:
            return ClinicalFrailty(_required(resource, "valueInteger"))
        case AcuityMethod.AMBULANCE_CATEGORY:
            return AmbulanceCategory(_required(resource, "valueInteger"))
        case AcuityMethod.MANCHESTER:
            level = _coded_text(
                _required(resource, "valueCodeableConcept"),
                MANCHESTER_SYSTEM,
                "valueCodeableConcept",
            )
            return ManchesterTriage(level)
        case AcuityMethod.PATHWAYS_DX:
            code = _coded_text(
                _required(resource, "valueCodeableConcept"), PATHWAYS_SYSTEM, "valueCodeableConcept"
            )
            return PathwaysDx(code)
    raise ValidationFailed("code", "not an acuity method")


def case_to_fhir(case: Case) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """The Patient stub, the ServiceRequest and the score Observations for a case.

    The stub's postcode is present only while the case is open. Its meta (tag and security label)
    is part of this output; the repository does not store it (see the module docstring)."""
    _check_district(case.postcode)
    _check_reference(case.reference)
    _check_closed_residue(case)
    _check_outcome(case)
    patient_id = _patient_id(case.id)
    patient: dict[str, Any] = {
        "resourceType": _PATIENT,
        "id": patient_id,
        "active": True,
        "meta": {
            "tag": [{"system": TAG_SYSTEM, "code": TAG_CODE}],
            "security": [
                {"system": SECURITY_SYSTEM, "code": SECURITY_CODE, "display": "restricted"}
            ],
        },
    }
    if case.age_band is not None:
        patient["extension"] = [_extension(_EXT_AGE_BAND, case.age_band.value)]
    if case.postcode is not None:
        patient["address"] = [{"postalCode": case.postcode}]

    extensions = (
        []
        if case.referrer_type is None
        else [_extension(_EXT_REFERRER_TYPE, case.referrer_type.value)]
    )
    request: dict[str, Any] = {
        "resourceType": _REQUEST,
        "id": case.id,
        "status": _REQUEST_STATUS_COMPLETED if case.closed_at else _REQUEST_STATUS_ACTIVE,
        "intent": _INTENT_PLAN,
        "authoredOn": _utc_text(case.opened_at),
        "identifier": [{"system": REFERENCE_SYSTEM, "value": case.reference}],
        "subject": {"reference": f"{_PATIENT}/{patient_id}"},
    }
    if case.scores:
        # Left out when empty: the resource store refuses an empty list (a case is opened before
        # any score is known, U11).
        request["supportingInfo"] = [
            {"reference": f"Observation/{_score_id(case.id, index, case.score_corrections)}"}
            for index in range(1, len(case.scores) + 1)
        ]
    if case.urgency is not None:
        request[_PRIORITY] = priority_for(case.urgency)
        extensions.append(_extension(_EXT_URGENCY, case.urgency.value))
    if case.needs:
        request["reasonCode"] = [codeable_to_fhir(need) for need in case.needs]
    if case.destination_service_id is not None:
        request["performer"] = [{"reference": f"{_PERFORMER_PREFIX}{case.destination_service_id}"}]
    if case.closed_at is not None:
        extensions.append(_extension(_EXT_CLOSED_AT, _utc_text(case.closed_at)))
    if case.outcome is not None:
        extensions.append(_extension(_EXT_OUTCOME, case.outcome.value))
    if case.best_fit_not_used is not None:
        extensions.append(_extension(_EXT_BEST_FIT, case.best_fit_not_used.value))
    if case.score_corrections:
        extensions.append(_extension(_EXT_SCORE_CORRECTIONS, case.score_corrections))
    if extensions:
        # Left out when empty, as the store refuses an empty list (a case with no referrer yet).
        request["extension"] = extensions

    scores = [
        _score_to_fhir(case.id, patient_id, index, score, case.score_corrections)
        for index, score in enumerate(case.scores, start=1)
    ]
    return patient, request, scores


def case_from_fhir(
    patient: dict[str, Any], service_request: dict[str, Any], scores: list[dict[str, Any]]
) -> Case:
    """The case for a stub, its request and its score Observations, in the order they were
    recorded. Refuses an identity element on the stub and any value it does not recognise."""
    case_id = str(_required(service_request, "id"))
    if patient.get("id") != _patient_id(case_id):
        raise ValidationFailed("patient", "is not the stub of this case")

    _refuse_unknown(patient, _PATIENT_KEYS, "patient")
    _refuse_unknown(service_request, _REQUEST_KEYS, "serviceRequest")
    for resource in scores:
        _refuse_unknown(resource, _SCORE_KEYS, "score")
    patient_values = _extension_values(patient)
    values = _extension_values(service_request)
    identifiers = _required(service_request, "identifier")
    if not isinstance(identifiers, list) or len(identifiers) != 1:
        raise ValidationFailed("identifier", "needs exactly one case reference")
    if identifiers[0].get("system") != REFERENCE_SYSTEM:
        raise ValidationFailed("identifier", "not the case reference system")

    postcode: str | None = None
    addresses = patient.get("address", [])
    if addresses:
        if len(addresses) != 1 or not isinstance(addresses[0], dict):
            raise ValidationFailed("address", "needs exactly one postcode")
        postcode = str(_required(addresses[0], "postalCode"))

    performers = service_request.get("performer", [])
    destination: str | None = None
    if performers:
        reference = _required(performers[0], "reference") if len(performers) == 1 else ""
        if not isinstance(reference, str) or not reference.startswith(_PERFORMER_PREFIX):
            raise ValidationFailed("performer", "needs one HealthcareService")
        destination = reference[len(_PERFORMER_PREFIX) :]

    closed_text = values.get(_EXT_CLOSED_AT)
    urgency_text = values.get(_EXT_URGENCY)
    outcome_text = values.get(_EXT_OUTCOME)
    best_fit_text = values.get(_EXT_BEST_FIT)
    age_text = patient_values.get(_EXT_AGE_BAND)
    _check_priority(service_request, urgency_text)
    _check_status(service_request, closed_text)
    if outcome_text is not None and closed_text is None:
        raise ValidationFailed(_EXT_OUTCOME, "needs a close time")
    return Case(
        id=case_id,
        reference=str(identifiers[0]["value"]),
        referrer_type=(
            None
            if values.get(_EXT_REFERRER_TYPE) is None
            else parse_code(ReferrerType, values[_EXT_REFERRER_TYPE])
        ),
        age_band=None if age_text is None else parse_code(AgeBand, age_text),
        postcode=postcode,
        needs=tuple(
            codeable_from_fhir(concept, NeedCategory, "reasonCode")
            for concept in service_request.get("reasonCode", [])
        ),
        urgency=None if urgency_text is None else parse_code(Urgency, urgency_text),
        scores=tuple(_score_from_fhir(resource) for resource in scores),
        opened_at=_datetime(_required(service_request, "authoredOn"), "authoredOn"),
        closed_at=None if closed_text is None else _datetime(closed_text, _EXT_CLOSED_AT),
        outcome=None if outcome_text is None else parse_code(Outcome, outcome_text),
        best_fit_not_used=(
            None if best_fit_text is None else parse_code(BestFitNotUsedReason, best_fit_text)
        ),
        destination_service_id=destination,
        score_corrections=int(values.get(_EXT_SCORE_CORRECTIONS, 0)),
    )


class Neo4jCaseRepository:
    """Cases as a Patient stub, a ServiceRequest and score Observations. Built per transaction
    (DEC-012). Every write goes through the resource store, which checks the version after its
    lock (DEC-053 item 4)."""

    def __init__(self, tx: ScopedTx, store: ResourceStore) -> None:
        self._tx = tx
        self._store = store

    async def add(self, case: Case) -> None:
        # The store refuses an existing Patient with Conflict before it writes anything, so a
        # second add of one case is refused on its first write (expected version None).
        patient, request, scores = case_to_fhir(case)
        if await run_query(self._tx, REGISTRY.get("Q-CASE-BY-REF"), reference=case.reference):
            raise Conflict("another case already holds this reference")
        await self._put_patient(case, patient, expected=None)
        for resource in scores:
            await self._store.put(resource, None)
        await self._put_request(case, request, expected=None)

    async def opened_between(self, start: datetime, end: datetime) -> list[Case]:
        rows = await run_query(
            self._tx,
            REGISTRY.get("Q-CASE-OPENED-BETWEEN"),
            start=start.astimezone(UTC),
            end=end.astimezone(UTC),
        )
        found = [await self.get(str(row["id"])) for row in rows]
        return [case for case in found if case is not None]

    async def get(self, case_id: str) -> Case | None:
        request = await self._store.get(_REQUEST, case_id)
        if request is None:
            return None
        patient_id = _patient_id(case_id)
        patient = await self._store.get(_PATIENT, patient_id)
        if patient is None:
            raise NotFound(f"{_PATIENT}/{patient_id}")
        observations: list[dict[str, Any]] = []
        for entry in request.get("supportingInfo", []):
            observation_id = str(entry["reference"]).split("/", 1)[1]
            observation = await self._store.get(_OBSERVATION, observation_id)
            if observation is None:
                raise NotFound(f"{_OBSERVATION}/{observation_id}")
            observations.append(_without_meta(observation))
        postcode = await self._postcode(patient_id)
        return case_from_fhir(
            _rebuilt_patient(patient, postcode), _rebuilt_request(request), observations
        )

    async def get_versioned(self, case_id: str) -> tuple[Case, int] | None:
        """The case and its version: the version of its ServiceRequest (H-192)."""
        request = await self._store.get(_REQUEST, case_id)
        if request is None:
            return None
        case = await self.get(case_id)
        if case is None:
            return None
        return case, int(request["meta"]["versionId"])

    async def get_by_reference(self, reference: str) -> Case | None:
        rows = await run_query(self._tx, REGISTRY.get("Q-CASE-BY-REF"), reference=reference)
        if not rows:
            return None
        return await self.get(str(rows[0]["id"]))

    async def save(self, case: Case, *, expected_version: int | None = None) -> None:
        """Replace the stored case. With `expected_version`, a case that is at another version is
        StaleVersion, before anything is written. Every refusal comes before the first write, so a
        caller that catches it commits nothing."""
        current = await self._store.get(_REQUEST, case.id)
        if current is None:
            raise NotFound(f"{_REQUEST}/{case.id}")
        current_version = str(current["meta"]["versionId"])
        if expected_version is not None and str(expected_version) != current_version:
            raise StaleVersion
        stored = await self.get(case.id)
        if stored is None:  # the request exists, so this is a broken graph
            raise NotFound(f"{_REQUEST}/{case.id}")
        _check_scores_change(stored, case)
        if stored.reference != case.reference:
            raise ValidationFailed("reference", "the case reference cannot change")
        if stored.closed_at is not None and case != stored:
            raise InvalidTransition("a closed case cannot change")

        patient, request, scores = case_to_fhir(case)
        try:
            await self._write(case, patient, request, scores, current_version)
        except Conflict as error:
            if expected_version is not None and "is at version" in str(error):
                raise StaleVersion from error  # a writer got in after the check above
            raise

    async def _write(
        self,
        case: Case,
        patient: dict[str, Any],
        request: dict[str, Any],
        scores: list[dict[str, Any]],
        request_version: str,
    ) -> None:
        patient_current = await self._store.get(_PATIENT, _patient_id(case.id))
        patient_expected = (
            None if patient_current is None else str(patient_current["meta"]["versionId"])
        )
        await self._put_patient(case, patient, expected=patient_expected)
        for resource in scores:
            # Each Observation is written once (the store refuses an existing one): one that is
            # already there is a score kept as recorded, and one that is not is new (a first
            # recording, an added method or a correction's new revision), written before the
            # request that lists it, in the bound tenant like every other put.
            if await self._store.get(_OBSERVATION, resource["id"]) is None:
                await self._store.put(resource, None)
        await self._put_request(case, request, expected=request_version)

    async def _put_patient(self, case: Case, patient: dict[str, Any], expected: str | None) -> None:
        # The stub is not written with its meta or its postcode: the store refuses meta, and the
        # postcode is a property set after the put, so a closed case has none (DEC-066).
        resource = {key: value for key, value in patient.items() if key not in ("meta", "address")}
        await self._store.put(resource, expected)
        key = f"{_PATIENT}/{_patient_id(case.id)}"
        await run_query(
            self._tx, REGISTRY.get("Q-CASE-SET-POSTCODE"), key=key, postalCode=case.postcode
        )

    async def _put_request(self, case: Case, request: dict[str, Any], expected: str | None) -> None:
        # The reference is a copy of the identifier, set after the put (DEC-066).
        await self._store.put(request, expected)
        key = f"{_REQUEST}/{case.id}"
        try:
            # The open reference is what the per-tenant constraint is unique on (migration 0033):
            # set while the case is open, and removed when it closes (a null property is removed),
            # so a closed case's reference blocks nobody once the lifetime constraint goes
            # (TEN-032).
            await run_query(
                self._tx,
                REGISTRY.get("Q-CASE-SET-REFERENCE"),
                key=key,
                reference=case.reference,
                openReference=case.reference if case.closed_at is None else None,
            )
        except ClientError as error:
            # The unique constraint on the reference (migration 0022) refused a racing write.
            if str(getattr(error, "code", "")).endswith("ConstraintValidationFailed"):
                raise Conflict("another case already holds this reference") from error
            raise

    async def _postcode(self, patient_id: str) -> str | None:
        rows = await run_query(
            self._tx, REGISTRY.get("Q-CASE-READ-POSTCODE"), key=f"{_PATIENT}/{patient_id}"
        )
        if not rows or rows[0]["postalCode"] is None:
            return None
        return str(rows[0]["postalCode"])


def _check_scores_change(stored: Case, case: Case) -> None:
    """A recorded score changes only as a correction (DEC-1171): the correction count rises by one
    and every recorded method stays recorded; otherwise the recorded scores are a prefix of the
    saved ones (a method added). Anything else is refused, before any write."""
    if case.score_corrections == stored.score_corrections:
        if case.scores[: len(stored.scores)] != stored.scores:
            raise ValidationFailed("scores", "recorded scores cannot change")
        return
    if case.score_corrections != stored.score_corrections + 1:
        raise ValidationFailed("scores", "a save records one correction at most")
    kept = {method_of(score) for score in case.scores}
    if any(method_of(score) not in kept for score in stored.scores):
        raise ValidationFailed("scores", "a correction does not remove a recorded score")


def _rebuilt_patient(patient: dict[str, Any], postcode: str | None) -> dict[str, Any]:
    """The stored stub with its postcode put back as the address the mapper does not hold."""
    rebuilt = {key: value for key, value in patient.items() if key not in ("meta", "postalCode")}
    if postcode is not None:
        rebuilt["address"] = [{"postalCode": postcode}]
    return rebuilt


def _without_meta(resource: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in resource.items() if key != "meta"}


def _rebuilt_request(request: dict[str, Any]) -> dict[str, Any]:
    """The stored request without the reference copy and the open reference, which are not FHIR
    elements of their own."""
    return {
        key: value
        for key, value in request.items()
        if key not in ("meta", "reference", "openReference")
    }


_OPENED_BETWEEN: Final = NamedQuery(
    id="Q-CASE-OPENED-BETWEEN",
    cypher=(
        "MATCH (r:ServiceRequest {tenantId: $tenant}) "
        "WHERE r.authoredOn >= $start AND r.authoredOn < $end "
        "RETURN r.id AS id ORDER BY r.authoredOn ASC, r.id ASC"
    ),
    mode="read",
    scenario=WEEK_SCENARIOS["Q-CASE-OPENED-BETWEEN"],
)
if _OPENED_BETWEEN.id not in REGISTRY.ids():
    REGISTRY.register(_OPENED_BETWEEN)
