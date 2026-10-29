"""Reviewing a registration up to the decision (U28, docs/spec/domain-rules.md section 6).

The shift lead starts the review (submitted to in-review), the system runs five automatic checks,
the lead may explain a failed check, calls the number on the register back, and records the scope
decision. Each is one unit of work with its audit entry. The call-back and the scope decision are
also Provenance records on the registration (fhir-data-model.md "Checks as provenance"). Approval,
send-back and go-live are U29; criteria approval is U30.

The five checks (each passed or failed, with a message): the ODS code is found, active and an NHS
organisation; the organisation's name is the ODS name; the address is found and in the area (or, for
a visiting service, every district is); the number given for reporting is the number invited; the
criteria owner's email is an organisation address. An explained failure counts as ok. The checks are
re-run from what is stored every time they are needed, so a number changed after the review started
is seen. The area is the tenant's own: it comes from `area_districts_for(scope)`, there is no
built-in default (a tenant that inherited Dorset's districts would be wrong, DEC-317).

The number called is never in the graph's records: it goes to the protected contact store under a
key of its own, and the Provenance holds only a keyed hash of it. Decisions: DEC-317 to DEC-320.
"""

import hashlib
import hmac
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import PHONE_HASH_SECRET, PhoneHasher
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound
from diucs.application.use_cases.invite_reporter import lead_post
from diucs.application.use_cases.registration_draft import RegistrationDraft, read_draft
from diucs.application.use_cases.registration_submit import Lookups, lookups_of
from diucs.application.use_cases.scope_list import check_reason
from diucs.domain.codes import CriteriaStatus, RegistrationStatus, Role, ScopeFlag
from diucs.domain.errors import Conflict, InvalidTransition, NotAllowed, NotFound, ValidationFailed
from diucs.domain.messages.privacy_guard import find_patient_data
from diucs.domain.model.people import check_staff_text
from diucs.domain.model.registration import Answer, CallBackResult, Registration
from diucs.domain.rules.postcode import normalise_district
from diucs.domain.rules.registration import (
    ApprovalChecks,
    missing_for_approval,
    transition_registration,
)

AreaDistrictsFor = Callable[[ScopeId], frozenset[str]]
"""The district codes of a tenant's area, given the bound scope. The composition root backs it with
the tenant's configuration; nothing here has a default (DEC-317)."""
CHECK_ODS: Final = "ods-code"
CHECK_NAME: Final = "organisation-name"
CHECK_ADDRESS: Final = "address-area"
CHECK_PHONE: Final = "reporting-phone"
CHECK_EMAIL: Final = "owner-email"
CHECK_ORDER: Final = (CHECK_ODS, CHECK_NAME, CHECK_ADDRESS, CHECK_PHONE, CHECK_EMAIL)
NOTES_STEP: Final = "check_notes"
"""The key of the explanations in a registration's draft: check name to note. Not a wizard step."""
FREE_MAIL_DOMAINS: Final = frozenset({"gmail.com", "hotmail.com", "outlook.com", "yahoo.com"})
"""[ASSUMED] domain-rules 6: free-mail domains never make an organisation address."""
NHS_MAIL_DOMAIN: Final = "nhs.net"
NHS_ORGANISATION_TYPES: Final = frozenset(
    {
        "NHS TRUST",
        "NHS TRUST SITE",
        "NHS FOUNDATION TRUST",
        "GP PRACTICE",
        "PRIMARY CARE NETWORK",
        "INTEGRATED CARE BOARD",
        "COMMUNITY HEALTH SERVICE",
        "PILOT-SAMPLE",
    }
)
"""[ASSUMED] The ODS role names that count as an NHS organisation, compared ignoring case and
punctuation. PILOT-SAMPLE is the role of the pilot's sample directory."""
NOTE_MAX_LENGTH: Final = 500
ROLE_SPOKEN_MAX_LENGTH: Final = 80
MISSING_PHONE_MESSAGE: Final = "Enter the full phone number from the register"
REVIEW_USE_CASE: Final = "ReviewRegistration"
AUDIT_UPDATE: Final = "U"
CALLBACK_KEY_PREFIX: Final = "callback-"
"""The contact-store key of a number called: `callback-<id>`, one per call-back, so the audit can
find the number of that call and a later call-back does not overwrite it."""

