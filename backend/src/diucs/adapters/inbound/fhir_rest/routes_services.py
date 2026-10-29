"""HealthcareService and capacity Observation endpoints (R04). Red-commit stub: no routes yet."""

from fastapi import APIRouter

router = APIRouter(prefix="/fhir")


def register_capabilities() -> None:
    """Advertise the two resources in the CapabilityStatement. Red-commit stub."""
