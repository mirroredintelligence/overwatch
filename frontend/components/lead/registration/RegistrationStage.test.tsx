import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetRegistrationRequests } from '@/test/msw/handlers/registrations';
import { RegistrationOverview } from '../RegistrationOverview';
import { RegistrationStage } from './RegistrationStage';

beforeEach(() => resetRegistrationRequests());
vi.setConfig({ testTimeout: 15_000 });

const grid = (container: HTMLElement) => container.querySelector<HTMLElement>('[data-stage]')!;

describe('RegistrationStage', () => {
  it('at the queue stage shows the queue alone, in the wide track, under the page heading', async () => {
    const { container } = render(<RegistrationStage stage={0} />);
    expect(screen.getByRole('heading', { level: 1, name: 'Registrations' })).toBeInTheDocument();
    expect(await screen.findByRole('list', { name: 'Registrations to review' })).toBeInTheDocument();
    expect(grid(container)).toHaveAttribute('data-stage', '0');
    expect(JSON.parse(grid(container).dataset.css!).gridTemplateColumns).toMatch(/^minmax\(0,\s*1fr\) 0px/);
    expect(screen.queryByRole('link', { name: /Back to registrations/ })).toBeNull();
    expect(container.querySelector('[role="main"]')).not.toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('narrows the queue to 380px when a registration opens, and shows it beside the queue', async () => {
    const { container } = render(
      <RegistrationStage stage={1} selectedId="r1">
        <RegistrationOverview id="r1" />
      </RegistrationStage>,
    );
    expect(JSON.parse(grid(container).dataset.css!).gridTemplateColumns).toMatch(/^380px/);
    expect(await screen.findByRole('heading', { level: 1, name: 'UCR East' })).toBeInTheDocument();
    const queue = await screen.findByRole('list', { name: 'Registrations to review' });
    expect(within(queue).getAllByRole('listitem')[0]).toHaveAttribute('aria-current', 'true');
    expect(screen.getByRole('link', { name: 'Back to registrations' })).toHaveAttribute('href', '/lead/registrations');
  });

  it('narrows the queue to 300px for each check, and keeps the queue in the page', async () => {
    const { container } = render(
      <RegistrationStage stage={3} selectedId="r1">
        <p>The scope check</p>
      </RegistrationStage>,
    );
    expect(JSON.parse(grid(container).dataset.css!).gridTemplateColumns).toMatch(/^300px/);
    expect(screen.getByText('The scope check')).toBeInTheDocument();
    expect(await screen.findByRole('list', { name: 'Registrations to review' })).toBeInTheDocument();
    // The step draws its own heading and landmark: the stage adds none of its own.
    expect(screen.queryByRole('heading', { level: 1, name: 'Registrations' })).toBeNull();
    expect(container.querySelector('[role="main"]')).toBeNull();
  });

  it('copies the first problem of the open registration into its queue card', async () => {
    render(
      <RegistrationStage stage={1} selectedId="r1">
        <RegistrationOverview id="r1" />
      </RegistrationStage>,
    );
    const queue = await screen.findByRole('list', { name: 'Registrations to review' });
    const card = within(queue).getAllByRole('listitem')[0]!;
    expect(await within(card).findByText('Criteria owner email is not an organisation address')).toBeInTheDocument();
    expect(within(queue).getAllByText('Needs attention:')).toHaveLength(1);
  });

  it('keeps the first problem on the card while a check is open', async () => {
    const { rerender } = render(
      <RegistrationStage stage={1} selectedId="r1">
        <RegistrationOverview id="r1" />
      </RegistrationStage>,
    );
    const queue = await screen.findByRole('list', { name: 'Registrations to review' });
    await within(queue).findByText('Criteria owner email is not an organisation address');
    rerender(
      <RegistrationStage stage={2} selectedId="r1">
        <p>The call-back</p>
      </RegistrationStage>,
    );
    expect(within(queue).getByText('Criteria owner email is not an organisation address')).toBeInTheDocument();
  });
});