_PUNCTUATION: Final = re.compile(r"[\W_]+")
_APOSTROPHES: Final = ("'", "’")
_DISTRICT_PREFIX: Final = re.compile(r"[A-Z]{1,2}")
_SEPARATORS: Final = re.compile(r"[\s\-().]")
_FULL_NUMBER: Final = re.compile(r"0[0-9]{10}")


@dataclass(frozen=True, slots=True)
class AutomaticCheck:
    name: str
    passed: bool
    message: str
    explained_note: str | None = None

    @property
    def ok(self) -> bool:
        """Passed, or failed and explained: an explained failure counts as ok."""
        return self.passed or bool(self.explained_note)


@dataclass(frozen=True, slots=True)
class ScopeAnswers:
    """The four scope questions, each yes, no or not sure (ui-screens "ApprovalWeb2")."""

    on_dorset_pathway: Answer
    takes_spoa_referrals: Answer
    can_report: Answer
    category_on_pilot_list: Answer


@dataclass(frozen=True, slots=True)
class ReviewStatus:
    registration_id: str
    status: RegistrationStatus
    checks: tuple[AutomaticCheck, ...]
    automatic_ok: bool
    callback_confirmed: bool
    scope: ScopeFlag | None
    criteria_approved: bool
    missing: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StartReviewCommand:
    idempotency_key: str
    actor: Actor
    registration_id: str


@dataclass(frozen=True, slots=True)
class StartReviewResult:
    registration_id: str
    status: RegistrationStatus
    reviewer_role_id: str


@dataclass(frozen=True, slots=True)
class ExplainCheckCommand:
    idempotency_key: str
    actor: Actor
    registration_id: str
    check_name: str
    note: str


@dataclass(frozen=True, slots=True)
class ExplainCheckResult:
    registration_id: str
    check_name: str
    automatic_ok: bool


@dataclass(frozen=True, slots=True)
class RecordCallBackCommand:
    idempotency_key: str
    actor: Actor
    registration_id: str
    number_called: str
    role_spoken_to: str
    result: CallBackResult


@dataclass(frozen=True, slots=True)
class RecordCallBackResult:
    registration_id: str
    result: CallBackResult
    callback_confirmed: bool
    provenance_id: str


@dataclass(frozen=True, slots=True)
class RecordScopeDecisionCommand:
    idempotency_key: str
    actor: Actor
    registration_id: str
    answers: ScopeAnswers
    decision: ScopeFlag
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RecordScopeDecisionResult:
    registration_id: str
    decision: ScopeFlag
    provenance_id: str


@dataclass(frozen=True, slots=True)
class GetReviewStatusQuery:
    actor: Actor
    registration_id: str


@dataclass(frozen=True, slots=True)
class _Stored:
    """A result with the fingerprint of the command that made it (DEC-104)."""

    fingerprint: str
    result: object


def check_may_review(actor: Actor) -> str:
    """Only a shift lead acting as a named practitioner reviews. Returns the practitioner id."""
    if actor.role is not Role.LEAD:
        raise NotAllowed("only the shift lead may review a registration")
    if actor.practitioner_id is None:
        raise NotAllowed("the lead must act as a named practitioner")
    return actor.practitioner_id


def name_key(text: str) -> str:
    """A name for comparison: lower case, apostrophes dropped, every other run of punctuation or
    space one space. "St. Mary's Ward" and "ST MARYS WARD" are the same."""
    for apostrophe in _APOSTROPHES:
        text = text.replace(apostrophe, "")
    return " ".join(_PUNCTUATION.sub(" ", text.casefold()).split())


def _domain_of(address: str) -> str | None:
    text = address.strip()
    local, separator, domain = text.partition("@")
    if not separator or not local or "@" in domain or any(c.isspace() for c in text):
        return None
    domain = domain.lower()
    return (
        domain
        if "." in domain and not domain.startswith(".") and not domain.endswith(".")
        else None
    )


def organisation_email_ok(owner_email: str, organisation_email: str) -> bool:
    """An organisation address: `nhs.net`, or the same domain as the organisation's own contact
    email. A free-mail domain never is, even when the organisation's contact uses one."""
    owner = _domain_of(owner_email)
    if owner is None or owner in FREE_MAIL_DOMAINS:
        return False
    if owner == NHS_MAIL_DOMAIN:
        return True
    return owner == _domain_of(organisation_email)


