"""Public routes (TEN-040). Stub for the red commit: no route yet."""

from fastapi import APIRouter

PUBLIC_PREFIX = "/public"
PROFILE_PATH = f"{PUBLIC_PREFIX}/tenant-profile"

router = APIRouter()
