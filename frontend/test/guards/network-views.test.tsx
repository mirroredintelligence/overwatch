import { render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NetworkBoardView } from '@/components/network/NetworkBoardView';
import { NetworkHistoryView } from '@/components/network/NetworkHistoryView';
import { NetworkPhonesView } from '@/components/network/NetworkPhonesView';
import { NetworkServiceDetail } from '@/components/network/NetworkServiceDetail';
import { NetworkServicesView } from '@/components/network/NetworkServicesView';
import { NetworkSystemNowView } from '@/components/network/NetworkSystemNowView';
import { NetworkWeekView } from '@/components/network/NetworkWeekView';
import { FakeStream } from '@/test/fakeStream';
import { NETWORK_LIST } from '@/test/msw/handlers/networkBff';
import { server } from '@/test/msw/server';

// KI-552 (TEN-063 audit D 7.3): render EVERY network view and look for a value shaped like a source
// tenant, a grant or a tenant. A network view carries capacity only. The BFF already rebuilds each answer
// from the fields a page uses; this test is the second line: it hands every view answers that have been
// poisoned at every level of the object (a tenant id, a source tenant id, a grant id, a source service id),
// as a back end or BFF that had gone wrong would send, and checks that not one of them reaches the page, in
// its text or in any attribute. A view added to the network family without an entry here fails the last test.

const POISON = 'trust-poison-9';

/** Adds a poisoned field of each kind to every object, however deep. */
function poison<T>(value: T): T {
  if (Array.isArray(value)) return value.map(poison) as T;
  if (typeof value === 'object' && value !== null) {
    const out: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value)) out[key] = poison(item);
    return { ...out, tenantId: POISON, sourceTenantId: POISON, source_tenant_id: POISON, grantId: POISON, sourceServiceId: POISON } as T;
  }
  return value;
}

/** The default BFF handlers, each answering a poisoned copy of its body. */
function poisoned() {
  return [
    http.get('/api/bff/network', () => HttpResponse.json(poison(NETWORK_LIST))),
    ...(['board', 'directory', 'criteria', 'system-now', 'phones', 'week'] as const).map((view) =>
      http.get(`/api/bff/network/${view}`, async ({ request }) => HttpResponse.json(poison(await fetchClean(view, request)))),
    ),
  ];
}

// The clean answer of a view: the same fixtures the stand-in of the BFF uses, through the same parser.
async function fetchClean(view: string, request: Request): Promise<unknown> {
  const { parseBoard, parseCriteria, parseDirectory, parsePhones, parseSystemNow, parseWeek } = await import('@/lib/network/parse');
  const f = await import('@/test/fixtures/network');
  const history = new URL(request.url).searchParams.get('history') === 'true';
  switch (view) {
    case 'board':
      return parseBoard(f.BOARD_BODY, 'backend');
    case 'directory':
      return parseDirectory(history ? f.DIRECTORY_HISTORY_BODY : f.DIRECTORY_BODY, 'backend');
    case 'criteria':
      return parseCriteria(f.CRITERIA_BODY, 'backend');
    case 'system-now':
      return parseSystemNow(f.SYSTEM_NOW_BODY, 'backend');
    case 'phones':
      return parsePhones(f.PHONES_BODY, 'backend');
    default:
      return parseWeek(f.WEEK_BODY, 'backend');
  }
}

const VIEWS: [string, () => React.ReactElement, string][] = [
  ['the board', () => <NetworkBoardView ownHref="/advisor/board" />, 'UCR West'],
  ['the services', () => <NetworkServicesView ownHref="/advisor/board" />, 'UCR West'],
  ['a service', () => <NetworkServiceDetail rowRef="lst-0001" ownHref="/advisor/board" />, 'Shared by Sample Area A'],
  ['the history', () => <NetworkHistoryView ownHref="/advisor/board" />, 'Former service'],
  ['system now', () => <NetworkSystemNowView ownHref="/lead" />, '4 services from 3 organisations'],
  ['the phones', () => <NetworkPhonesView ownHref="/lead/phones" />, '3 services from 3 organisations'],
  ['the week', () => <NetworkWeekView ownHref="/planning/week" />, '134 hours sampled'],
];

beforeEach(() => {
  vi.stubGlobal(
    'EventSource',
    class {
      constructor() {
        return new FakeStream() as unknown as EventSource;
      }
    },
  );
  server.use(...poisoned());
});
afterEach(() => vi.unstubAllGlobals());

describe('every network view shows no tenant, grant or source id', () => {
  it('is not vacuous: the answers the views are given really carry the poison', async () => {
    for (const path of ['/api/bff/network', '/api/bff/network/board', '/api/bff/network/directory', '/api/bff/network/phones', '/api/bff/network/week']) {
      const text = await (await fetch(path)).text();
      expect(text, path).toContain(POISON);
    }
  });

  it.each(VIEWS)('%s', async (_name, element, ready) => {
    const { container } = render(element());
    await waitFor(() => expect(screen.getAllByText(new RegExp(ready.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))).length).toBeGreaterThan(0), { timeout: 4000 });
    // Text and every attribute of the page, as markup.
    expect(container.innerHTML).not.toContain(POISON);
    expect(container.innerHTML).not.toMatch(/sourceTenant|source_tenant|tenantId|grantId|sourceServiceId|trust-[a-z]/i);
    expect(container.textContent).not.toMatch(/trust-[a-z]|tenant/i);
  });

  it('the list of views here is the list of the network views on disk', async () => {
    const files = Object.keys(import.meta.glob('../../components/network/Network*View.tsx', { eager: false })).map((path) => path.split('/').pop());
    const known = ['NetworkBoardView.tsx', 'NetworkHistoryView.tsx', 'NetworkPhonesView.tsx', 'NetworkServicesView.tsx', 'NetworkSystemNowView.tsx', 'NetworkWeekView.tsx'];
    // NetworkServiceDetail is the one view whose file is not named View; it has its own entry above.
    expect(files.sort()).toEqual(known);
  });
});
