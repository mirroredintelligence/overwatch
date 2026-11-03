import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { ProblemForm } from './ProblemForm';

const sent: unknown[] = [];

beforeEach(() => {
  sent.length = 0;
  server.use(http.post('/api/bff/help/problems', async ({ request }) => {
    sent.push(await request.json());
    return HttpResponse.json({ ok: true });
  }));
});

describe('ProblemForm', () => {
  it('asks the person to choose one kind before sending', async () => {
    render(<ProblemForm from="/help" />);
    await userEvent.click(screen.getByRole('button', { name: 'Send report' }));
    expect(screen.getByText('Choose one.')).toBeInTheDocument();
    expect(sent).toHaveLength(0);
  });

  it('posts the kind and the page the person came from', async () => {
    render(<ProblemForm from="/case/[ref]" />);
    await userEvent.click(screen.getByRole('button', { name: 'A button does not work' }));
    await userEvent.click(screen.getByRole('button', { name: 'Send report' }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toEqual({ kind: 'button-does-not-work', route: '/case/[ref]' });
    expect(await screen.findByText('Thanks. We have your report.')).toBeInTheDocument();
  });

  it('says it is sending while the report goes, and holds the button so a second tap does nothing', async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    server.use(http.post('/api/bff/help/problems', async () => {
      await gate;
      return HttpResponse.json({ ok: true });
    }));
    render(<ProblemForm from="/help" />);
    await userEvent.click(screen.getByRole('button', { name: 'A screen is slow' }));
    await userEvent.click(screen.getByRole('button', { name: 'Send report' }));
    expect(await screen.findByText('Sending your report.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send report' })).toBeDisabled();
    release();
    expect(await screen.findByText('Thanks. We have your report.')).toBeInTheDocument();
    expect(screen.queryByText('Sending your report.')).not.toBeInTheDocument();
  });

  it('confirms in a status region, with a shape as well as the words, and takes the form away', async () => {
    render(<ProblemForm from="/help" />);
    await userEvent.click(screen.getByRole('button', { name: 'A screen is slow' }));
    await userEvent.click(screen.getByRole('button', { name: 'Send report' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Thanks. We have your report.');
    expect(screen.getByRole('status').querySelector('svg[aria-hidden="true"]')).not.toBeNull();
    expect(screen.queryByRole('button', { name: 'Send report' })).not.toBeInTheDocument();
  });

  it('says the report did not send, and keeps what was typed, when the back end cannot take it', async () => {
    server.use(http.post('/api/bff/help/problems', () => HttpResponse.json({ code: 'unavailable' }, { status: 503 })));
    render(<ProblemForm from="/help" />);
    await userEvent.click(screen.getByRole('button', { name: 'A figure looks wrong' }));
    await userEvent.type(screen.getByLabelText('Tell us more (optional)'), 'Total is off');
    await userEvent.click(screen.getByRole('button', { name: 'Send report' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('We could not send that. Nothing was lost: your words are still here. Try again.');
    expect(alert.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
    expect(screen.getByLabelText('Tell us more (optional)')).toHaveValue('Total is off');
    expect(screen.getByRole('button', { name: 'A figure looks wrong' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Send report' })).toBeEnabled();
  });

  it('keeps the "No patient names or details" warning with the count', () => {
    render(<ProblemForm from="/help" />);
    expect(screen.getByText('No patient names or details.')).toBeInTheDocument();
    expect(screen.getByText('0 of 280')).toBeInTheDocument();
  });

  it('warns about a postcode in the text without blocking it', async () => {
    render(<ProblemForm from="/help" />);
    await userEvent.type(screen.getByLabelText('Tell us more (optional)'), 'DT4 8XX looks wrong');
    expect(screen.getByText('This looks like it may contain patient details. Please remove them.')).toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<ProblemForm from="/help" />);
    expect(screen.getByRole('button', { name: 'Send report' })).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
