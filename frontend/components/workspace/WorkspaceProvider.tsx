'use client';

import { createContext, useCallback, useContext, useReducer, useRef, useSyncExternalStore, type ReactNode } from 'react';
import type { AgeCode, NeedCode, UrgencyCode } from '@/lib/advisor/codes';
import { normalisePostcode } from '@/lib/advisor/postcode';
import { tenantStore } from '@/lib/storage/tenantStore';
import { canOpen } from '@/lib/workspace/registry';
import { renderTurn, type ChipSpec, type DialogContext } from '@/lib/workspace/dialog';
import { workspaceHref } from '@/lib/workspace/url';
import type { ThreadChip, ThreadMessage, ThreadSummary } from './ThreadDrawer';

// The workspace provider (DEC-1376, WS-PRV): the patient criteria, the opened service, the thread and the
// hidden flag. Criteria live in React state only, never in the URL or browser storage (WS-PRIV). The one
// value stored is the hidden flag, through tenantStore.

export type Criteria = { age: AgeCode | null; postcode: string; needs: NeedCode[]; urgency: UrgencyCode | null };
export type Opened = { serviceName: string; updated: string; stale: boolean; noReport: boolean };

export type WorkspaceValue = {
  identity: { role: string | null; roles: readonly string[]; organisation: string | null };
  criteria: Criteria;
  setCriteria(patch: Partial<Criteria>): void;
  resetCriteria(): void;
  criteriaComplete: boolean;
  opened: Opened | null;
  remember(opened: Opened): void;
  messages: ThreadMessage[];
  chips: ThreadChip[];
  summary: ThreadSummary | null;
  visit(intentId: string, context: DialogContext): void;
  hidden: boolean;
  hide(): void;
  show(): void;
};

export type WorkspaceProviderProps = {
  role: string | null;
  roles?: readonly string[];
  organisation?: string | null;
  children: ReactNode;
};

type Over = NonNullable<Parameters<typeof workspaceHref>[1]>;

type Entry = {
  id: string;
  intent: string;
  echo: string | null;
  reply: string;
  chips: ChipSpec[];
  card: string | null;
  summaryBox: boolean;
  summaryLine: string | null;
};

type State = { criteria: Criteria; opened: Opened | null; history: Entry[]; counter: number };

type Action =
  | { type: 'setCriteria'; patch: Partial<Criteria> }
  | { type: 'resetCriteria' }
  | { type: 'remember'; opened: Opened }
  | { type: 'visit'; intentId: string; context: DialogContext };

const NEW_SEARCH = 'advisor.new-search';
const FIRST_INTENT = 'advisor.intake.age';
const MAX_MESSAGES = 6;
const HIDDEN_NAME = 'workspace.assistant.hidden';
const EMPTY_CRITERIA: Criteria = { age: null, postcode: '', needs: [], urgency: null };
const NO_ROLES: readonly string[] = [];
const INITIAL_STATE: State = { criteria: EMPTY_CRITERIA, opened: null, history: [], counter: 0 };

const WorkspaceContext = createContext<WorkspaceValue | null>(null);

function isTrue(value: unknown): value is true {
  return value === true;
}

// Storage can throw (blocked, cleared): a throwing store means shown, and hide still flips the state.
function readHidden(): boolean {
  try {
    return tenantStore.get(HIDDEN_NAME, isTrue) === true;
  } catch {
    return false;
  }
}

function writeHidden(hidden: boolean): void {
  try {
    if (hidden) tenantStore.set(HIDDEN_NAME, true);
    else tenantStore.remove(HIDDEN_NAME);
  } catch {
    // Storage is unavailable: the flag lasts for this page only.
  }
}

// The hidden flag as an external store, so the server render (and the first client render while hydrating) shows the
// drawer and the stored choice is read after hydration without a mismatch. `override` holds what this page chose, so a
// store that cannot be written still behaves for this page.
type HiddenStore = { override: boolean | null; listeners: Set<() => void> };

function newHiddenStore(): HiddenStore {
  return { override: null, listeners: new Set() };
}

function hiddenSnapshot(store: HiddenStore): boolean {
  return store.override ?? readHidden();
}

// Narrows a chip's params to the workspace link options (unknown values are left out).
function overFrom(params: Record<string, string> | undefined): Over {
  const over: Over = {};
  if (params === undefined) return over;
  if (params.order === 'travel' || params.order === 'name') over.order = params.order;
  if (params.tab === 'pressure' || params.tab === 'under') over.tab = params.tab;
  if (params.group !== undefined) over.group = params.group;
  if (params.area !== undefined) over.area = params.area;
  return over;
}

// Renders a turn without ever throwing out of the reducer (a throw there would crash the page). When the echo cannot be
// filled (its value is not known, for example a service page reached without opening a tile) the turn is shown without
// its echo; a turn that cannot be rendered at all leaves the thread as it was.
function safeTurn(intentId: string, context: DialogContext, withEcho: boolean): ReturnType<typeof renderTurn> {
  try {
    return renderTurn(intentId, context, { withEcho });
  } catch {
    if (!withEcho) return null;
  }
  try {
    return renderTurn(intentId, context, { withEcho: false });
  } catch {
    return null;
  }
}

