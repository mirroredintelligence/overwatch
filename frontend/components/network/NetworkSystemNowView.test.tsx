import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { SYSTEM_NOW_BODY } from '@/test/fixtures/network';
import { networkBffHandlers } from '@/test/msw/handlers/networkBff';
import { server } from '@/test/msw/server';
import { parseSystemNow } from '@/lib/network/parse';
import { NetworkSystemNowView } from './NetworkSystemNowView';

// W17, network variant (`GET /network/{id}/system-now`): the counts of the network board by status, the
// numbers of services and organisations, and the pressure state. A network has no chase cards, ladder or
// requests (they are an organisation's own), so this is the counts and the pressure, naming no
// organisation and no service. The pressure is a state of the board, never an instruction (H-654).

const view = () => render(<NetworkSystemNowView ownHref="/lead" />);
const withBody = (over: Record<string, unknown>) => parseSystemNow({ ...SYSTEM_NOW_BODY, ...over }, 'backend');
const FOOTNOTE = "Your organisation's own chase cards, escalation ladder and requests are on your own System now, not here.";

describe('NetworkSystemNowView', () => {
  it('shows the scope header, the title and each status with its word and its number', async () => {
    server.use(...networkBffHandlers);
    view();
    expect(await screen.findByRole('heading', { level: 1, name: 'Sample Network system now' })).toBeInTheDocument();
    const counts = await screen.findByRole('group', { name: 'Services by status' });
    expect(screen.getByRole('region', { name: 'Which board you are viewing' })).toHaveTextContent('Showing: Network, Sample Network');
    for (const [word, n] of [['Accepting', '1'], ['Limited', '1'], ['Not accepting', '0'], ['Over capacity', '0'], ['Not updated', '1'], ['Out of hours', '0'], ['Not on the network', '1']]) {
      const term = within(counts).getByText(word);
      expect(term.parentElement).toHaveTextContent(n as string);
    }
  });

  it('draws one stacked bar with every status and its number, as one image with a name', async () => {
    server.use(...networkBffHandlers);
    view();
    await screen.findByText('4 services from 3 organisations');
    expect(
      screen.getByRole('img', {
        name: 'Of 4 services: 1 accepting, 1 limited, 0 not accepting, 0 over capacity, 1 not updated, 0 out of hours, 1 not on the network',
      }),
    ).toBeInTheDocument();
  });

  it('says how many services from how many organisations, and when', async () => {
    server.use(...networkBffHandlers);
    view();
    expect(await screen.findByText('4 services from 3 organisations')).toBeInTheDocument();
    expect(screen.getByText(/As at 14:12/)).toBeInTheDocument();
  });

  it('shows no pressure notice while the pressure is normal', async () => {
    server.use(...networkBffHandlers);
    view();
    await screen.findByText('4 services from 3 organisations');
    expect(screen.queryByText(/Network pressure/)).toBeNull();
  });

  it('says the pressure is high as a state, with the count and where it starts, when the alert is raised', async () => {
    server.use(http.get('/api/bff/network/system-now', () => HttpResponse.json(withBody({ pressure: 'high', alert: { raised: true, level: 'high', limited_or_worse: 6, watch_from: 3, high_from: 5 } }))), ...networkBffHandlers);
    view();
    const title = await screen.findByText('Network pressure is high.');
    expect(title.parentElement).toHaveTextContent('Network pressure is high. 6 services are limited, not accepting or over capacity. High from 5.');
    expect(document.body.textContent).not.toMatch(/you must|should|escalate|call/i);
  });

  it('says the pressure is rising at the watch level, with the count of services and where it starts', async () => {
    server.use(http.get('/api/bff/network/system-now', () => HttpResponse.json(withBody({ pressure: 'watch', alert: { raised: false, level: 'watch', limited_or_worse: 3, watch_from: 3, high_from: 5 } }))), ...networkBffHandlers);
    view();
    const title = await screen.findByText('Network pressure is rising.');
    expect(title.parentElement).toHaveTextContent('Network pressure is rising. 3 services are limited, not accepting or over capacity. Rising from 3.');
  });

  it('names no organisation, no service and no chase or request in the counts (a network has none)', async () => {
    server.use(...networkBffHandlers);
    const { container } = view();
    await screen.findByText('4 services from 3 organisations');
    const withoutFootnote = (container.textContent ?? '').replace(FOOTNOTE, '');
    expect(withoutFootnote).not.toMatch(/Sample Area|UCR West|chas|pending|request/i);
    expect(container.innerHTML).not.toMatch(/trust-|tenant|net-sample/i);
  });

  it('says what this is and that the footnote points to the organisation own System now', async () => {
    server.use(...networkBffHandlers);
    view();
    expect(await screen.findByText(/It names no organisation and no service\./)).toBeInTheDocument();
    expect(screen.getByText(/It is never an instruction\./)).toBeInTheDocument();
    expect(screen.getByText(FOOTNOTE)).toBeInTheDocument();
  });

  it('says one service from one organisation in the singular', async () => {
    server.use(http.get('/api/bff/network/system-now', () => HttpResponse.json(withBody({ services: 1, organisations: 1 }))), ...networkBffHandlers);
    view();
    expect(await screen.findByText('1 service from 1 organisation')).toBeInTheDocument();
  });

  it('is "not available" when refused, and says the network could not be read when a read fails with no counts yet', async () => {
    server.use(http.get('/api/bff/network/system-now', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })), ...networkBffHandlers);
    const refused = view();
    expect(await screen.findByText('Network view not available')).toBeInTheDocument();
    expect(screen.queryByText('Accepting')).toBeNull();
    refused.unmount();
    server.use(http.get('/api/bff/network/system-now', () => HttpResponse.json({ code: 'exception' }, { status: 503 })));
    view();
    expect(await screen.findByText('The network could not be read. Try again shortly.')).toBeInTheDocument();
    expect(screen.queryByText('Accepting')).toBeNull();
    expect(screen.queryByText('0')).toBeNull();
  });

  it('has no axe violations', async () => {
    server.use(...networkBffHandlers);
    const { container } = view();
    await screen.findByText('4 services from 3 organisations');
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
