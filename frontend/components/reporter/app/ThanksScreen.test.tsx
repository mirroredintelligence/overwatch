import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { ThanksScreen } from './ThanksScreen';

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace }) }));

describe('ThanksScreen', () => {
  it('thanks the reporter, gives the next update time, and lists today newest first', async () => {
    const { container } = render(<ThanksScreen serviceId="svc-1" service="UCR West" value={3} at="10:12" nextDue="12:00" />);
    expect(screen.getByRole('heading', { name: 'Thank you' })).toBeInTheDocument();
    expect(screen.getByText('UCR West: 3 referrals recorded at 10:12.')).toBeInTheDocument();
    expect(screen.getByText('Next update due 12:00')).toBeInTheDocument();
    const rows = await screen.findAllByRole('listitem');
    expect(rows.map((row) => row.textContent)).toEqual(['10:12 3', '08:15 2']);
    expect(screen.getByRole('link', { name: 'Change it' })).toHaveAttribute('href', '/app/respond/svc-1');
    expect(await runAxe(container)).toHaveNoViolations();
    expect(within(container).queryByText(/\d{7,}/)).toBeNull();
  });
});
