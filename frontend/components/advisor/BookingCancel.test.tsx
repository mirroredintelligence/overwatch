import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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

describe('WithdrawalAlert', () => {
  it('opens as an alert dialog with focus on its heading, and says the reason and the time', async () => {
    const { container } = render(
      <WithdrawalAlert booking={STATE_WITHDRAWN} serviceName="UCR West" onAcknowledge={vi.fn(async () => undefined)} onSeeOptions={vi.fn()} />,
    );
    expect(screen.getByRole('alertdialog', { name: 'UCR West withdrew' })).toBeInTheDocument();
    expect(screen.getByText('Withdrawn')).toBeInTheDocument();
    const heading = screen.getByRole('heading', { name: 'UCR West can no longer take this patient' });
    expect(document.activeElement).toBe(heading);
    expect(screen.getByText('Reason: staffing. Withdrawn 14:41.')).toBeInTheDocument();
    expect(screen.getByText('Phone the caller now.')).toBeInTheDocument();
    expect(screen.getByText('Tell them another service is being found.')).toBeInTheDocument();
    expect(screen.getByText('If nobody acts within 10 minutes the shift lead is alerted.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'See options again' })).toHaveAttribute('data-el', 'ADV-WITHDRAWN-OPTIONS-BTN');
    expect(screen.getByRole('button', { name: 'Ask a clinical advisor' })).toHaveAttribute('data-el', 'ADV-WITHDRAWN-CLINICAL-BTN');
    expect(screen.getByRole('button', { name: 'Phone the caller' })).toHaveAttribute('data-el', 'ADV-WITHDRAWN-CALLER-BTN');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('acknowledges first, then goes to the options, for See options again', async () => {
    const order: string[] = [];
    render(
      <WithdrawalAlert
        booking={STATE_WITHDRAWN}
        serviceName="UCR West"
        onAcknowledge={vi.fn(async () => {
          order.push('acknowledged');
        })}
        onSeeOptions={() => order.push('options')}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'See options again' }));
    expect(order).toEqual(['acknowledged', 'options']);
  });

  it('calls onAskClinical and onPhoneCaller after acknowledging', async () => {
    const onAskClinical = vi.fn();
    const onPhoneCaller = vi.fn();
    render(
      <WithdrawalAlert
        booking={STATE_WITHDRAWN}
        serviceName="UCR West"
        onAcknowledge={vi.fn(async () => undefined)}
        onSeeOptions={vi.fn()}
        onAskClinical={onAskClinical}
        onPhoneCaller={onPhoneCaller}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Ask a clinical advisor' }));
    expect(onAskClinical).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole('button', { name: 'Phone the caller' }));
    expect(onPhoneCaller).toHaveBeenCalledTimes(1);
  });

  it('reads a not-reached report with its own title and its reason', async () => {
    const { container } = render(
      <WithdrawalAlert booking={STATE_NOT_REACHED} serviceName="UCR West" onAcknowledge={vi.fn(async () => undefined)} onSeeOptions={vi.fn()} />,
    );
    expect(screen.getByRole('alertdialog', { name: 'UCR West could not reach the patient' })).toBeInTheDocument();
    expect(screen.getByText('Reason: No answer at the door. Reported 14:41.')).toBeInTheDocument();
    expect(screen.getByText('The SPOA is told and will phone the caller.')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
