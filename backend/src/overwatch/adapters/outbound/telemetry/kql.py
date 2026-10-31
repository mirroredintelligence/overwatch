"""The KQL for the telemetry query port (O07). One module holds every query text.

Values never go into the text: the tenant, the session id, the trace id, the window and the search
filters are declared as query parameters and sent beside the text. The tenant is the bound one
(application.tenancy.current_tenant), filtered on `customDimensions["tenant.id"]` (DEC-130; the
tenancy audit's change to O07).

UNVERIFIED: the Application Insights table and column names below are not checked against a live
workspace. They assume the classic `customDimensions` column that the O07 prompt names, with the
standard tables AppPageViews, AppEvents, AppDependencies, AppExceptions and AppRequests. On a
workspace-based resource the same data may sit under `Properties`. Verify before the first live
run, and change the names here only.
"""

from typing import Final

# Columns: TimeGenerated, kind, name, DurationMs, status, customDimensions.
TIMELINE_QUERY: Final = """
declare query_parameters(session_id: string, tenant_id: string, start: string, end: string);
union isfuzzy=true
    (AppPageViews
        | extend kind = "page_view", name = Name, DurationMs = real(null), status = ""),
    (AppEvents
        | extend kind = tostring(customDimensions["event.kind"]), name = Name,
                 DurationMs = real(null), status = ""),
    (AppDependencies
        | extend kind = "api_call", name = Name, status = tostring(ResultCode)),
    (AppExceptions
        | extend kind = "error", name = ProblemId, DurationMs = real(null), status = "")
| where TimeGenerated between (todatetime(start) .. todatetime(end))
| where tostring(customDimensions["session.id"]) == session_id
| where tostring(customDimensions["tenant.id"]) == tenant_id
| project TimeGenerated, kind, name, DurationMs, status, customDimensions
| order by TimeGenerated asc
"""

# Columns: SpanId, ParentSpanId, SpanName, StartTime, DurationMs, Status, customDimensions.
SPANS_QUERY: Final = """
declare query_parameters(trace_id: string, tenant_id: string);
union isfuzzy=true AppRequests, AppDependencies
| where OperationId == trace_id
| where tostring(customDimensions["tenant.id"]) == tenant_id
| project SpanId = Id, ParentSpanId = ParentId, SpanName = Name, StartTime = TimeGenerated,
          DurationMs, Status = iff(Success == true, "ok", "error"), customDimensions
| order by StartTime asc
"""

# Columns: session_id, role, device, release, started, event_count, friction_count, error_count.
# An empty filter parameter means no filter on that field.
SESSIONS_QUERY: Final = """
declare query_parameters(tenant_id: string, role: string, device: string, release: string,
                         started_from: string, started_to: string, limit: string);
AppEvents
| extend session_id = tostring(customDimensions["session.id"]),
         role_value = tostring(customDimensions["role"]),
         device_value = tostring(customDimensions["device.class"]),
         release_value = tostring(customDimensions["release"]),
         event_kind = tostring(customDimensions["event.kind"])
| where tostring(customDimensions["tenant.id"]) == tenant_id
| where role == "" or role_value == role
| where device == "" or device_value == device
| where release == "" or release_value == release
| where started_from == "" or TimeGenerated >= todatetime(started_from)
| where started_to == "" or TimeGenerated <= todatetime(started_to)
| summarize started = min(TimeGenerated), role_any = any(role_value),
            device_any = any(device_value), release_any = any(release_value),
            event_count = count(), friction_count = countif(event_kind == "friction"),
            error_count = countif(event_kind == "error")
    by session_id
| order by started desc
| take toint(limit)
| project session_id, role = role_any, device = device_any, release = release_any,
          started, event_count, friction_count, error_count
"""
