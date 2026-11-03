import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import type { FlagItem } from '@/lib/lead/flags';
import { FlagList } from './FlagList';

// The master list of flagged reports (LDR-09): one button per flag, the open one marked with aria-current.

const ITEMS: FlagItem[] = [
  { id: 'f1', serviceId: 's1', serviceName: 'UCR East', reason: 'many-changes', summary: 'The figure changed many times in a short time.' },
  { id: 'f2', serviceId: 's2', serviceName: 'SDEC Site 2', reason: 'out-of-range-twice', summary: 'The figure was out of its usual range twice.' },
];

describe('FlagList', () => {
  it('lists each flag as a button with the service and the reason in words', () => {
    render(<FlagList items={ITEMS} currentId={null} onOpen={() => {}} />);
    const list = screen.getByRole('list', { name: 'Flagged reports' });
    expect(list).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
    const first = screen.getByRole('button', { name: /UCR East/ });
    expect(first).toHaveTextContent('The figure changed many times in a short time.');
  });

  it('marks the open flag with aria-current and no other', () => {
    render(<FlagList items={ITEMS} currentId="f2" onOpen={() => {}} />);
    expect(screen.getByRole('button', { name: /SDEC Site 2/ })).toHaveAttribute('aria-current', 'true');
    expect(screen.getByRole('button', { name: /UCR East/ })).not.toHaveAttribute('aria-current');
  });

  it('calls onOpen with the id of the flag that is chosen', async () => {
    const onOpen = vi.fn();
    render(<FlagList items={ITEMS} currentId="f1" onOpen={onOpen} />);
    await userEvent.setup().click(screen.getByRole('button', { name: /SDEC Site 2/ }));
    expect(onOpen).toHaveBeenCalledWith('f2');
  });

  it('has no axe violations', async () => {
    const { container } = render(<FlagList items={ITEMS} currentId="f1" onOpen={() => {}} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
