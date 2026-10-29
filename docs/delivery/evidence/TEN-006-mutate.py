"""TEN-006 mutation check (hand-run, no mutation tool is installed).

Applies one mutation at a time to a source file of this task, runs the four TEN-006 test files with
`-x`, records the first failing test and restores the file with `git checkout`. Run from a clean
tree: `python docs/delivery/evidence/TEN-006-mutate.py [name fragment ...]`. It was run in two
passes on the green commit (9e78b93 before the rebase onto main, aba64b6 after): pass one (99 mutants) mis-reported one mutant whose import failed as
"survived", applied one with a stale snippet and contained one no-op; the replacements and the
mutants for the guards whose tests were added after the red commit are the last six entries.
"""
import subprocess, sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3] / "backend"
SRC = "src/diucs/domain/"
TESTS = [
    "tests/unit/domain/model/test_tenant.py",
    "tests/unit/domain/model/test_tenant_id_parity.py",
    "tests/unit/domain/rules/test_tenant_settings.py",
    "tests/unit/domain/rules/test_tenant_lifecycle.py",
]
M = "model/"; R = "rules/"
MUTANTS = [
 # (name, file, old, new)
 ("tenant: drop the net- prefix refusal", M+"tenant.py", "        or value.startswith(RESERVED_TENANT_PREFIX)\n", "        or False\n"),
 ("tenant: drop the reserved id refusal", M+"tenant.py", "        or value in RESERVED_TENANT_IDS\n", "        or False\n"),
 ("tenant: widen the id length by one", M+"tenant.py", '{1,30}")', '{1,31}")'),
 ("tenant: allow UTC", M+"tenant.py", "ALLOWED_TIME_ZONES: Final = frozenset({DEFAULT_TIME_ZONE})", 'ALLOWED_TIME_ZONES: Final = frozenset({DEFAULT_TIME_ZONE, "UTC"})'),
 ("tenant: skip the zone database load", M+"tenant.py", "        ZoneInfo(value)\n", "        pass\n"),
 ("tenant: enum checked by value, not type", M+"tenant.py", "    if type(value) is not enum_type:", "    if str(value) not in [m.value for m in enum_type]:"),
 ("tenant: skip status and timestamp agreement", M+"tenant.py", "            if (value is not None) != (status in statuses):", "            if False:"),
 ("tenant: skip the timestamp order", M+"tenant.py", "        if any(earlier > later for earlier, later in pairwise(chain)):", "        if False:"),
 ("tenant: skip activated_at for non-provisioning", M+"tenant.py", "        if status is not TenantStatus.PROVISIONING and self.activated_at is None:", "        if False:"),
 ("tenant: epoch may be 0", M+"tenant.py", '_whole_number("epoch", self.epoch, 1)', '_whole_number("epoch", self.epoch, 0)'),
 ("tenant: hash key version 2 allowed", M+"tenant.py", "HASH_KEY_VERSIONS: Final = frozenset({0, 1})", "HASH_KEY_VERSIONS: Final = frozenset({0, 1, 2})"),
 ("tenant: ODS lower case allowed", M+"tenant.py", 'ODS_PATTERN: Final = re.compile(r"[A-Z0-9]{3,8}")', 'ODS_PATTERN: Final = re.compile(r"[A-Za-z0-9]{3,8}")'),
 ("tenant: reference may hold braces", M+"tenant.py", 'REFERENCE_PATTERN: Final = re.compile(r"[A-Za-z0-9 ._:/-]+")', 'REFERENCE_PATTERN: Final = re.compile(r"[A-Za-z0-9 ._:/{}-]+")'),
 ("tenant: contact skips the privacy guard", M+"tenant.py", "        or find_patient_data(value)\n    ):\n        raise ValidationFailed(name, \"must be plain text of the right length\")", "    ):\n        raise ValidationFailed(name, \"must be plain text of the right length\")"),
 ("tenant: contact allows braces", M+"tenant.py", 'CONTACT_FORBIDDEN_CHARACTERS: Final = frozenset("{}<>")', 'CONTACT_FORBIDDEN_CHARACTERS: Final = frozenset("<>")'),
 ("tenant: phone kind takes an email", M+"tenant.py", "pattern = PHONE_PATTERN if self.kind in _PHONE_KINDS else EMAIL_PATTERN", "pattern = EMAIL_PATTERN"),
 ("tenant: a current config needs no effective_from", M+"tenant.py", "        if self.status is ConfigStatus.CURRENT and self.effective_from is None:", "        if False:"),
 ("tenant: config values left writable", M+"tenant.py", 'object.__setattr__(self, "values", MappingProxyType(validate_settings(self.values)))', 'object.__setattr__(self, "values", validate_settings(self.values))'),
 ("tenant: config skips settings validation", M+"tenant.py", 'MappingProxyType(validate_settings(self.values))', 'MappingProxyType(dict(self.values))'),
 ("tenant: wording needs only one key", M+"tenant.py", "        if not all(key in self.values for key in WORDING_KEYS):", "        if not any(key in self.values for key in WORDING_KEYS):"),
 # policy
 ("policy: reply window maximum 61", M+"tenant_policy.py", "REPLY_WINDOW_MAX: Final = timedelta(minutes=60)", "REPLY_WINDOW_MAX: Final = timedelta(minutes=61)"),
 ("policy: phone task minimum 29", M+"tenant_policy.py", "PHONE_TASK_AFTER_MIN: Final = timedelta(minutes=30)", "PHONE_TASK_AFTER_MIN: Final = timedelta(minutes=29)"),
 ("policy: pressure high maximum 101", M+"tenant_policy.py", "PRESSURE_HIGH_MAX: Final = 100", "PRESSURE_HIGH_MAX: Final = 101"),
 ("policy: confirms default 3", M+"tenant_policy.py", "MAX_CONFIRMS_DEFAULT: Final = 2", "MAX_CONFIRMS_DEFAULT: Final = 3"),
 ("policy: range check < for <=", M+"tenant_policy.py", "    if not low <= value <= high:", "    if not low < value <= high:"),
 ("policy: range check skipped", M+"tenant_policy.py", "    if field.name in FIELD_BOUNDS:\n        _check_range(field, value)", "    pass"),
 ("policy: reply <= reminder skipped", M+"tenant_policy.py", "        if self.reply_window > self.reminder_after:", "        if False:"),
 ("policy: reminder < phone task skipped", M+"tenant_policy.py", "        if self.reminder_after >= self.phone_task_after:", "        if False:"),
 ("policy: reminder < phone task not strict", M+"tenant_policy.py", "        if self.reminder_after >= self.phone_task_after:", "        if self.reminder_after > self.phone_task_after:"),
 ("policy: phone task < escalate skipped", M+"tenant_policy.py", "        if self.phone_task_after >= self.escalate_after:", "        if False:"),
 ("policy: watch < high skipped", M+"tenant_policy.py", "        if self.pressure_watch_from >= self.pressure_high_from:", "        if False:"),
 ("policy: booking prompt < reply skipped", M+"tenant_policy.py", "        if self.booking_phone_prompt_after >= self.booking_reply_window:", "        if False:"),
 ("policy: a bool is an int", M+"tenant_policy.py", "def _check_count(field: PolicyField, value: object) -> None:\n    if type(value) is not int:", "def _check_count(field: PolicyField, value: object) -> None:\n    if not isinstance(value, int):"),
 ("policy: whole-unit check skipped", M+"tenant_policy.py", "    if value % _DURATION_UNITS[field.unit]:", "    if False:"),
 ("policy: duration type by isinstance", M+"tenant_policy.py", "    if type(value) is not timedelta:", "    if not isinstance(value, timedelta | int):"),
 ("policy: alert hours choice skipped", M+"tenant_policy.py", "    if value not in ALERT_NOT_UPDATED_CHOICES:", "    if False:"),
 ("policy: empty alert set allowed", M+"tenant_policy.py", "    if not value or any(type(member) is not AlertKind for member in value):", "    if any(type(member) is not AlertKind for member in value):"),
 ("policy: require_policy takes a subclass", M+"tenant_policy.py", "    if type(value) is not TenantPolicy:", "    if not isinstance(value, TenantPolicy):"),
 ("policy: require_policy takes anything", M+"tenant_policy.py", "    if type(value) is not TenantPolicy:", "    if False:"),
 # settings
 ("settings: unknown key accepted", R+"tenant_settings.py", "    if spec is None:", "    if False:"),
 ("settings: approver may be the author", R+"tenant_settings.py", "    if required == CLINICAL_APPROVALS_REQUIRED and author_ref in approver_refs:", "    if False:"),
 ("settings: a clinical change needs one", R+"tenant_settings.py", "        return CLINICAL_APPROVALS_REQUIRED\n    return", "        return ORDINARY_APPROVALS_REQUIRED\n    return"),
 ("settings: approvers need not be distinct", R+"tenant_settings.py", " or len(set(approver_refs)) != len(\n        approver_refs\n    ):", ":"),
 ("settings: approvers need not be named", R+"tenant_settings.py", "    if not all(is_named_ref(ref) for ref in approver_refs)", "    if False and not all(is_named_ref(ref) for ref in approver_refs)"),
 ("settings: approver count ignored", R+"tenant_settings.py", "        or len(approver_refs) < required\n", "        or False\n"),
 ("settings: text trailing space allowed", R+"tenant_settings.py", '    if value.endswith(" ") or "  " in value or', "    if \"  \" in value or"),
 ("settings: text double space allowed", R+"tenant_settings.py", '    if value.endswith(" ") or "  " in value or', '    if value.endswith(" ") or'),
 ("settings: text pattern skipped", R+"tenant_settings.py", " or TEXT_PATTERN.fullmatch(value) is None:", ":"),
 ("settings: text skips the privacy guard", R+"tenant_settings.py", "    if find_patient_data(value):", "    if False:"),
 ("settings: text length not limited", R+"tenant_settings.py", "or not TEXT_MIN_LENGTH <= len(value) <= maximum:", "or not TEXT_MIN_LENGTH <= len(value):"),
 ("settings: int bound < for <=", R+"tenant_settings.py", "    elif not cast(int, spec.minimum) <= value <= cast(int, spec.maximum):", "    elif not cast(int, spec.minimum) < value <= cast(int, spec.maximum):"),
 ("settings: int is isinstance", R+"tenant_settings.py", "def _check_int(spec: SettingSpec, value: object) -> int:\n    if type(value) is not int:", "def _check_int(spec: SettingSpec, value: object) -> int:\n    if not isinstance(value, int):"),
 ("settings: aware time allowed", R+"tenant_settings.py", "    if type(value) is not time or value.tzinfo is not None:", "    if type(value) is not time:"),
 ("settings: seconds allowed", R+"tenant_settings.py", "    if value.second or value.microsecond:\n        raise ValidationFailed(spec.key, WRONG_TYPE_MESSAGE)", "    if False:\n        raise ValidationFailed(spec.key, WRONG_TYPE_MESSAGE)"),
 ("settings: unknown alert code allowed", R+"tenant_settings.py", "or code not in allowed for code in value", "for code in value"),
 ("settings: wording key refused by policy_from_settings", R+"tenant_settings.py", "        if spec.policy_field is not None:", "        if True:"),
 # lifecycle
 ("lifecycle: provisioning -> suspended allowed", R+"tenant_lifecycle.py", "_T.PROVISIONING: frozenset({_T.ACTIVE}),", "_T.PROVISIONING: frozenset({_T.ACTIVE, _T.SUSPENDED}),"),
 ("lifecycle: purged may reopen", R+"tenant_lifecycle.py", "_T.PURGED: frozenset(),", "_T.PURGED: frozenset({_T.ACTIVE}),"),
 ("lifecycle: offboarding -> active removed", R+"tenant_lifecycle.py", "_T.OFFBOARDING: frozenset({_T.OFFBOARDED, _T.ACTIVE}),", "_T.OFFBOARDING: frozenset({_T.OFFBOARDED}),"),
 ("lifecycle: active -> offboarded allowed", R+"tenant_lifecycle.py", "_T.ACTIVE: frozenset({_T.SUSPENDED, _T.OFFBOARDING}),", "_T.ACTIVE: frozenset({_T.SUSPENDED, _T.OFFBOARDING, _T.OFFBOARDED}),"),
 ("lifecycle: status checked by isinstance on str", R+"tenant_lifecycle.py", "    if type(value) is not TenantStatus:", "    if not isinstance(value, str):"),
 ("lifecycle: a current config may go back to draft", R+"tenant_lifecycle.py", "_C.CURRENT: frozenset({_C.SUPERSEDED}),", "_C.CURRENT: frozenset({_C.SUPERSEDED, _C.DRAFT}),"),
 ("lifecycle: notice is 29 days", R+"tenant_lifecycle.py", "OFFBOARDING_NOTICE: Final = timedelta(days=30)", "OFFBOARDING_NOTICE: Final = timedelta(days=29)"),
 ("lifecycle: notice boundary exclusive", R+"tenant_lifecycle.py", "    if waived is not True and instant < offboarding_may_complete_at(checked):", "    if waived is not True and instant <= offboarding_may_complete_at(checked):"),
 ("lifecycle: notice ignored", R+"tenant_lifecycle.py", "    if waived is not True and instant < offboarding_may_complete_at(checked):", "    if False:"),
 ("lifecycle: truthy waiver accepted", R+"tenant_lifecycle.py", "    if waived is not True and instant", "    if not waived and instant"),
 ("lifecycle: quarantine is 89 days", R+"tenant_lifecycle.py", "NUMBER_QUARANTINE: Final = timedelta(days=90)", "NUMBER_QUARANTINE: Final = timedelta(days=89)"),
 ("lifecycle: quarantine end exclusive", R+"tenant_lifecycle.py", "    return instant >= end", "    return instant > end"),
 ("lifecycle: no quarantine end means assignable", R+"tenant_lifecycle.py", "    if status is NumberStatus.ACTIVE or end is None:", "    if status is NumberStatus.ACTIVE:\n        return False\n    if end is None:\n        return True\n    if False:"),
 ("lifecycle: an active number assignable", R+"tenant_lifecycle.py", "    if status is NumberStatus.ACTIVE or end is None:", "    if end is None:"),
 ("lifecycle: hold boundary inclusive", R+"tenant_lifecycle.py", "    if hold is not None and hold > instant:\n        raise NotAllowed(HOLD_MESSAGE)", "    if hold is not None and hold >= instant:\n        raise NotAllowed(HOLD_MESSAGE)"),
 ("lifecycle: hold ignored by purge", R+"tenant_lifecycle.py", "    if hold is not None and hold > instant:\n        raise NotAllowed(HOLD_MESSAGE)", "    if False:\n        raise NotAllowed(HOLD_MESSAGE)"),
 ("lifecycle: suspend does not bump the epoch", R+"tenant_lifecycle.py", "        suspended_at=instant,\n        epoch=checked.epoch + 1,", "        suspended_at=instant,\n        epoch=checked.epoch,"),
 ("lifecycle: resume does not bump the epoch", R+"tenant_lifecycle.py", "        suspended_at=None,\n        epoch=checked.epoch + 1,\n    )\n\n\ndef start_offboarding", "        suspended_at=None,\n        epoch=checked.epoch,\n    )\n\n\ndef start_offboarding"),
 ("lifecycle: resume applies to offboarding too", R+"tenant_lifecycle.py", "_move(checked, _T.ACTIVE, frozenset({_T.SUSPENDED}))", "_move(checked, _T.ACTIVE, frozenset({_T.SUSPENDED, _T.OFFBOARDING}))"),
 ("lifecycle: reopen keeps the offboarding times", R+"tenant_lifecycle.py", "        offboarding_started_at=None,\n        offboarded_at=None,\n        epoch", "        epoch"),
 ("lifecycle: activation skips the facts", R+"tenant_lifecycle.py", "    if blockers:\n        raise NotAllowed(\"Activation", "    if False:\n        raise NotAllowed(\"Activation"),
 ("lifecycle: two operators become one", R+"tenant_lifecycle.py", "PURGE_OPERATORS_REQUIRED: Final = 2", "PURGE_OPERATORS_REQUIRED: Final = 1"),
 ("lifecycle: operators need not be distinct", R+"tenant_lifecycle.py", "    return len({ref for ref in refs if is_named_ref(ref)})", "    return len([ref for ref in refs if is_named_ref(ref)])"),
 ("lifecycle: a typed id is not compared", R+"tenant_lifecycle.py", "    if type(typed_slug) is not str or typed_slug != checked.id:", "    if type(typed_slug) is not str:"),
 ("lifecycle: purge blocker order changed", R+"tenant_lifecycle.py", "    if checked.status is not _T.OFFBOARDED:\n        blockers.append(BLOCKER_NOT_OFFBOARDED)\n", "    pass\n"),
 ("lifecycle: config approved by truthiness", R+"tenant_lifecycle.py", "    if facts.config_approved is not True:", "    if not facts.config_approved:"),
 ("lifecycle: first admin by truthiness", R+"tenant_lifecycle.py", "    if facts.first_admin_invited is not True:", "    if not facts.first_admin_invited:"),
 ("lifecycle: zone any text", R+"tenant_lifecycle.py", "    if type(facts.time_zone) is not str or facts.time_zone not in ALLOWED_TIME_ZONES:", "    if type(facts.time_zone) is not str:"),
 ("lifecycle: a flag counts as a number", R+"tenant_lifecycle.py", "    return type(count) is int and count >= 1", "    return isinstance(count, int) and count >= 1"),
 ("lifecycle: email checked only when true", R+"tenant_lifecycle.py", "    if facts.email_in_use is not False and facts.email_sender_verified is not True:", "    if facts.email_in_use is True and facts.email_sender_verified is not True:"),
 ("lifecycle: email always checked", R+"tenant_lifecycle.py", "    if facts.email_in_use is not False and facts.email_sender_verified is not True:", "    if facts.email_sender_verified is not True:"),
 ("lifecycle: districts always required", R+"tenant_lifecycle.py", "    if facts.registers_services is not False and facts.area_districts_set is not True:", "    if facts.area_districts_set is not True:"),
 ("lifecycle: agreement always required", R+"tenant_lifecycle.py", "    if facts.network_member is not False and facts.agreement_accepted is not True:", "    if facts.agreement_accepted is not True:"),
 ("lifecycle: contacts need either", R+"tenant_lifecycle.py", "    if not {ContactKind.COORDINATION_PHONE, ContactKind.CLINICAL_SAFETY_OFFICER} <= contacts:", "    if not ({ContactKind.COORDINATION_PHONE, ContactKind.CLINICAL_SAFETY_OFFICER} & contacts):"),
 ("lifecycle: contacts matched by value", R+"tenant_lifecycle.py", "    return frozenset(value for value in values if type(value) is enum_type)", "    return frozenset(enum_type(value) for value in values if isinstance(value, str) and value in [m.value for m in enum_type])"),
 ("lifecycle: retention one short passes", R+"tenant_lifecycle.py", "    if not retention >= REQUIRED_RETENTION_CLASSES:", "    if len(retention) < len(REQUIRED_RETENTION_CLASSES) - 1:"),
 ("lifecycle: references need two of three", R+"tenant_lifecycle.py", "    if not _plain_strings(facts.references_recorded) >= REQUIRED_REFERENCES:", "    if len(_plain_strings(facts.references_recorded) & REQUIRED_REFERENCES) < 2:"),
 ("lifecycle: wording by truthiness", R+"tenant_lifecycle.py", "    if facts.wording_complete is not True:", "    if not facts.wording_complete:"),
 ("lifecycle: Tenant type not checked", R+"tenant_lifecycle.py", "    if type(value) is not Tenant:", "    if False:"),
 ("lifecycle: naive instants accepted", R+"tenant_lifecycle.py", "    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:", "    if not isinstance(value, datetime):"),

 # second pass: the mutants that the first pass mis-reported, replaced or added
 ("policy: reply < reminder (not strict-equal)", M+"tenant_policy.py", "        if self.reply_window > self.reminder_after:", "        if self.reply_window >= self.reminder_after:"),
 ("settings: restoring a default is not a change", R+"tenant_settings.py", "    return frozenset(key for key in {*old, *new} if old.get(key, _ABSENT) != new.get(key, _ABSENT))", "    return frozenset(key for key in {*old, *new} if key in old and key in new and old[key] != new[key])"),
 ("settings: policy_from_settings ignores the overrides", R+"tenant_settings.py", "            overrides[spec.policy_field] = from_setting_value(POLICY_FIELD_BY_KEY[key], checked)", "            pass"),
 ("policy: an aware time of day is accepted", M+"tenant_policy.py", "    if type(value) is not time or value.tzinfo is not None:", "    if type(value) is not time:"),
 ("policy: a time of day may be any text", M+"tenant_policy.py", "    if type(value) is not time or value.tzinfo is not None:", "    if False:"),
 ("policy: a choice may be a bool", M+"tenant_policy.py", "def _check_choice(field: PolicyField, value: object) -> None:\n    if type(value) is not int:", "def _check_choice(field: PolicyField, value: object) -> None:\n    if not isinstance(value, int):"),
]

only = sys.argv[1:] 
results = []
for name, f, old, new in MUTANTS:
    if only and not any(o in name for o in only):
        continue
    path = ROOT / SRC / f
    text = path.read_text()
    if text.count(old) != 1:
        results.append((name, f"NOT APPLIED (count {text.count(old)})"))
        print(results[-1], flush=True)
        continue
    path.write_text(text.replace(old, new))
    try:
        done = subprocess.run(
            ["uv", "run", "pytest", *TESTS, "-x", "-q", "--no-header", "-p", "no:cacheprovider", "-W", "ignore"],
            cwd=ROOT, capture_output=True, text=True, timeout=600,
        )
        failed = [l for l in done.stdout.splitlines() if l.startswith(("FAILED", "ERROR"))]
        if done.returncode == 0:
            results.append((name, "SURVIVED"))
        else:
            results.append((name, failed[0][:140] if failed else "FAILED (collection or import)"))
    finally:
        subprocess.run(["git", "checkout", "--", str(path)], cwd=ROOT, check=True)
    print(results[-1], flush=True)
print("DONE", sum(1 for _, r in results if r == "SURVIVED"), "survived of", len(results))
