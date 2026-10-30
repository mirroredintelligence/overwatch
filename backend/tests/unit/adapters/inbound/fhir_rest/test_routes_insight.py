"""The insight routes (W9F): `GET /support/insight/{tab}` and `POST /telemetry/ui`. The role
boundary (the support role only reads a tab; every signed-in role but the platform operator may
send its own browser's events), the refusals before any read, and the JSON shapes the console
reads. The stored answers and the tenant boundary are in tests/integration/.
"""

import pytest
from diucs.adapters.inbound.fhir_rest.routes_insight import (
    TABS,
    friction_json,
    funnels_json,
    paths_json,
    performance_json,
    releases_json,
)
from diucs.application.use_cases.browser_insight import ReleasesView

from diucs.domain.codes import Role
from diucs.domain.rules.insight_views import (
    FrictionTable,
    FrictionView,
    FunnelView,
    PathsView,
    PerformanceView,
    PipelineView,
    ReleaseCompareView,
    ReleaseMeasureView,
    RouteUse,
    SlowView,
    SplitView,
    StepView,
    VitalView,
)
from tests.support.route_unit import EDGE_REFUSED, assert_role_matrix, bearer, route_client

READERS = frozenset({Role.SUPPORT})
SENDERS = frozenset(role for role in Role if role not in EDGE_REFUSED)
EVENT = {
    "name": "ui.click",
    "attributes": {
        "session.id": "a1b2c3d4e5f60718",
        "release": "1.4.2",
        "device.type": "desktop",
        "element.id": "ADV-X-BTN",
    },
}


@pytest.mark.parametrize("tab", TABS)
async def test_a_tab_is_for_the_support_role_only(tab: str) -> None:
    async with route_client() as client:
        await assert_role_matrix(client, "GET", f"/support/insight/{tab}?range=7d", READERS)


async def test_events_may_be_sent_by_every_role_but_the_platform_operator() -> None:
    async with route_client() as client:
        await assert_role_matrix(client, "POST", "/telemetry/ui", SENDERS, body={"events": [EVENT]})


@pytest.mark.parametrize(
    ("path", "field"),
    [
        ("/support/insight/funnels?range=1y", "range"),
        ("/support/insight/funnels?range=7d&device=watch", "device"),
        ("/support/insight/sessions?range=7d", "tab"),
    ],
)
async def test_a_range_device_or_tab_that_is_not_listed_is_a_400_that_names_it(
    path: str, field: str
) -> None:
    async with route_client() as client:
        response = await client.get(path, headers=bearer(Role.SUPPORT))

    assert response.status_code == 400
    assert field in response.text


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"events": "x"},
        {"events": [{"attributes": {}}]},
        {"events": [{"name": "ui.click", "attributes": {"a": [1]}}]},
        {"events": [{"name": "ui.click", "attributes": {"a": {"b": 1}}}]},
    ],
)
async def test_a_body_that_is_not_a_list_of_named_events_is_a_400(body: dict[str, object]) -> None:
    async with route_client() as client:
        response = await client.post("/telemetry/ui", json=body, headers=bearer(Role.ADVISOR))

    assert response.status_code == 400


async def test_a_batch_over_fifty_events_is_a_400_before_any_read() -> None:
    async with route_client() as client:
        response = await client.post(
            "/telemetry/ui", json={"events": [EVENT] * 51}, headers=bearer(Role.ADVISOR)
        )

    assert response.status_code == 400


async def test_an_empty_batch_is_counted_as_nothing_without_a_read() -> None:
    async with route_client() as client:
        response = await client.post(
            "/telemetry/ui", json={"events": []}, headers=bearer(Role.ADVISOR)
        )

    assert response.status_code == 200
    assert response.json() == {"accepted": 0, "dropped": 0}


async def test_nothing_is_cached() -> None:
    async with route_client() as client:
        response = await client.post(
            "/telemetry/ui", json={"events": []}, headers=bearer(Role.ADVISOR)
        )

    assert response.headers["cache-control"] == "no-store"


# ---- the shapes ---------------------------------------------------------------------------------


def test_funnels_are_steps_with_a_share_and_the_split_by_channel() -> None:
    body = funnels_json(
        [
            FunnelView(
                "reporter-set-up",
                "Reporter set-up",
                (
                    StepView("Set-up opened", 40, 100, False),
                    StepView("PIN screen viewed", None, None, True),
                ),
                (SplitView("browser", 70, False), SplitView("app", None, True)),
            )
        ],
        "7d",
        None,
    )

    assert body == {
        "tab": "funnels",
        "range": "7d",
        "device": None,
        "funnels": [
            {
                "name": "reporter-set-up",
                "label": "Reporter set-up",
                "steps": [
                    {"name": "Set-up opened", "count": 40, "pct": 100, "suppressed": False},
                    {"name": "PIN screen viewed", "count": None, "pct": None, "suppressed": True},
                ],
                "split": [
                    {"channel": "browser", "pct": 70, "suppressed": False},
                    {"channel": "app", "pct": None, "suppressed": True},
                ],
            }
        ],
    }


