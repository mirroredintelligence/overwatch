import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { byEl } from '@/test/el';
import { resetSeenAdvisorRequests, seenOutcomePosts } from '@/test/msw/handlers/advisor';
import { server } from '@/test/msw/server';
import { FinishScreen } from './FinishScreen';

// A booking the service confirmed (DEC-1344): the outcome and the place are chosen already, and copying the summary
// records them and closes the case. When nothing is chosen, or the clipboard refuses, the case stays open.

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace }) }));

const writeText = vi.fn();

function useClipboard() {
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
}

const BOOKED = { destination: 'svc-ucr-west' };

beforeEach(() => {
  resetCsrfCache();
  resetSeenAdvisorRequests();
  replace.mockReset();
  writeText.mockReset();
  writeText.mockResolvedValue(undefined);
  useClipboard();
});

describe('FinishScreen: a confirmed booking (DEC-1344)', () => {
  it('has "Accepted and booked" and the service chosen already, and the summary names the service', async () => {
    render(<FinishScreen caseId="4821" preselect={null} booked={BOOKED} />);

    expect(byEl('ADV-FIN-OUTCOME-ACCEPTED')).toHaveAttribute('aria-pressed', 'true');
    expect(await screen.findByRole('button', { name: 'UCR West', pressed: true })).toBeInTheDocument();
    expect(await screen.findByText('Reference 4821 · UCR West')).toBeInTheDocument();
  });

  it('says that copying records the outcome and closes the case', async () => {
    render(<FinishScreen caseId="4821" preselect={null} booked={BOOKED} />);
    expect(await screen.findByRole('button', { name: 'Copy summary and close the case' })).toBeInTheDocument();
  });

  it('copying puts the summary on the clipboard, records the outcome with the service and closes the case', async () => {
    const user = userEvent.setup();
    useClipboard();
    render(<FinishScreen caseId="4821" preselect={null} booked={BOOKED} />);

    await user.click(await screen.findByRole('button', { name: 'Copy summary and close the case' }));

    expect(await screen.findByRole('heading', { name: 'Call closed' })).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledTimes(1);
    expect(seenOutcomePosts).toHaveLength(1);
    expect(seenOutcomePosts[0].body).toEqual({ outcome: 'accepted-and-booked', destinationServiceId: 'svc-ucr-west' });
    expect(replace).toHaveBeenCalledWith('/advisor/case/4821/finish?closed=1');
    expect(document.body.textContent).not.toContain('DT4 8XX');
  });

  it('does not close the case when the clipboard refuses: the text is shown to copy by hand', async () => {
    writeText.mockRejectedValue(new Error('refused'));
    const user = userEvent.setup();
    useClipboard();
    render(<FinishScreen caseId="4821" preselect={null} booked={BOOKED} />);

    await user.click(await screen.findByRole('button', { name: 'Copy summary and close the case' }));

    expect(await screen.findByText('Press Ctrl+C to copy')).toBeInTheDocument();
    expect(seenOutcomePosts).toHaveLength(0);
    expect(screen.queryByRole('heading', { name: 'Call closed' })).toBeNull();
  });

  it('keeps the case open and says so when the outcome could not be saved after the copy', async () => {
    server.use(http.post('/api/bff/cases/:ref/outcome', () => HttpResponse.json({}, { status: 500 })));
    const user = userEvent.setup();
    useClipboard();
    render(<FinishScreen caseId="4821" preselect={null} booked={BOOKED} />);

    await user.click(await screen.findByRole('button', { name: 'Copy summary and close the case' }));

    expect(await screen.findByText('Copied, but the outcome could not be saved. Use Save outcome.')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Call closed' })).toBeNull();
  });

  it('closes with the outcome the advisor changed it to, not the booking they started with', async () => {
    const user = userEvent.setup();
    useClipboard();
    render(<FinishScreen caseId="4821" preselect={null} booked={BOOKED} />);
    await screen.findByRole('button', { name: 'UCR West', pressed: true });

    await user.click(byEl('ADV-FIN-OUTCOME-DECLINED'));
    await user.click(await screen.findByRole('button', { name: 'Copy summary and close the case' }));

    await waitFor(() => expect(seenOutcomePosts).toHaveLength(1));
    expect(seenOutcomePosts[0].body).toEqual({ outcome: 'declined' });
  });
});

describe('FinishScreen: no booking (DEC-1344)', () => {
  it('copying alone does not close the case or record anything until an outcome is chosen', async () => {
    const user = userEvent.setup();
    useClipboard();
    render(<FinishScreen caseId="4821" preselect={null} />);

    await user.click(await screen.findByRole('button', { name: 'Copy summary' }));

    expect(await screen.findByText('Copied to clipboard')).toBeInTheDocument();
    expect(seenOutcomePosts).toHaveLength(0);
    expect(screen.queryByRole('heading', { name: 'Call closed' })).toBeNull();
  });

  it('once an outcome is chosen, copying records it and closes the case', async () => {
    const user = userEvent.setup();
    useClipboard();
    render(<FinishScreen caseId="4821" preselect={null} />);

    await user.click(byEl('ADV-FIN-OUTCOME-DECLINED'));
    await user.click(await screen.findByRole('button', { name: 'Copy summary and close the case' }));

    expect(await screen.findByRole('heading', { name: 'Call closed' })).toBeInTheDocument();
    expect(seenOutcomePosts[0].body).toEqual({ outcome: 'declined' });
  });
});
