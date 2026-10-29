"""The live ODS directory lookup, not yet built (I12): it will use the NHS ODS API."""

from diucs.application.ports.outbound.terminology import OdsRecord


class HttpOdsLookup:
    async def ods_lookup(self, code: str) -> OdsRecord | None:
        raise NotImplementedError(
            "live ODS lookup is not built: use the NHS ODS API (open decision)"
        )
