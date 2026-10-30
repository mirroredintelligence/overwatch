import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { STATE_NOT_REACHED, STATE_WITHDRAWN } from '@/test/fixtures/bookings';
import { CancelBookingDialog } from './CancelBookingDialog';
import { WithdrawalAlert } from './WithdrawalAlert';

// The advisor's cancel dialog and the withdrawal alert (W21). Sample values only: booking 4821.

describe('CancelBookingDialog for a confirmed booking', () => {
  it('asks the question, lists the four reasons, and keeps Cancel booking off until one is chosen', async () => {
    const { container } = render(<CancelBookingDialog kind="booking" serviceName="UCR West" onConfirm={vi.fn()} onKeep={vi.fn()} />);
    expect(screen.getByRole('dialog', { name: 'Cancel booking' })).toBeInTheDocument();
    expect(screen.getByText('Cancel the booking with UCR West?')).toBeInTheDocument();
    for (const reason of ['Caller declined', 'No longer needed', 'Other route found', 'Entered in error']) {
      expect(screen.getByRole('button', { name: reason })).toBeInTheDocument();
    }
    expect(screen.getByText('The service is told by its own channel. The slot goes back to available.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel booking' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Cancel booking' })).toHaveAttribute('data-el', 'ADV-CANCEL-CONFIRM-BTN');
    expect(screen.getByRole('button', { name: 'Keep booking' })).toHaveAttribute('data-el', 'ADV-CANCEL-KEEP-BTN');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('confirms with the reason chosen', async () => {
    const onConfirm = vi.fn();
    render(<CancelBookingDialog kind="booking" serviceName="UCR West" onConfirm={onConfirm} onKeep={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: 'No longer needed' }));
    await userEvent.click(screen.getByRole('button', { name: 'Cancel booking' }));
    expect(onConfirm).toHaveBeenCalledWith('no-longer-needed');
  });

  it('closes with Keep booking, and gives focus back to the control that opened it', async () => {
    const onKeep = vi.fn();
    function Host() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open cancel
          </button>
          {open ? <CancelBookingDialog kind="booking" serviceName="UCR West" onConfirm={vi.fn()} onKeep={() => { onKeep(); setOpen(false); }} /> : null}
        </>
      );
    }
    render(<Host />);
    const opener = screen.getByRole('button', { name: 'Open cancel' });
    await userEvent.click(opener);
    await userEvent.click(screen.getByRole('button', { name: 'Keep booking' }));
    expect(onKeep).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it('shows the state-changed message when the booking moved on', () => {
    render(
      <CancelBookingDialog
        kind="booking"
        serviceName="UCR West"
        conflict="This booking changed before you cancelled. Check its status."
        onConfirm={vi.fn()}
        onKeep={vi.fn()}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('This booking changed before you cancelled. Check its status.');
  });
});

describe('CancelBookingDialog for a request not yet answered', () => {
  it('asks about the request, with Cancel request and Keep request', async () => {
    const { container } = render(<CancelBookingDialog kind="request" serviceName="UCR West" onConfirm={vi.fn()} onKeep={vi.fn()} />);
    expect(screen.getByRole('dialog', { name: 'Cancel request' })).toBeInTheDocument();
    expect(screen.getByText('Cancel the request to UCR West?')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Keep request' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Caller declined' }));
    await userEvent.click(screen.getByRole('button', { name: 'Cancel request' }));
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

function renderAlert(props: Partial<Parameters<typeof WithdrawalAlert>[0]> = {}) {
  const handlers = {
    onAcknowledge: vi.fn(async () => true),
    onLeaveOpen: vi.fn(),
    onSeeOptions: vi.fn(),
    onAskClinical: vi.fn(),
  };
  const result = render(<WithdrawalAlert booking={STATE_WITHDRAWN} serviceName="UCR West" {...handlers} {...props} />);
  return { ...result, ...handlers };
}

describe('WithdrawalAlert (W21, DEC-854)', () => {
  it('opens as an alert dialog on the shared shell, and says the reason and the time', async () => {
    const { container } = renderAlert();
    const dialog = screen.getByRole('alertdialog', { name: 'UCR West withdrew' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(document.activeElement).toBe(dialog);
    expect(screen.getByText('Withdrawn')).toBeInTheDocument();
    expect(screen.getByText('Reason: staffing. Withdrawn 14:41.')).toBeInTheDocument();
    expect(screen.getByText('Phone the caller now.')).toBeInTheDocument();
    expect(screen.getByText('Tell them another service is being found.')).toBeInTheDocument();
    expect(screen.getByText('If nobody acts within 10 minutes the shift lead is alerted.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'I have phoned the caller' })).toHaveAttribute('data-el', 'ADV-WITHDRAWN-PHONED-BTN');
    expect(screen.getByRole('button', { name: 'The caller is already being helped' })).toHaveAttribute('data-el', 'ADV-WITHDRAWN-HELPED-BTN');
    expect(screen.getByRole('button', { name: 'See options again' })).toHaveAttribute('data-el', 'ADV-WITHDRAWN-OPTIONS-BTN');
    expect(screen.getByRole('button', { name: 'Ask a clinical advisor' })).toHaveAttribute('data-el', 'ADV-WITHDRAWN-CLINICAL-BTN');
    expect(screen.queryByRole('button', { name: 'Phone the caller' })).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it.each(['I have phoned the caller', 'The caller is already being helped'])(
    'acknowledges, once, only from the explicit answer "%s"',
    async (answer) => {
      const { onAcknowledge, onLeaveOpen, onSeeOptions, onAskClinical } = renderAlert();
      await userEvent.click(screen.getByRole('button', { name: answer }));
      expect(onAcknowledge).toHaveBeenCalledTimes(1);
      expect(onLeaveOpen).not.toHaveBeenCalled();
      expect(onSeeOptions).not.toHaveBeenCalled();
      expect(onAskClinical).not.toHaveBeenCalled();
    },
  );

  it('does NOT acknowledge on "See options again": the alert stays open and the escalation keeps running (the old first-action rule fails here)', async () => {
    const { onAcknowledge, onLeaveOpen, onSeeOptions } = renderAlert();
    await userEvent.click(screen.getByRole('button', { name: 'See options again' }));
    expect(onAcknowledge).not.toHaveBeenCalled();
    expect(onSeeOptions).toHaveBeenCalledTimes(1);
    expect(onLeaveOpen).toHaveBeenCalledTimes(1);
  });

  it('does NOT acknowledge on "Ask a clinical advisor" (the old first-action rule fails here)', async () => {
    const { onAcknowledge, onLeaveOpen, onAskClinical } = renderAlert();
    await userEvent.click(screen.getByRole('button', { name: 'Ask a clinical advisor' }));
    expect(onAcknowledge).not.toHaveBeenCalled();
    expect(onAskClinical).toHaveBeenCalledTimes(1);
    expect(onLeaveOpen).toHaveBeenCalledTimes(1);
  });

  it('does NOT acknowledge on Escape: it leaves the alert open', async () => {
    const { onAcknowledge, onLeaveOpen } = renderAlert();
    await userEvent.keyboard('{Escape}');
    expect(onAcknowledge).not.toHaveBeenCalled();
    expect(onLeaveOpen).toHaveBeenCalledTimes(1);
  });

  it('says so, stays open and lets the advisor answer again when the acknowledgement could not be sent', async () => {
    const { onAcknowledge, onLeaveOpen } = renderAlert({ onAcknowledge: vi.fn(async () => false) });
    await userEvent.click(screen.getByRole('button', { name: 'I have phoned the caller' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The answer could not be sent. The shift lead will still be told. Try again.');
    expect(onLeaveOpen).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'I have phoned the caller' }));
    expect(onAcknowledge).toHaveBeenCalledTimes(2);
  });

  it('presses once, even when the answer is pressed twice quickly', async () => {
    let release: (value: boolean) => void = () => undefined;
    const onAcknowledge = vi.fn(() => new Promise<boolean>((resolve) => (release = resolve)));
    renderAlert({ onAcknowledge });
    const button = screen.getByRole('button', { name: 'I have phoned the caller' });
    await userEvent.click(button);
    await userEvent.click(button);
    expect(onAcknowledge).toHaveBeenCalledTimes(1);
    release(true);
  });

  it('reads a not-reached report with its own title, its reason, and no clinical-advice button', async () => {
    const { container } = renderAlert({ booking: STATE_NOT_REACHED });
    expect(screen.getByRole('alertdialog', { name: 'UCR West could not reach the patient' })).toBeInTheDocument();
    expect(screen.getByText('Reason: No answer at the door. Reported 14:41.')).toBeInTheDocument();
    expect(screen.getByText('The coordination team is told and will phone the caller.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'I have phoned the caller' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Ask a clinical advisor' })).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('the advisor dialogs use the shared Dialog (W14, DEC-637)', () => {
  it.each(['CancelBookingDialog.tsx', 'WithdrawalAlert.tsx'])('%s builds on components/ui/Dialog and draws no modal of its own', (file) => {
    const source = readFileSync(resolve(process.cwd(), 'components/advisor', file), 'utf8');
    expect(source).toContain("from '@/components/ui/Dialog'");
    expect(source).not.toMatch(/role=["'](alert)?dialog["']/);
    expect(source).not.toContain('aria-modal');
  });

  it('Escape in the cancel dialog keeps the booking', async () => {
    const onKeep = vi.fn();
    render(<CancelBookingDialog kind="booking" serviceName="UCR West" onConfirm={vi.fn()} onKeep={onKeep} />);
    await userEvent.keyboard('{Escape}');
    expect(onKeep).toHaveBeenCalledTimes(1);
  });
});