// Appends the turn, or replaces the reply in place when the last entry has the same intent.
function visitTurn(state: State, intentId: string, context: DialogContext): State {
  const withEcho = state.history.length > 0;
  const turn = safeTurn(intentId, context, withEcho);
  if (turn === null) return state;

  const summaryLine = typeof context.summaryLine === 'string' ? context.summaryLine : null;
  const fields = {
    intent: intentId,
    echo: turn.echo,
    reply: turn.reply,
    chips: turn.chips,
    card: turn.card,
    summaryBox: turn.summaryBox,
    summaryLine,
  };

  const last: Entry | undefined = state.history[state.history.length - 1];
  if (last !== undefined && last.intent === intentId) {
    return { ...state, history: [...state.history.slice(0, -1), { ...last, ...fields }] };
  }
  const entry: Entry = { id: `${intentId}#${state.counter}`, ...fields };
  return { ...state, counter: state.counter + 1, history: [...state.history, entry] };
}

function reduce(state: State, action: Action): State {
  switch (action.type) {
    case 'setCriteria':
      return { ...state, criteria: { ...state.criteria, ...action.patch } };
    case 'resetCriteria':
      return { ...state, criteria: EMPTY_CRITERIA };
    case 'remember':
      return { ...state, opened: action.opened };
    case 'visit':
      if (action.intentId === NEW_SEARCH) {
        // A new search clears the criteria, the opened service and the thread, then starts again at age.
        return visitTurn({ ...state, criteria: EMPTY_CRITERIA, opened: null, history: [] }, FIRST_INTENT, {});
      }
      return visitTurn(state, action.intentId, action.context);
  }
}

// Every entry flattened to its person message (when it has an echo) and its assistant message; the last six kept.
function flatten(history: readonly Entry[]): ThreadMessage[] {
  const messages: ThreadMessage[] = [];
  for (const entry of history) {
    if (entry.echo !== null) messages.push({ id: `${entry.id}:echo`, from: 'person', text: entry.echo });
    messages.push({ id: `${entry.id}:reply`, from: 'assistant', text: entry.reply });
  }
  return messages.slice(-MAX_MESSAGES);
}

export function WorkspaceProvider({ role, roles = NO_ROLES, organisation = null, children }: WorkspaceProviderProps) {
  const [state, dispatch] = useReducer(reduce, INITIAL_STATE);
  const hiddenStore = useRef<HiddenStore | null>(null);
  if (hiddenStore.current === null) hiddenStore.current = newHiddenStore();
  const store = hiddenStore.current;
  const hidden = useSyncExternalStore(
    useCallback(
      (onChange: () => void) => {
        store.listeners.add(onChange);
        return () => {
          store.listeners.delete(onChange);
        };
      },
      [store],
    ),
    () => hiddenSnapshot(store),
    () => false,
  );

  const setCriteria = useCallback((patch: Partial<Criteria>) => dispatch({ type: 'setCriteria', patch }), []);
  const resetCriteria = useCallback(() => dispatch({ type: 'resetCriteria' }), []);
  const remember = useCallback((opened: Opened) => dispatch({ type: 'remember', opened }), []);
  const visit = useCallback(
    (intentId: string, context: DialogContext) => dispatch({ type: 'visit', intentId, context }),
    [],
  );
  const hide = useCallback(() => {
    writeHidden(true);
    store.override = true;
    store.listeners.forEach((listener) => listener());
  }, [store]);
  const show = useCallback(() => {
    writeHidden(false);
    store.override = false;
    store.listeners.forEach((listener) => listener());
  }, [store]);

  const { criteria, opened, history } = state;
  const last: Entry | undefined = history[history.length - 1];

  // Chips and summary come from the last entry only. A chip the role cannot open is dropped; no role, no chips.
  const chips: ThreadChip[] = [];
  if (role !== null && last !== undefined) {
    for (const chip of last.chips) {
      if (canOpen(role, chip.intent)) {
        chips.push({ label: chip.label, href: workspaceHref(chip.intent, overFrom(chip.params)) });
      }
    }
  }

  const summary: ThreadSummary | null =
    last !== undefined && last.summaryBox && last.summaryLine !== null
      ? { line: last.summaryLine, changeHref: workspaceHref('advisor.intake.need') }
      : null;

  const criteriaComplete =
    normalisePostcode(criteria.postcode) !== null &&
    criteria.age !== null &&
    criteria.needs.length > 0 &&
    criteria.urgency !== null;

  const value: WorkspaceValue = {
    identity: { role, roles, organisation },
    criteria,
    setCriteria,
    resetCriteria,
    criteriaComplete,
    opened,
    remember,
    messages: flatten(history),
    chips,
    summary,
    visit,
    hidden,
    hide,
    show,
  };

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceValue {
  const value = useContext(WorkspaceContext);
  if (value === null) throw new Error('useWorkspace: no provider');
  return value;
}
