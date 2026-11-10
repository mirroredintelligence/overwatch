import registryJson from './registry.json';

// Who may open which assistant intent (WS-REG). The data is registry.json, an exact copy of
// docs/design/workspaces/registry.json. Pure functions, no React.

export type Persona = 'advisor' | 'overview' | 'manager' | 'reporter' | 'admin' | 'platform' | 'display';
export type Flag = 'clinicalSignOff' | 'peopleAndPhones' | 'planningAndAlerts' | 'ownCriteria' | 'auditReplay';
export type DataClass = 'patient' | 'aggregate' | 'none';
export type Intent = {
  id: string; label: string; kind: 'view' | 'action' | 'nav'; phase: number;
  personas: Persona[]; requires: Flag | null; sessionRoles?: string[]; dataClass: DataClass;
  route: string; params: Record<string, string>; layout: string | null;
};
export type Identity = { persona: Persona; flags: readonly Flag[]; workspace: boolean };

type Registry = {
  livePhase: number;
  flags: Flag[];
  personas: Record<Persona, { label: string; dataClass: DataClass }>;
  adapter: { sessionRole: string; persona: Persona; flags: Flag[]; workspace: boolean }[];
  layouts: Record<string, { widgets: string[] }>;
  intents: Intent[];
};

const registry = registryJson as unknown as Registry;

export const LIVE_PHASE: number = registry.livePhase;

export function identityOf(sessionRole: string): Identity | null {
  const row = registry.adapter.find((entry) => entry.sessionRole === sessionRole);
  if (!row) return null;
  return { persona: row.persona, flags: [...row.flags], workspace: row.workspace };
}

export function intentById(id: string): Intent | undefined {
  return registry.intents.find((intent) => intent.id === id);
}

// An intent is offered only when every condition holds (WS-REG). The registry may offer less than
// the route guard allows, never more.
function isOffered(intent: Intent, sessionRole: string, identity: Identity, phase: number): boolean {
  return intent.phase <= phase
    && intent.personas.includes(identity.persona)
    && (intent.requires === null || identity.flags.includes(intent.requires))
    && (intent.sessionRoles === undefined || intent.sessionRoles.includes(sessionRole))
    && (intent.kind === 'nav' || identity.workspace);
}

export function intentsFor(sessionRole: string, opts?: { phase?: number }): Intent[] {
  const identity = identityOf(sessionRole);
  if (!identity) return [];
  const phase = opts?.phase ?? LIVE_PHASE;
  return registry.intents.filter((intent) => isOffered(intent, sessionRole, identity, phase));
}

export function canOpen(sessionRole: string, intentId: string, opts?: { phase?: number }): boolean {
  return intentsFor(sessionRole, opts).some((intent) => intent.id === intentId);
}

export function routeOf(intent: Intent, vars?: { id?: string }): string {
  if (!intent.route.includes('[id]')) return intent.route;
  const id = vars?.id;
  if (!id) throw new Error('routeOf: missing id');
  return intent.route.replace('[id]', () => id);
}
