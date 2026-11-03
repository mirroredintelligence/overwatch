import { render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { RegisterStage } from './RegisterStage';

function phone(matches: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockImplementation((query: string) => ({
      matches,
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    })),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe('RegisterStage on a wide screen', () => {
  it('draws the top bar with Save and come back later, the checklist, the step and the help', () => {
    render(
      <RegisterStage registrationId="REG-1" stage={2}>
        <h1>Where is the service?</h1>
      </RegisterStage>,
    );
    expect(screen.getByRole('banner')).toHaveTextContent('Overwatch');
    const later = within(screen.getByRole('banner')).getByRole('link', { name: 'Save and come back later' });
    expect(later).toHaveAttribute('href', '/register?saved=1');
    expect(later).toHaveAttribute('data-el', 'REG-SAVE-LATER-BTN');
    expect(screen.getByRole('navigation', { name: 'Your registration' })).toBeInTheDocument();
    const stage = screen.getByRole('region', { name: 'Current step' });
    expect(within(stage).getByRole('heading', { level: 1, name: 'Where is the service?' })).toBeInTheDocument();
    expect(within(screen.getByRole('complementary', { name: 'Help' })).getByText('Why we ask')).toBeInTheDocument();
    expect(screen.getByRole('main')).toBeInTheDocument();
  });

  it('shows the service in the top bar when it is known, and the saved note', () => {
    render(
      <RegisterStage registrationId="REG-1" stage={1} service="UCR East" savedNote="Saved a moment ago">
        <h1>Tell us</h1>
      </RegisterStage>,
    );
    expect(screen.getByRole('banner')).toHaveTextContent('UCR East · invited by your shift lead');
    expect(screen.getByRole('banner')).toHaveTextContent('Saved a moment ago');
  });

  it('opens the grid for the stage: 300px help beside a step, none on the start and review stages', () => {
    const columns = (stage: number) => {
      const { container, unmount } = render(
        <RegisterStage registrationId="REG-1" stage={stage}>
          <h1>x</h1>
        </RegisterStage>,
      );
      const value = JSON.parse((container.querySelector('[data-stage]') as HTMLElement).dataset.css!).gridTemplateColumns;
      unmount();
      return value;
    };
    expect(columns(0)).toBe('300px minmax(0,1fr) 0px');
    expect(columns(1)).toBe('300px minmax(0,1fr) 300px');
    expect(columns(4)).toBe('300px minmax(0,1fr) 300px');
    expect(columns(5)).toBe('300px minmax(0,1fr) 0px');
    expect(columns(6)).toBe('0px minmax(0,1fr) 0px');
  });

  it('has no help text on the start stage and hides the checklist once submitted', () => {
    const { unmount } = render(
      <RegisterStage registrationId="REG-1" stage={0}>
        <h1>Start</h1>
      </RegisterStage>,
    );
    expect(screen.queryByText('Why we ask')).toBeNull();
    unmount();
    render(
      <RegisterStage registrationId="REG-1" stage={6}>
        <h1>Done</h1>
      </RegisterStage>,
    );
    expect(screen.queryByRole('navigation', { name: 'Your registration' })).toBeNull();
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <RegisterStage registrationId="REG-1" stage={1}>
        <h1>Tell us</h1>
      </RegisterStage>,
    );
    expect((await runAxe(container)).violations).toEqual([]);
  });
});

describe('RegisterStage on a phone', () => {
  it('uses the phone frame: progress, the step, a Why we ask disclosure and the sticky action', () => {
    phone(true);
    render(
      <RegisterStage registrationId="REG-1" stage={3} service="UCR East" phoneAction={{ primary: { label: 'Continue' }, link: { label: 'Back', href: '/register/REG-1/location' } }}>
        <h1>Describe the service</h1>
      </RegisterStage>,
    );
    expect(screen.getByLabelText('Step 3 of 5')).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Your registration' })).toBeNull();
    expect(screen.getByRole('button', { name: /Why we ask/ })).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByRole('button', { name: 'Continue' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back' })).toBeInTheDocument();
  });

  it('offers Save and come back later as the link when the page gives no action', () => {
    phone(true);
    render(
      <RegisterStage registrationId="REG-1" stage={1}>
        <h1>Tell us</h1>
      </RegisterStage>,
    );
    expect(screen.getByRole('link', { name: 'Save and come back later' })).toHaveAttribute('href', '/register?saved=1');
  });

  it('has no progress bar on the start stage', () => {
    phone(true);
    render(
      <RegisterStage registrationId="REG-1" stage={0}>
        <h1>Start</h1>
      </RegisterStage>,
    );
    expect(screen.queryByRole('progressbar')).toBeNull();
  });
});
