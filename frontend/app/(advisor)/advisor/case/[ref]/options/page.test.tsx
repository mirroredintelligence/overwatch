import { render, screen, within } from '@testing-library/react';
import { networkBffHandlers } from '@/test/msw/handlers/networkBff';
import { server } from '@/test/msw/server';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

import OptionsPage from './page';

describe('options page (W13)', () => {
  it('marks the Options step current, and shows the options list for the case', async () => {
    render(await OptionsPage({ params: Promise.resolve({ ref: '4821' }) }));

    expect(document.querySelector('[data-step="options"]')).toHaveAttribute('aria-current', 'step');
    expect(document.querySelector('[data-step="needs"]')).toHaveAttribute('data-state', 'done');
    expect(screen.getByText('Loading the options.')).toBeInTheDocument();
  });

  it('?service= of a service of this case opens its Request state, with the other options beside it', async () => {
    render(await OptionsPage({ params: Promise.resolve({ ref: '4821' }), searchParams: Promise.resolve({ service: 'svc-ward-b' }) }));

    const card = await screen.findByRole('article', { name: 'Community hospital · Ward B' });
    expect(within(card).getByRole('button', { name: 'Request booking' })).toBeInTheDocument();
    expect(screen.getByRole('complementary', { name: 'Other options' })).toBeInTheDocument();
    expect(document.querySelector('[data-step="options"]')).toHaveAttribute('aria-current', 'step');
  });

  it('takes the first of a repeated ?service=, and ignores one that is not among the options', async () => {
    const { unmount } = render(
      await OptionsPage({ params: Promise.resolve({ ref: '4821' }), searchParams: Promise.resolve({ service: ['svc-ucr-west', 'svc-ward-b'] }) }),
    );
    expect(await screen.findByRole('article', { name: 'UCR West' })).toBeInTheDocument();
    expect(screen.getAllByRole('article')).toHaveLength(1);
    unmount();

    render(await OptionsPage({ params: Promise.resolve({ ref: '4821' }), searchParams: Promise.resolve({ service: 'svc-nowhere' }) }));
    expect(await screen.findByRole('heading', { name: "3 services meet this patient's criteria" })).toBeInTheDocument();
    expect(screen.getAllByRole('article')).toHaveLength(3);
  });

  it('has one level-one heading for the page', async () => {
    render(await OptionsPage({ params: Promise.resolve({ ref: '4821' }) }));
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
  });

  it('says it shows our organisation’s options and offers the network’s, when the organisation is in a network (WB11)', async () => {
    server.use(...networkBffHandlers);
    render(await OptionsPage({ params: Promise.resolve({ ref: '4821' }) }));
    const header = screen.getByRole('region', { name: 'Which board you are viewing' });
    expect(header).toHaveTextContent('Showing: Our organisation');
    const nav = await within(header).findByRole('navigation', { name: 'Choose the board' });
    expect(within(nav).getByRole('link', { name: 'Network' })).toHaveAttribute('href', '/advisor/case/4821/network-options');
    expect(within(nav).getByRole('link', { name: 'Our organisation' })).toHaveAttribute('href', '/advisor/case/4821/options');
  });
});
