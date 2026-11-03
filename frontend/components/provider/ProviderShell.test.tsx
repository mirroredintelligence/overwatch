import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { ProviderShell } from './ProviderShell';

describe('ProviderShell', () => {
  it('shows the mark, the service chip, the progress and the content', () => {
    render(
      <ProviderShell service="UCR West" step={2}>
        <h1>Check your number</h1>
      </ProviderShell>,
    );
    expect(screen.getByRole('banner')).toHaveTextContent('Overwatch');
    expect(screen.getByRole('banner')).toHaveTextContent('UCR West');
    expect(screen.getByLabelText('Step 2 of 5')).toBeInTheDocument();
    expect(screen.getByRole('main')).toContainElement(screen.getByRole('heading', { level: 1, name: 'Check your number' }));
  });

  it('leaves out the chip and the progress when there is no service and no step', () => {
    render(
      <ProviderShell>
        <h1>Link expired</h1>
      </ProviderShell>,
    );
    expect(screen.queryByLabelText(/^Step /)).toBeNull();
    expect(screen.getByRole('banner').querySelector('[data-chip]')).toBeNull();
  });

  it('puts the sticky action after the content', () => {
    render(
      <ProviderShell service="UCR West" step={1} action={{ primary: { label: 'Start' }, link: { label: 'Back', onClick: () => {} } }}>
        <h1>Welcome</h1>
      </ProviderShell>,
    );
    expect(screen.getByRole('button', { name: 'Start' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Back' })).toBeInTheDocument();
    const main = screen.getByRole('main');
    expect(main.compareDocumentPosition(screen.getByRole('button', { name: 'Start' })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('does not steal focus on first render', () => {
    render(
      <ProviderShell service="UCR West" step={1}>
        <h1>Welcome</h1>
      </ProviderShell>,
    );
    expect(document.body).toHaveFocus();
  });

  it('moves focus to the heading when the step changes', () => {
    const { rerender } = render(
      <ProviderShell service="UCR West" step={1}>
        <h1>First</h1>
      </ProviderShell>,
    );
    rerender(
      <ProviderShell service="UCR West" step={2}>
        <h1>Second</h1>
      </ProviderShell>,
    );
    expect(screen.getByRole('heading', { level: 1, name: 'Second' })).toHaveFocus();
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <ProviderShell service="UCR West" step={3} action={{ primary: { label: 'Continue' } }}>
        <h1>Add to home screen</h1>
      </ProviderShell>,
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
