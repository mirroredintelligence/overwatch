// The shapes of ids and codes the network administration screens and routes share. No import: this file is
// safe for the browser as well as the server (the screens check a code before they send it, and the routes
// check it again).

/** A network id as the back end makes it: `net-` and lower-case letters, digits and hyphens, 31 characters at most. */
export const NETWORK_ID = /^net-[a-z0-9][a-z0-9-]{1,26}$/;
/** A registry record's id (a membership, a grant, a listing): `RECORD_ID_PATTERN` of the back end. */
export const RECORD_ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;
/** An organisation code: the back end's tenant id shape (`TENANT_ID_PATTERN`). */
export const ORGANISATION_CODE = /^[a-z0-9][a-z0-9-]{1,30}$/;
/** An agreement's reference in the owner's own document system (`AGREEMENT_REFERENCE_PATTERN`). */
export const AGREEMENT_REFERENCE = /^[A-Za-z0-9][A-Za-z0-9._/-]{0,63}$/;