def number_digits(number: str) -> str:
    """A full UK phone number as eleven digits from 0: spaces, hyphens, brackets, +44 and 0044 are
    accepted. Anything else is ValidationFailed on `number_called`, without the number."""
    if not isinstance(number, str):
        raise ValidationFailed("number_called", MISSING_PHONE_MESSAGE)
    compact = _SEPARATORS.sub("", number)
    if compact.startswith("+44"):
        national = "0" + compact[3:].removeprefix("0")
    elif compact.startswith("0044"):
        national = "0" + compact[4:]
    else:
        national = compact
    if _FULL_NUMBER.fullmatch(national) is None:
        raise ValidationFailed("number_called", MISSING_PHONE_MESSAGE)
    return national


def callback_number_hash(secret: bytes, number: str) -> str:
    """The keyed hash of a number called, which is all the Provenance holds. It is separated from
    the phone hash of a person (a landline is hashed here, and a person's hash cannot be matched
    to a number called)."""
    message = f"callback|{number_digits(number)}".encode("ascii")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def districts_in_ranges(*ranges: tuple[str, int, int]) -> frozenset[str]:
    """The district codes of a prefix and a run of numbers: ("DT", 1, 11) is DT1 to DT11. Helps a
    tenant's configuration state its area; there is no default area (DEC-317)."""
    districts: set[str] = set()
    for prefix, low, high in ranges:
        if _DISTRICT_PREFIX.fullmatch(prefix) is None or not 1 <= low <= high:
            raise ValidationFailed("area", "a range is a prefix of letters and 1 <= low <= high")
        for number in range(low, high + 1):
            code = normalise_district(f"{prefix}{number}")
            if code is None:
                raise ValidationFailed("area", "a range must give district codes")
            districts.add(code)
    return frozenset(districts)


def _is_nhs_type(org_type: str | None) -> bool:
    return org_type is not None and name_key(org_type) in {
        name_key(item) for item in NHS_ORGANISATION_TYPES
    }


def _ods(lookups: Lookups | None) -> AutomaticCheck:
    if lookups is None:
        return AutomaticCheck(CHECK_ODS, False, "ODS code has not been checked")
    if not lookups.ods_found:
        return AutomaticCheck(CHECK_ODS, False, "ODS code not found")
    if not lookups.ods_active:
        return AutomaticCheck(CHECK_ODS, False, "ODS code is not active")
    if not _is_nhs_type(lookups.ods_type):
        return AutomaticCheck(CHECK_ODS, False, "ODS code is not an NHS organisation")
    return AutomaticCheck(CHECK_ODS, True, "ODS code found, active, NHS organisation")


def _name(draft: RegistrationDraft, lookups: Lookups | None) -> AutomaticCheck:
    if lookups is None or not lookups.ods_found or lookups.ods_name is None:
        return AutomaticCheck(
            CHECK_NAME, False, "Organisation name cannot be checked without an ODS record"
        )
    given = "" if draft.organisation is None else draft.organisation.name
    if name_key(given) != name_key(lookups.ods_name) or not name_key(given):
        return AutomaticCheck(CHECK_NAME, False, "Organisation name does not match the ODS name")
    return AutomaticCheck(CHECK_NAME, True, "Organisation name matches the ODS name")


def _visiting_districts(draft: RegistrationDraft) -> list[str]:
    if draft.service is None:
        return []
    items = [item.strip() for item in draft.service.districts.split(",") if item.strip()]
    return [normalise_district(item) or item for item in items]


def _address(
    draft: RegistrationDraft, lookups: Lookups | None, area: frozenset[str]
) -> AutomaticCheck:
    if draft.location is not None and not draft.location.fixed_site:
        districts = _visiting_districts(draft)
        if not districts:
            return AutomaticCheck(CHECK_ADDRESS, False, "No districts given")
        if any(district not in area for district in districts):
            return AutomaticCheck(CHECK_ADDRESS, False, "A district is outside the area")
        return AutomaticCheck(CHECK_ADDRESS, True, "Every district is in the area")
    if lookups is None or not lookups.address_found or lookups.address_district is None:
        return AutomaticCheck(CHECK_ADDRESS, False, "Address not found")
    if lookups.address_district not in area:
        return AutomaticCheck(CHECK_ADDRESS, False, "Address district is outside the area")
    return AutomaticCheck(CHECK_ADDRESS, True, "Address district is in the area")


