"""Composition helpers the routes and workers share (R11).

The use cases take their collaborators through their constructors, and some have a collaborator that
only the composition root can name. This module names them in one place, so no route or worker
composes them differently:

- `submit_registration` builds `SubmitRegistration` with the write of `PersistRegistration` (U27:
  the persist is optional on the use case, and without it a submit that succeeds writes nothing).
- The review's area comes from `bootstrap/areas.py` through `Container.area_districts_for` (U28).
"""

from diucs.application.use_cases.registration_draft import SubmitRegistration
from diucs.application.use_cases.registration_submit import PersistRegistration
from diucs.bootstrap.container import Container


def submit_registration(container: Container) -> SubmitRegistration:
    """SubmitRegistration with the write of the registration's resources after a submit that
    succeeds (U27)."""
    return SubmitRegistration(
        container.uow_factory,
        container.ids,
        container.clock,
        persist=PersistRegistration(
            container.uow_factory,
            container.geocoder,
            container.terminology,
            container.ids,
            container.clock,
        ),
    )
