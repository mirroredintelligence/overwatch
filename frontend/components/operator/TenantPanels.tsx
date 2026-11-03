// The steps of an organisation's "Go live" page (TEN-083) now live one per file under ./funnel. This file only
// re-exports them, so the imports of the page keep working.

export type { Detail, PanelProps } from './funnel/shared';
export { StepSection } from './funnel/shared';
export { OrganisationStep } from './funnel/OrganisationStep';
export { SignInStep } from './funnel/SignInStep';
export { InviteStep } from './funnel/InviteStep';
export { TeamStep } from './funnel/TeamStep';
export { RolesStep } from './funnel/RolesStep';
export { ReachStep } from './funnel/ReachStep';
export { AgreementsStep } from './funnel/AgreementsStep';