def _phone(invited: str | None, reporting: str | None) -> AutomaticCheck:
    if invited is None or reporting is None or not hmac.compare_digest(invited, reporting):
        return AutomaticCheck(CHECK_PHONE, False, "Reporting phone is not the invited number")
    return AutomaticCheck(CHECK_PHONE, True, "Reporting phone is the invited number")


def _email(draft: RegistrationDraft) -> AutomaticCheck:
    owner = "" if draft.service is None else draft.service.owner_email
    organisation = "" if draft.organisation is None else draft.organisation.contact_email
    if organisation_email_ok(owner, organisation):
        return AutomaticCheck(CHECK_EMAIL, True, "Criteria owner email is an organisation address")
    return AutomaticCheck(CHECK_EMAIL, False, "Criteria owner email is not an organisation address")


def run_automatic_checks(
    registration: Registration,
    *,
    lookups: Lookups | None,
    invited_phone_hash: str | None,
    reporting_phone_hash: str | None,
    area_districts: frozenset[str],
    notes: Mapping[str, str] | None = None,
) -> tuple[AutomaticCheck, ...]:
    """The five automatic checks of a registration, in screen order. Pure: `lookups` is what the
    ODS directory and the geocoder said (U27), the two hashes are the phone invited and the phone
    given for reporting, `area_districts` is the tenant's area, and `notes` are the explanations
    (check name to note). A failed check with a note counts as ok."""
    draft = read_draft(registration)
    found = (
        _ods(lookups),
        _name(draft, lookups),
        _address(draft, lookups, area_districts),
        _phone(invited_phone_hash, reporting_phone_hash),
        _email(draft),
    )
    given = notes or {}
    explained: list[AutomaticCheck] = []
    for check in found:
        note = given.get(check.name, "").strip()
        explained.append(
            replace(check, explained_note=note) if note and not check.passed else check
        )
    return tuple(explained)


def automatic_ok(checks: tuple[AutomaticCheck, ...]) -> bool:
    """Every check passed or explained. No checks is not ok: nothing was judged."""
    return bool(checks) and all(check.ok for check in checks)


@dataclass(frozen=True, slots=True)
class _Evaluation:
    checks: tuple[AutomaticCheck, ...]
    criteria_approved: bool

    @property
    def automatic_ok(self) -> bool:
        return automatic_ok(self.checks)


def _tenant_scope(unit_scope: ScopeId | None) -> ScopeId:
    if unit_scope is None or unit_scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return unit_scope


def _command_key(operation: str, scope: ScopeId, key: str) -> str:
    """The replay key, named by operation and tenant (lesson L160)."""
    return f"review-registration:{operation}:{scope}:{key}"


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()


def _replayed(stored: object, fingerprint: str) -> object | None:
    if stored is None:
        return None
    if not isinstance(stored, _Stored) or stored.fingerprint != fingerprint:
        raise Conflict("this command key was used for a different review command")
    return stored.result


async def _load(uow: UnitOfWork, registration_id: str) -> Registration:
    registration = await uow.registrations.get(registration_id)
    if registration is None:
        raise NotFound("no registration with this id")
    return registration


def _require_in_review(registration: Registration) -> None:
    if registration.status is not RegistrationStatus.IN_REVIEW:
        raise InvalidTransition(f"a registration in {registration.status.value} is not in review")


def _notes_of(registration: Registration) -> dict[str, str]:
    held = registration.draft.get(NOTES_STEP, {})
    return {name: value for name, value in held.items() if isinstance(value, str)}


async def _invited_hash(uow: UnitOfWork, registration: Registration, now: datetime) -> str | None:
    """The phone hash of the person invited: the practitioner who holds the registration's
    requester post."""
    if registration.requester_role_id is None:
        return None
    roles = await uow.people.reporter_roles_for_service(registration.service_id, now)
    role = next((item for item in roles if item.id == registration.requester_role_id), None)
    if role is None:
        return None
    person = await uow.people.get_practitioner(role.practitioner_id)
    return None if person is None else person.phone_hash


async def _reporting_phone(uow: UnitOfWork, registration: Registration) -> str | None:
    if registration.requester_role_id is None:
        return None
    return await uow.contacts.get_phone(registration.requester_role_id)


def _hash_or_none(hasher: PhoneHasher, number: str | None) -> str | None:
    if number is None:
        return None
    try:
        return hasher.hash(number)
    except ValidationFailed:
        return None