def test_paths_say_the_unused_controls_are_not_measured_rather_than_none() -> None:
    body = paths_json(
        PathsView(
            (RouteUse("/advisor/board", 120, False), RouteUse("/help", None, True)),
            (RouteUse("/advisor/board", 12, False),),
        ),
        "30d",
        "phone",
    )

    assert body["mostCommon"] == [
        {"route": "/advisor/board", "sessions": 120, "medianSeconds": None, "suppressed": False},
        {"route": "/help", "sessions": None, "medianSeconds": None, "suppressed": True},
    ]
    assert body["uTurns"] == [
        {"route": "/advisor/board", "sessions": 12, "medianSeconds": None, "suppressed": False}
    ]
    assert body["unused"] is None
    assert body["device"] == "phone"


def test_friction_rows_carry_the_review_flag_and_the_count_of_hidden_groups() -> None:
    body = friction_json(
        FrictionTable(
            (
                FrictionView("ADV-OPT-REQUEST-BTN", "rage", None, 41, 312, 41 / 312, True),
                FrictionView("PAGE", "u-turn", "/advisor/board", 15, None, None, False),
            ),
            2,
        ),
        "7d",
        None,
    )

    assert body["rows"] == [
        {
            "elementId": "ADV-OPT-REQUEST-BTN",
            "kind": "rage",
            "route": None,
            "events": 41,
            "interactions": 312,
            "rate": pytest.approx(41 / 312),
            "review": True,
        },
        {
            "elementId": "PAGE",
            "kind": "u-turn",
            "route": "/advisor/board",
            "events": 15,
            "interactions": None,
            "rate": None,
            "review": False,
        },
    ]
    assert body["suppressedGroups"] == 2


def test_performance_names_each_vital_by_its_label_and_leaves_prompt_to_board_unmeasured() -> None:
    body = performance_json(
        PerformanceView(
            (
                VitalView("lcp", "Largest contentful paint", "phone", 2500.0, 2500.0, "ms", False),
                VitalView("cls", "Cumulative layout shift", "phone", None, 0.1, "score", True),
            ),
            (SlowView("/advisor/board", 4000.0),),
            (SlowView("Q-BOARD", 91.0),),
        ),
        "7d",
        None,
    )

    assert body["vitals"] == [
        {
            "measure": "Largest contentful paint",
            "metric": "lcp",
            "device": "phone",
            "p75": 2500.0,
            "budget": 2500.0,
            "unit": "ms",
            "suppressed": False,
        },
        {
            "measure": "Cumulative layout shift",
            "metric": "cls",
            "device": "phone",
            "p75": None,
            "budget": 0.1,
            "unit": "score",
            "suppressed": True,
        },
    ]
    assert body["slowestRoutes"] == [{"name": "/advisor/board", "p95Ms": 4000.0}]
    assert body["slowestQueries"] == [{"name": "Q-BOARD", "p95Ms": 91.0}]
    assert body["promptToBoard"] is None


def test_releases_carry_the_comparison_and_the_pipeline() -> None:
    body = releases_json(
        ReleasesView(
            ReleaseCompareView(
                "1.4.2",
                "1.4.3",
                (ReleaseMeasureView("Largest contentful paint, p75", 2000.0, 3000.0, "ms", True),),
            ),
            (PipelineView("messages.outbound", 2, 1, 90),),
        ),
        "7d",
    )

    assert body == {
        "tab": "releases",
        "range": "7d",
        "compare": {"old": "1.4.2", "new": "1.4.3"},
        "measures": [
            {
                "measure": "Largest contentful paint, p75",
                "old": 2000.0,
                "new": 3000.0,
                "unit": "ms",
                "review": True,
            }
        ],
        "pipeline": [
            {"name": "messages.outbound", "active": 2, "deadLettered": 1, "oldestSeconds": 90}
        ],
    }


def test_no_comparison_is_null_with_no_measures_and_the_pipeline_still_shows() -> None:
    body = releases_json(ReleasesView(None, (PipelineView("other", 0, 0, None),)), "24h")

    assert body["compare"] is None
    assert body["measures"] == []
    assert body["pipeline"] == [
        {"name": "other", "active": 0, "deadLettered": 0, "oldestSeconds": None}
    ]


def test_no_shape_names_a_person_an_advisor_or_a_session() -> None:
    texts = [
        str(funnels_json([], "7d", None)),
        str(paths_json(PathsView((), ()), "7d", None)),
        str(friction_json(FrictionTable((), 0), "7d", None)),
        str(performance_json(PerformanceView((), (), ()), "7d", None)),
        str(releases_json(ReleasesView(None, ()), "7d")),
    ]
    for text in texts:
        for word in ("advisor", "person", "session", "practitioner", "user"):
            assert word not in text.lower().replace("sessions", "")
