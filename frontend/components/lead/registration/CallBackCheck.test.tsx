import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetRegistrationRequests, seenRegistrationRequests } from '@/test/msw/handlers/registrations';
import { CallBackCheck } from './CallBackCheck';

const CALLBACK = '/api/bff/registrations/r1/callback';
beforeEach(() => resetRegistrationRequests());
const posts = (path: string) => seenRegistrationRequests.filter((r) => r.method === 'POST' && r.path === path);

// The user-event tests here run slowly when the whole suite shares the machine; the budget is per file.
vi.setConfig({ testTimeout: 15_000 });

describe('CallBackCheck', () => {
  it('asks who was spoken to when the call is confirmed, and posts nothing until a role is given', async () => {
    const user = userEvent.setup();
    const { container } = render(<CallBackCheck id="r1" />);
    expect(await screen.findByRole('heading', { level: 1, name: 'Call the service back' })).toBeInTheDocument();
    expect(screen.getByText('Check 1 of 4')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Confirmed' }));
    await user.click(screen.getByRole('button', { name: 'Save result' }));
    expect(await screen.findByText('Enter who you spoke to')).toBeInTheDocument();
    expect(posts(CALLBACK)).toHaveLength(0);

    await user.type(screen.getByLabelText(/Who you spoke to/), 'Ward manager');
    await user.click(screen.getByRole('button', { name: 'Save result' }));
    await waitFor(() => expect(posts(CALLBACK)).toHaveLength(1));
    expect(posts(CALLBACK)[0]?.body).toMatchObject({ result: 'confirmed', spokeToRole: 'Ward manager' });
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows the number to call apart from the number the applicant gave, and the script with the name and role', async () => {
    render(<CallBackCheck id="r1" />);
    expect(
      await screen.findByText('Phone the number on the NHS register or the Dorset directory. Do not use the number the applicant gave.'),
    ).toBeInTheDocument();
    const toCall = screen.getByText('01202 000 111');
    expect(toCall.tagName).toBe('STRONG');
    expect(screen.getByText('Number the applicant gave:')).toBeInTheDocument();
    expect(screen.getByText('01202 000 999')).toBeInTheDocument();
    expect(screen.getByText('Ask for Sample Person, or the person in charge')).toBeInTheDocument();
    expect(screen.getByText('Ask: is Sample Person a Duty manager at UCR East?')).toBeInTheDocument();
    expect(screen.getByText('Do not talk about any patient')).toBeInTheDocument();
  });

  it('reaches the result options with Tab and chooses one with Space', async () => {
    const user = userEvent.setup();
    render(<CallBackCheck id="r1" />);
    const confirmed = await screen.findByRole('button', { name: 'Confirmed' });
    confirmed.focus();
    await user.keyboard('{Tab}');
    expect(screen.getByRole('button', { name: 'Not confirmed' })).toHaveFocus();
    await user.keyboard('{Tab}');
    expect(screen.getByRole('button', { name: 'No answer' })).toHaveFocus();
    await user.keyboard(' ');
    expect(screen.getByRole('button', { name: 'No answer' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(screen.getByRole('group', { name: 'Result' })).getAllByRole('button')).toHaveLength(3);
  });
});