async def _evaluate(
    uow: UnitOfWork,
    registration: Registration,
    hasher: PhoneHasher,
    area_districts_for: AreaDistrictsFor,
    now: datetime,
    notes: Mapping[str, str] | None = None,
) -> _Evaluation:
    scope = _tenant_scope(uow.unit_scope)
    checks = run_automatic_checks(
        registration,
        lookups=lookups_of(registration),
        invited_phone_hash=await _invited_hash(uow, registration, now),
        reporting_phone_hash=_hash_or_none(hasher, await _reporting_phone(uow, registration)),
        area_districts=area_districts_for(scope),
        notes=_notes_of(registration) if notes is None else notes,
    )
    criteria = await uow.criteria.current_for_service(registration.service_id)
    approved = criteria is not None and criteria.status is CriteriaStatus.CURRENT
    return _Evaluation(checks, approved)


def _checks_of(registration: Registration, evaluation: _Evaluation) -> ApprovalChecks:
    """The registration's stored checks with the two that are re-judged from what is stored."""
    return replace(
        registration.checks,
        automatic_ok=evaluation.automatic_ok,
        criteria_approved=evaluation.criteria_approved,
    )


async def _audit(
    uow: UnitOfWork,
    command_actor: Actor,
    registration: Registration,
    use_case: str,
    snapshot: dict[str, Any],
    now: datetime,
) -> None:
    await uow.audit.append(
        AuditEntry(
            action=AUDIT_UPDATE,
            use_case=use_case,
            actor=command_actor,
            entity_ids=(registration.id, registration.service_id),
            snapshot=snapshot,
            at=now,
        )
    )


