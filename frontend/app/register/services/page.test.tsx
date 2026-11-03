import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { withApplicantHandlers } from '@/test/msw/applicant';
import MyServicesPage from './page';

withApplicantHandlers();

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

describe('my services page', () => {
  it('shows the heading and no axe violations', async () => {
    const { container } = render(await MyServicesPage());
    expect(screen.getByRole('heading', { level: 1, name: 'My services' })).toBeInTheDocument();
    expect((await runAxe(container)).violations).toEqual([]);
  });

  it('lists the services in the main region and says new ones come by invitation', async () => {
    render(await MyServicesPage());
    const main = screen.getByRole('main');
    expect(await within(main).findAllByRole('listitem')).toHaveLength(3);
    expect(within(main).getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(within(main).getByText('A new service comes by invitation from your shift lead.')).toBeInTheDocument();
  });
});
