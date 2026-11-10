import { act, cleanup, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { tenantStore } from '@/lib/storage/tenantStore';
import { WorkspaceProvider, useWorkspace, type Criteria } from './WorkspaceProvider';

// The workspace provider (DEC-1376, WS-PRV): criteria in memory only, the thread history, and the hidden flag.
// Tests use neutral words and the postcode examples of the spec only.

const { store, storeMode } = vi.hoisted(() => ({
  store: new Map<string, unknown>(),
  storeMode: { throws: false },
}));

// An in-memory tenantStore: get applies the validator, and every call throws while storeMode.throws is set.
vi.mock('@/lib/storage/tenantStore', () => ({
  tenantStore: {
    get: (name: string, validate: (value: unknown) => boolean) => {
      if (storeMode.throws) throw new Error('storage blocked');
      const value = store.get(name);
      return value !== undefined && validate(value) ? value : undefined;
    },
    set: (name: string, value: unknown) => {
      if (storeMode.throws) throw new Error('storage blocked');
      store.set(name, value);
      return true;
    },
    remove: (name: string) => {
      store.delete(name);
    },
    names: () => [...store.keys()],
    clear: () => {
      const count = store.size;
      store.clear();
      return count;
    },
  },
}));

const HIDDEN_KEY = 'workspace.assistant.hidden';
const AGE_REPLY = "Let's find a service for your patient. Two short steps, then I will show who can take them.";
const NEED_REPLY = 'What does the patient need, and by when?';
const MAP_REPLY =
  'Here is the map. Visiting services show the area they cover; sites show where they are. Tap a service to open it, or ask:';
const NEED_CTX = { age: '65 to 79', district: 'DT4' };
const COMPLETE: Criteria = { age: '65-79', postcode: 'DT4 8XX', needs: ['frailty'], urgency: 'today' };
const EMPTY: Criteria = { age: null, postcode: '', needs: [], urgency: null };

function wrapper(role: string | null) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <WorkspaceProvider role={role}>{children}</WorkspaceProvider>;
  };
}

function mount(role: string | null = 'advisor') {
  return renderHook(() => useWorkspace(), { wrapper: wrapper(role) });
}

