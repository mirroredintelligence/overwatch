"""The network services of the API process, wired (TEN-059, TEN-079, TEN-082, KI-587, KI-852).

`app.state.network_services` (the read routes, the live stream, the lead's and executive's views)
and `app.state.network_admin` (the members, the agreement, the grants and the listings) are built
here from the container, the real network registry and the two kinds of unit of work, as the worker
builds its own half. Nothing here holds a rule and nothing binds a tenant or a network: each use
case takes the scope from the request's actor.

The wall screen reader is the container's own unit of work (`UowScreens`), so a wall's board choice
is judged against the bound tenant's screens (TEN-072).
"""

from overwatch.adapters.inbound.fhir_rest.routes_network import NetworkServices
from overwatch.adapters.inbound.fhir_rest.routes_network_admin import NetworkAdminServices
from overwatch.adapters.outbound.graph_store.network_registry import Neo4jNetworkRegistry
from overwatch.adapters.outbound.graph_store.unit_of_work import neo4j_network_uow_factory
from overwatch.application.network_access import NetworkAccess
from overwatch.application.use_cases.filter_network_options import FilterNetworkOptions
from overwatch.application.use_cases.grants import (
    ApproveGrant,
    DeclineGrant,
    EndGrant,
    ProposeGrant,
    QueryGrants,
    ReviseGrant,
)
from overwatch.application.use_cases.listing_admission import (
    DecideListing,
    QueryListings,
    RequestListing,
)
from overwatch.application.use_cases.member_sharing import QueryMemberSharing
from overwatch.application.use_cases.membership import (
    AcceptMembership,
    InviteMember,
    LeaveNetwork,
    RemoveMember,
)
from overwatch.application.use_cases.network_admin import (
    GovernanceRecorder,
    QueryNetworkAdmin,
    RecordAgreement,
    RegistryNetworkOwnership,
)
from overwatch.application.use_cases.network_board_projector import NetworkBoardProjector
from overwatch.application.use_cases.network_leave import EndProjections
from overwatch.application.use_cases.network_samples import RecordNetworkSample
from overwatch.application.use_cases.network_week_summary import GetNetworkWeekSummary
from overwatch.application.use_cases.query_network_board import QueryNetworkBoard
from overwatch.application.use_cases.query_network_directory import (
    QueryNetworkCriteria,
    QueryNetworkDirectory,
)
from overwatch.application.use_cases.wall_board_scope import UowScreens
from overwatch.bootstrap.container import Container


def build_network_services(container: Container) -> NetworkServices:
    """The read services of `/network`: the board projector (which caches under the network's own
    key and samples the board for the week summary), the directory, the criteria, the week and the
    advisor's options (the case is read in the advisor's own tenant, the rows in the network)."""
    registry = Neo4jNetworkRegistry(container.neo4j)
    access = NetworkAccess(registry, container.tenants, UowScreens(container.uow_factory))
    read_only = neo4j_network_uow_factory(container.neo4j, clock=container.clock, read_only=True)
    projector = NetworkBoardProjector(
        QueryNetworkBoard(read_only, access, container.clock),
        access,
        container.cache,
        container.clock,
        RecordNetworkSample(neo4j_network_uow_factory(container.neo4j, clock=container.clock)),
    )
    return NetworkServices(
        access=access,
        projector=projector,
        directory=QueryNetworkDirectory(read_only, access, container.clock),
        criteria=QueryNetworkCriteria(read_only, access, container.clock),
        weeks=GetNetworkWeekSummary(read_only, access),
        options=FilterNetworkOptions(
            container.uow_factory,
            read_only,
            access,
            container.clock,
            container.postcodes,
            container.travel,
        ),
    )


def build_network_admin_services(container: Container) -> NetworkAdminServices:
    """The administration services of `/network-admin`, on the real registry. Every change is
    recorded in the audit chain of the tenant that made it and in the network's own."""
    registry = Neo4jNetworkRegistry(container.neo4j)
    clock = container.clock
    ids = container.ids
    tenants = container.tenants
    network_units = neo4j_network_uow_factory(container.neo4j, clock=clock)
    read_only = neo4j_network_uow_factory(container.neo4j, clock=clock, read_only=True)
    recorder = GovernanceRecorder(container.uow_factory, network_units, ids, clock)
    ends = EndProjections(network_units, registry, clock)
    return NetworkAdminServices(
        query=QueryNetworkAdmin(registry, tenants, read_only),
        invite=InviteMember(registry, tenants, recorder, ids, clock),
        accept=AcceptMembership(registry, recorder, clock),
        leave=LeaveNetwork(registry, ends, recorder, clock),
        remove=RemoveMember(registry, ends, recorder, clock),
        agreement=RecordAgreement(registry, recorder, clock),
        grants=QueryGrants(registry, tenants, clock),
        propose=ProposeGrant(registry, recorder, ids, clock),
        approve=ApproveGrant(registry, recorder, clock),
        decline=DeclineGrant(registry, recorder, clock),
        end=EndGrant(registry, ends, recorder, clock),
        revise=ReviseGrant(registry, recorder, ids, clock),
        listings=QueryListings(registry, tenants),
        request_listing=RequestListing(registry, container.uow_factory, recorder, ids, clock),
        decide_listing=DecideListing(registry, recorder, clock),
        sharing=QueryMemberSharing(registry, read_only),
    )


def build_network_ownership(container: Container) -> RegistryNetworkOwnership:
    """The token exchange's one question about networks: does the host's tenant own an active
    one (TEN-080, DEC-1260)? Answered from the registry on each sign-in."""
    return RegistryNetworkOwnership(Neo4jNetworkRegistry(container.neo4j))