class _Review:
    """What every review use case shares: the unit of work factory, the phone hasher, the clock and
    the tenant's area."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        phone_hasher: PhoneHasher,
        clock: Clock,
        *,
        area_districts_for: AreaDistrictsFor,
    ) -> None:
        self._uow_factory = uow_factory
        self._hasher = phone_hasher
        self._clock = clock
        self._area_districts_for = area_districts_for

    async def _evaluate(
        self,
        uow: UnitOfWork,
        registration: Registration,
        now: datetime,
        notes: Mapping[str, str] | None = None,
    ) -> _Evaluation:
        return await _evaluate(
            uow, registration, self._hasher, self._area_districts_for, now, notes
        )


class StartReview(_Review):
    async def execute(self, command: StartReviewCommand) -> StartReviewResult:
        lead_id = check_may_review(command.actor)
        fingerprint = _fingerprint("start", command.registration_id, lead_id)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            key = _command_key("start", scope, command.idempotency_key)
            replay = _replayed(await uow.idempotency.get(key), fingerprint)
            if isinstance(replay, StartReviewResult):
                return replay
            registration = await _load(uow, command.registration_id)
            transition_registration(registration.status, RegistrationStatus.IN_REVIEW)
            post = lead_post(await uow.people.roles_for_practitioner(lead_id))
            if post is None:
                raise NotAllowed("the lead holds no shift lead post")
            evaluation = await self._evaluate(uow, registration, now)
            await uow.registrations.save(
                replace(
                    registration,
                    status=RegistrationStatus.IN_REVIEW,
                    owner_role_id=post.id,
                    checks=_checks_of(registration, evaluation),
                    last_modified=now,
                )
            )
            await _audit(
                uow,
                command.actor,
                registration,
                "StartReview",
                {
                    "status": RegistrationStatus.IN_REVIEW.value,
                    "automatic_ok": evaluation.automatic_ok,
                    "failed": [check.name for check in evaluation.checks if not check.passed],
                },
                now,
            )
            result = StartReviewResult(
                registration_id=registration.id,
                status=RegistrationStatus.IN_REVIEW,
                reviewer_role_id=post.id,
            )
            await uow.idempotency.put(key, _Stored(fingerprint, result))
            await uow.commit()
        return result


class ExplainCheck(_Review):
    async def execute(self, command: ExplainCheckCommand) -> ExplainCheckResult:
        check_may_review(command.actor)
        if command.check_name not in CHECK_ORDER:
            raise ValidationFailed("check_name", "is not an automatic check")
        note = _checked_note(command.note)
        fingerprint = _fingerprint("explain", command.registration_id, command.check_name, note)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            key = _command_key("explain", scope, command.idempotency_key)
            replay = _replayed(await uow.idempotency.get(key), fingerprint)
            if isinstance(replay, ExplainCheckResult):
                return replay
            registration = await _load(uow, command.registration_id)
            _require_in_review(registration)
            held = _notes_of(registration)
            before = await self._evaluate(uow, registration, now, held)
            check = next(item for item in before.checks if item.name == command.check_name)
            if check.passed:
                raise Conflict("this check passed: there is nothing to explain")
            notes = {**held, command.check_name: note}
            after = await self._evaluate(uow, registration, now, notes)
            await uow.registrations.save(
                replace(
                    registration,
                    draft={**registration.draft, NOTES_STEP: notes},
                    checks=_checks_of(registration, after),
                    last_modified=now,
                )
            )
            await _audit(
                uow,
                command.actor,
                registration,
                "ExplainCheck",
                {"check": command.check_name, "automatic_ok": after.automatic_ok},
                now,
            )
            result = ExplainCheckResult(
                registration_id=registration.id,
                check_name=command.check_name,
                automatic_ok=after.automatic_ok,
            )
            await uow.idempotency.put(key, _Stored(fingerprint, result))
            await uow.commit()
        return result


def _checked_note(note: str) -> str:
    if not isinstance(note, str):
        raise ValidationFailed("note", "must be text")
    text = " ".join(note.split())
    if not text:
        raise ValidationFailed("note", "is required to explain a check")
    if len(text) > NOTE_MAX_LENGTH:
        raise ValidationFailed("note", f"must be at most {NOTE_MAX_LENGTH} characters")
    if find_patient_data(text):
        raise ValidationFailed("note", "must not hold anything that looks like patient information")
    return text


def _role_spoken_to(result: CallBackResult, role: str) -> str:
    """The role spoken to: required when someone was spoken to (confirmed or not confirmed),
    optional for no answer (DEC-318 item 2)."""
    text = " ".join(role.split()) if isinstance(role, str) else ""
    if not text and result is not CallBackResult.NO_ANSWER:
        raise ValidationFailed("role_spoken_to", "is required")
    if text:
        if len(text) > ROLE_SPOKEN_MAX_LENGTH:
            raise ValidationFailed(
                "role_spoken_to", f"must be at most {ROLE_SPOKEN_MAX_LENGTH} characters"
            )
        check_staff_text("role_spoken_to", text)
    return text


async def _applicant_numbers(uow: UnitOfWork, registration: Registration) -> set[str]:
    """The digits of every number the applicant gave: the reporting mobile, the organisation's
    contact phone and the SPOA phone. The number called must not be one of them."""
    draft = read_draft(registration)
    given = [await _reporting_phone(uow, registration)]
    if draft.organisation is not None:
        given.append(draft.organisation.contact_phone)
    if draft.service is not None:
        given.append(draft.service.spoa_phone)
    digits: set[str] = set()
    for number in given:
        if number:
            try:
                digits.add(number_digits(number))
            except ValidationFailed:
                continue
    return digits


class RecordCallBack(_Review):
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        phone_hasher: PhoneHasher,
        secret_store: SecretStore,
        ids: IdGenerator,
        clock: Clock,
        *,
        area_districts_for: AreaDistrictsFor,
    ) -> None:
        super().__init__(uow_factory, phone_hasher, clock, area_districts_for=area_districts_for)
        self._secrets = secret_store
        self._ids = ids

    async def execute(self, command: RecordCallBackCommand) -> RecordCallBackResult:
        lead_id = check_may_review(command.actor)
        if not isinstance(command.result, CallBackResult):
            raise ValidationFailed("result", "must be confirmed, not-confirmed or no-answer")
        role = _role_spoken_to(command.result, command.role_spoken_to)
        digits = number_digits(command.number_called)
        number_hash = callback_number_hash(self._secrets.get(PHONE_HASH_SECRET), digits)
        fingerprint = _fingerprint(
            "call-back", command.registration_id, number_hash, role, command.result.value
        )
        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            key = _command_key("call-back", scope, command.idempotency_key)
            replay = _replayed(await uow.idempotency.get(key), fingerprint)
            if isinstance(replay, RecordCallBackResult):
                return replay
            registration = await _load(uow, command.registration_id)
            _require_in_review(registration)
            if digits in await _applicant_numbers(uow, registration):
                raise ValidationFailed(
                    "number_called",
                    "must be the number on the register, not one the applicant gave",
                )
            callback_id = self._ids.new_id()
            await uow.contacts.put_phone(
                f"{CALLBACK_KEY_PREFIX}{callback_id}", command.number_called
            )
            extra: dict[str, Any] = {
                "callbackId": callback_id,
                "numberHash": number_hash,
                "result": command.result.value,
            }
            if role:
                extra["roleSpokenTo"] = role
            provenance_id = await uow.audit.append_provenance(
                "Task",
                registration.id,
                "call-back",
                lead_id,
                command.actor.role,
                extra=extra,
            )
            confirmed = command.result is CallBackResult.CONFIRMED
            await uow.registrations.save(
                replace(
                    registration,
                    checks=replace(registration.checks, callback_confirmed=confirmed),
                    last_modified=now,
                )
            )
            await _audit(
                uow,
                command.actor,
                registration,
                "RecordCallBack",
                {"result": command.result.value, "provenance_id": provenance_id},
                now,
            )
            result = RecordCallBackResult(
                registration_id=registration.id,
                result=command.result,
                callback_confirmed=confirmed,
                provenance_id=provenance_id,
            )
            await uow.idempotency.put(key, _Stored(fingerprint, result))
            await uow.commit()
        return result


class RecordScopeDecision(_Review):
    async def execute(self, command: RecordScopeDecisionCommand) -> RecordScopeDecisionResult:
        lead_id = check_may_review(command.actor)
        answers = command.answers
        values = (
            answers.on_dorset_pathway,
            answers.takes_spoa_referrals,
            answers.can_report,
            answers.category_on_pilot_list,
        )
        if not all(isinstance(value, Answer) for value in values):
            raise ValidationFailed("answers", "each question is answered yes, no or not sure")
        reason = check_reason(command.decision, command.reason)
        if reason and find_patient_data(reason):
            raise ValidationFailed(
                "reason", "must not hold anything that looks like patient information"
            )
        fingerprint = _fingerprint(
            "scope",
            command.registration_id,
            [v.value for v in values],
            command.decision.value,
            reason,
        )
        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            key = _command_key("scope", scope, command.idempotency_key)
            replay = _replayed(await uow.idempotency.get(key), fingerprint)
            if isinstance(replay, RecordScopeDecisionResult):
                return replay
            registration = await _load(uow, command.registration_id)
            _require_in_review(registration)
            extra: dict[str, Any] = {
                "onDorsetPathway": answers.on_dorset_pathway.value,
                "takesSpoaReferrals": answers.takes_spoa_referrals.value,
                "canReport": answers.can_report.value,
                "categoryOnPilotList": answers.category_on_pilot_list.value,
                "decision": command.decision.value,
            }
            if reason:
                extra["reason"] = reason
            provenance_id = await uow.audit.append_provenance(
                "Task",
                registration.id,
                "scope-decision",
                lead_id,
                command.actor.role,
                extra=extra,
            )
            await uow.registrations.save(
                replace(
                    registration,
                    checks=replace(registration.checks, scope=command.decision),
                    last_modified=now,
                )
            )
            await _audit(
                uow,
                command.actor,
                registration,
                "RecordScopeDecision",
                {"decision": command.decision.value, "provenance_id": provenance_id},
                now,
            )
            result = RecordScopeDecisionResult(
                registration_id=registration.id,
                decision=command.decision,
                provenance_id=provenance_id,
            )
            await uow.idempotency.put(key, _Stored(fingerprint, result))
            await uow.commit()
        return result


class GetReviewStatus(_Review):
    """The checks and what is still missing before approval, judged from what is stored now. Read
    only: nothing is written."""

    async def execute(self, query: GetReviewStatusQuery) -> ReviewStatus:
        check_may_review(query.actor)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            registration = await _load(uow, query.registration_id)
            evaluation = await self._evaluate(uow, registration, now)
            stored = _checks_of(registration, evaluation)
            return ReviewStatus(
                registration_id=registration.id,
                status=registration.status,
                checks=evaluation.checks,
                automatic_ok=stored.automatic_ok,
                callback_confirmed=stored.callback_confirmed,
                scope=stored.scope,
                criteria_approved=stored.criteria_approved,
                missing=tuple(missing_for_approval(stored)),
            )