beforeEach(() => {
  store.clear();
  storeMode.throws = false;
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('WorkspaceProvider', () => {
  it('WS-PRV-T01 the first visit yields one assistant message and no person message, even for a turn with an echo', () => {
    const { result } = mount();
    act(() => result.current.visit('advisor.intake.need', NEED_CTX));
    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0]).toMatchObject({ from: 'assistant', text: NEED_REPLY });
  });

  it('WS-PRV-T02 a second visit to a different intent appends the echo then the reply; ids are unique and unchanged across re-renders', () => {
    const { result, rerender } = mount();
    act(() => result.current.visit('advisor.intake.age', {}));
    act(() => result.current.visit('advisor.intake.need', NEED_CTX));
    const first = result.current.messages;
    expect(first).toHaveLength(3);
    expect(first[0]).toMatchObject({ from: 'assistant', text: AGE_REPLY });
    expect(first[1]).toMatchObject({ from: 'person', text: '65 to 79 · DT4' });
    expect(first[1].id.endsWith(':echo')).toBe(true);
    expect(first[2]).toMatchObject({ from: 'assistant', text: NEED_REPLY });
    expect(first[2].id.endsWith(':reply')).toBe(true);

    rerender();
    const ids = result.current.messages.map((message) => message.id);
    expect(ids).toEqual(first.map((message) => message.id));
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('WS-PRV-T03 visiting the same intent again with a changed context replaces its reply in place', () => {
    const { result } = mount();
    act(() => result.current.visit('advisor.results', { count: 3, order: 'travel', notSuitable: 0 }));
    const before = result.current.messages;
    expect(before).toHaveLength(1);

    act(() => result.current.visit('advisor.results', { count: 5, order: 'travel', notSuitable: 0 }));
    const after = result.current.messages;
    expect(after).toHaveLength(1);
    expect(after[0].id).toBe(before[0].id);
    expect(after[0].text).toBe("5 services meet this patient's criteria, sorted by travel time. Not ranked.");
    expect(after[0].text).not.toBe(before[0].text);
  });

  it('WS-PRV-T04 chips belong to the last entry only: after advisor.results they are exactly the List and map and List by name chips', () => {
    const { result } = mount('advisor');
    act(() => result.current.visit('advisor.intake.age', {}));
    act(() => result.current.visit('advisor.results', { count: 3, order: 'travel' }));
    expect(result.current.chips).toEqual([
      { label: 'List and map', href: '/advisor/v2?mode=find&view=map' },
      { label: 'List by name', href: '/advisor/v2?mode=find&view=list&order=name' },
    ]);

    act(() => result.current.visit('advisor.intake.age', {}));
    expect(result.current.chips).toEqual([]);
  });

  it('WS-PRV-T05 a chip whose intent the role cannot open is dropped; role null gives no chips', () => {
    const advisor = mount('advisor');
    act(() => advisor.result.current.visit('advisor.results', { count: 3, order: 'travel' }));
    expect(advisor.result.current.chips.map((chip) => chip.label)).toEqual(['List and map', 'List by name']);

    const lead = mount('lead');
    act(() => lead.result.current.visit('advisor.results', { count: 3, order: 'travel' }));
    expect(lead.result.current.chips).toEqual([]);

    const none = mount(null);
    act(() => none.result.current.visit('advisor.results', { count: 3, order: 'travel' }));
    expect(none.result.current.chips).toEqual([]);
  });

  it('WS-PRV-T06 visit advisor.new-search empties the criteria and history, then leaves exactly the age reply', () => {
    const { result } = mount();
    act(() => result.current.setCriteria(COMPLETE));
    act(() => result.current.visit('advisor.intake.age', {}));
    act(() => result.current.visit('advisor.intake.need', NEED_CTX));
    expect(result.current.messages.length).toBeGreaterThan(1);

    act(() => result.current.visit('advisor.new-search', {}));
    expect(result.current.criteria).toEqual(EMPTY);
    expect(result.current.messages).toEqual([{ id: expect.any(String), from: 'assistant', text: AGE_REPLY }]);
    expect(result.current.chips).toEqual([]);
    expect(result.current.summary).toBeNull();
  });

  it('WS-PRV-T07 after ten visits to alternating intents only the last six messages remain', () => {
    const { result } = mount();
    for (let i = 0; i < 10; i += 1) {
      const intent = i % 2 === 0 ? 'advisor.intake.need' : 'advisor.map';
      act(() => result.current.visit(intent, NEED_CTX));
    }
    const { messages } = result.current;
    expect(messages).toHaveLength(6);
    expect(messages.map((message) => [message.from, message.text])).toEqual([
      ['person', 'List and map'],
      ['assistant', MAP_REPLY],
      ['person', '65 to 79 · DT4'],
      ['assistant', NEED_REPLY],
      ['person', 'List and map'],
      ['assistant', MAP_REPLY],
    ]);
    const ids = messages.map((message) => message.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('WS-PRV-T08 setCriteria never writes browser storage or changes the location; a second provider starts with empty criteria', () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    const hrefBefore = window.location.href;

    const first = mount();
    act(() => first.result.current.setCriteria(COMPLETE));
    expect(first.result.current.criteria).toEqual(COMPLETE);
    expect(setItem).not.toHaveBeenCalled();
    expect(window.location.href).toBe(hrefBefore);

    const second = mount();
    expect(second.result.current.criteria).toEqual(EMPTY);
  });

  it('WS-PRV-T09 hidden starts false with an empty store; hide stores the flag; show removes it; a stored flag starts hidden', () => {
    const first = mount();
    expect(first.result.current.hidden).toBe(false);

    act(() => first.result.current.hide());
    expect(first.result.current.hidden).toBe(true);
    expect(tenantStore.get(HIDDEN_KEY, (value): value is true => value === true)).toBe(true);

    act(() => first.result.current.show());
    expect(first.result.current.hidden).toBe(false);
    expect(store.has(HIDDEN_KEY)).toBe(false);

    store.set(HIDDEN_KEY, true);
    const second = mount();
    expect(second.result.current.hidden).toBe(true);
  });

  it('WS-PRV-T10 when the store throws, hidden starts false and hide still sets it true without throwing', () => {
    storeMode.throws = true;
    const { result } = mount();
    expect(result.current.hidden).toBe(false);
    expect(() => act(() => result.current.hide())).not.toThrow();
    expect(result.current.hidden).toBe(true);
  });

  it('WS-PRV-T11 criteriaComplete is true only when age, a full postcode, a need and a timeframe are all set', () => {
    const full = mount();
    act(() => full.result.current.setCriteria(COMPLETE));
    expect(full.result.current.criteriaComplete).toBe(true);

    const missing: Partial<Criteria>[] = [
      { age: null },
      { postcode: '' },
      { postcode: 'DT4' },
      { needs: [] },
      { urgency: null },
    ];
    for (const patch of missing) {
      const { result } = mount();
      act(() => result.current.setCriteria({ ...COMPLETE, ...patch }));
      expect(result.current.criteriaComplete, JSON.stringify(patch)).toBe(false);
    }
  });

  it('WS-PRV-T12 the summary comes from the last entry when its turn has a summary box and a summary line', () => {
    const { result } = mount();
    act(() =>
      result.current.visit('advisor.results', {
        count: 3,
        order: 'travel',
        summaryLine: '65 to 79 · DT4 · Frailty · Today',
      }),
    );
    expect(result.current.summary).toEqual({
      line: '65 to 79 · DT4 · Frailty · Today',
      changeHref: '/advisor/v2?mode=find&view=find&step=need',
    });

    act(() => result.current.visit('advisor.map', { summaryLine: '65 to 79 · DT4 · Frailty · Today' }));
    expect(result.current.summary).toBeNull();
  });

  it('WS-PRV-T13 useWorkspace outside a provider throws', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    expect(() => renderHook(() => useWorkspace())).toThrow('useWorkspace: no provider');
  });

  it('WS-PRV-T14 a turn whose echo cannot be filled is shown without its echo, and a turn that cannot render leaves the thread unchanged, neither throws', () => {
    const { result } = mount();
    act(() => result.current.visit('advisor.intake.age', {}));
    // advisor.service has the echo "Open {serviceName}": with no service name the reply variant for that case is used.
    expect(() => act(() => result.current.visit('advisor.service', {}))).not.toThrow();
    expect(result.current.messages.map((m) => [m.from, m.text])).toEqual([
      ['assistant', AGE_REPLY],
      ['assistant', 'Here is the service. If the call allows, check that its figure is current.'],
    ]);
    // advisor.intake.need needs {age} and {district} for its echo and its reply has none: no echo, still shown.
    act(() => result.current.visit('advisor.intake.need', {}));
    expect(result.current.messages.at(-1)).toMatchObject({ from: 'assistant', text: NEED_REPLY });
    // A turn that cannot be rendered at all (an overview turn missing its organisation) changes nothing.
    const before = result.current.messages.map((m) => m.id);
    expect(() => act(() => result.current.visit('overview.home', { total: 3 }))).not.toThrow();
    expect(result.current.messages.map((m) => m.id)).toEqual(before);
  });
});
