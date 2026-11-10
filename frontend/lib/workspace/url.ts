import { intentById } from './registry';

// URL state for the workspace (WS-URL). The URL holds only where the person is, never who the
// patient is: age, postcode, need and when are never read or emitted (WS-PRIV).

export type AdvisorUrl = { view: 'find' | 'list' | 'map' | 'why'; step: 'age' | 'need'; group: string | null; order: 'travel' | 'name' };
export type OverviewUrl = { view: 'home' | 'attention' | 'area'; tab: 'pressure' | 'under'; area: string | null };

type WorkspaceOver = {
  group?: string | null;
  order?: 'travel' | 'name';
  tab?: 'pressure' | 'under';
  area?: string | null;
};

const GROUP_PATTERN = /^[a-z][a-z0-9-]{0,63}$/;
const AREA_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;

function pick<T extends string>(value: string | null, allowed: readonly T[], fallback: T): T {
  return allowed.find((item) => item === value) ?? fallback;
}

function toParams(search: string | URLSearchParams): URLSearchParams {
  return typeof search === 'string' ? new URLSearchParams(search) : search;
}

export function parseAdvisorUrl(search: string | URLSearchParams): AdvisorUrl {
  const params = toParams(search);
  const group = params.get('group');
  return {
    view: pick(params.get('view'), ['find', 'list', 'map', 'why'] as const, 'find'),
    step: pick(params.get('step'), ['age', 'need'] as const, 'age'),
    group: group !== null && GROUP_PATTERN.test(group) ? group : null,
    order: pick(params.get('order'), ['travel', 'name'] as const, 'travel'),
  };
}

export function parseOverviewUrl(search: string | URLSearchParams): OverviewUrl {
  const params = toParams(search);
  const area = params.get('area');
  return {
    view: pick(params.get('view'), ['home', 'attention', 'area'] as const, 'home'),
    tab: pick(params.get('tab'), ['pressure', 'under'] as const, 'pressure'),
    area: area !== null && AREA_PATTERN.test(area) ? area : null,
  };
}

// Builds the link for an assistant intent. Only the parameters named here are ever emitted, in
// this order; the criteria are never part of a link (WS-URL, WS-PRIV).
export function workspaceHref(intentId: string, over: WorkspaceOver = {}): string {
  const intent = intentById(intentId);
  if (!intent) throw new Error('workspaceHref: unknown intent');
  if (intentId === 'advisor.service') throw new Error('workspaceHref: advisor.service has no query form');
  if (intent.kind === 'nav') return intent.route;

  const parts: string[] = [];
  if (intent.params.mode === 'find') {
    const view = intent.params.view;
    parts.push('mode=find', `view=${view}`);
    if (view === 'find' && intent.params.step) parts.push(`step=${intent.params.step}`);
    const listing = view === 'list' || view === 'map';
    if (listing && over.group) parts.push(`group=${encodeURIComponent(over.group)}`);
    if (listing && over.order === 'name') parts.push('order=name');
  } else {
    const view = intent.params.view;
    parts.push(`view=${view}`);
    if (view === 'attention' && over.tab === 'under') parts.push('tab=under');
    if (view === 'area' && over.area) parts.push(`area=${encodeURIComponent(over.area)}`);
  }
  return parts.length > 0 ? `${intent.route}?${parts.join('&')}` : intent.route;
}
