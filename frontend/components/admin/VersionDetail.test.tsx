import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { VIEW_VERSIONS } from '@/test/fixtures/tenantAdmin';
import { resetAdminWrites, seenAdminWrites } from '@/test/msw/handlers/tenantAdmin';
import { SAMPLE_CSRF } from '@/test/msw/handlers/staff';
import { server } from '@/test/msw/server';
import { VersionDetail } from './VersionDetail';

// One version of the settings (TEN-076): what it changes against the version below it, who has approved it
// (as counts, and "you"), and the approval. The author of a clinical change cannot approve it and says so; a
// person who has approved already cannot again; two approvers who are not the author complete it.

beforeEach(() => resetAdminWrites());

const OTHER = { ...VIEW_VERSIONS.versions[0]!, version: 5, authoredByYou: false, approvals: 0, approvedByYou: false };

function serve(version: Record<string, unknown>) {
  server.use(
    http.get(`/api/bff/tenant/config/versions/${String(version.version)}`, () => HttpResponse.json(version)),
    http.get('/api/bff/tenant/config/versions', () => HttpResponse.json({ versions: [version, ...VIEW_VERSIONS.versions.slice(1)] })),
  );
}

describe('a version you wrote', () => {
  it('shows what it changes, its state and its approvals, and says you cannot approve it', async () => {
    render(<VersionDetail version={3} />);
    await screen.findByRole('complementary', { name: 'Approval' });
    expect(screen.getByRole('heading', { level: 1, name: 'Version 3' })).toBeInTheDocument();
    expect(screen.getByText('Waiting for approval · 0 of 2')).toBeInTheDocument();
    expect(screen.getAllByText('Clinical').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole('img', { name: '0 of 2 approvals' })).toBeInTheDocument();
    const card = within(screen.getByRole('region', { name: 'What changed' })).getByRole('region', { name: 'Pressure watch from' });
    expect(within(within(card).getByRole('group', { name: 'Was' })).getByText('4')).toBeInTheDocument();
    expect(within(within(card).getByRole('group', { name: 'Now' })).getByText('5')).toBeInTheDocument();
    expect(screen.getByText(/You cannot approve it\./)).toHaveTextContent(
      'You wrote this change. You cannot approve it. Ask another administrator, or someone in a role that can approve.',
    );
  });

  it('shows the approve button disabled and named for the author, and no dialog opens', async () => {
    const user = userEvent.setup();
    render(<VersionDetail version={3} />);
    const button = await screen.findByRole('button', { name: 'Approve (not for the author)' });
    expect(button).toBeDisabled();
    await user.click(button);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Approve version/ })).not.toBeInTheDocument();
  });

  it('has no withdraw button, and says to ask a platform operator', async () => {
    render(<VersionDetail version={3} />);
    await screen.findByRole('heading', { level: 1, name: 'Version 3' });
    expect(screen.queryByRole('button', { name: /Withdraw/ })).not.toBeInTheDocument();
    expect(screen.getByText('Ask a platform operator to withdraw this draft.')).toBeInTheDocument();
  });

  it('says which version it replaces, and links back to all versions', async () => {
    render(<VersionDetail version={3} />);
    await screen.findByRole('heading', { level: 1, name: 'Version 3' });
    expect(screen.getByText(/replaces version 2/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /All versions/ })).toHaveAttribute('href', '/admin/config');
  });
});

describe('the approval panel', () => {
  it('says in words, for the approver, that the author cannot approve a clinical change', async () => {
    serve(OTHER);
    render(<VersionDetail version={5} />);
    expect(await screen.findByRole('complementary', { name: 'Approval' })).toHaveTextContent('Approvals must come from people other than the one who wrote it.');
    expect(screen.getByRole('img', { name: '0 of 2 approvals' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Approve version 5' })).toBeEnabled();
  });

  it('counts the approvals given so far', async () => {
    serve({ ...OTHER, approvals: 1 });
    render(<VersionDetail version={5} />);
    expect(await screen.findByRole('img', { name: '1 of 2 approvals' })).toBeInTheDocument();
    expect(screen.getByText('Waiting for approval · 1 of 2')).toBeInTheDocument();
  });

  it('shows a draft that has no approval yet as a draft', async () => {
    serve({ ...OTHER, status: 'draft' });
    render(<VersionDetail version={5} />);
    expect(await screen.findByText('Draft · 0 of 2')).toBeInTheDocument();
  });
});

describe('while it loads', () => {
  it('says what is loading, under the version number', async () => {
    server.use(http.get('/api/bff/tenant/config/versions/3', () => new Promise<never>(() => {})));
    render(<VersionDetail version={3} />);
    expect(screen.getByRole('heading', { level: 1, name: 'Version 3' })).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Loading this version.');
  });
});

describe('a version somebody else wrote', () => {
  it('offers the approval, asks to confirm it, and says how many have approved', async () => {
    serve(OTHER);
    const user = userEvent.setup();
    render(<VersionDetail version={5} />);
    await user.click(await screen.findByRole('button', { name: 'Approve version 5' }));
    const dialog = await screen.findByRole('dialog', { name: 'Approve version 5?' });
    expect(within(dialog).getByText(/Pressure watch from/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Confirm approval' }));
    await waitFor(() => expect(seenAdminWrites).toHaveLength(1));
    expect(seenAdminWrites[0]).toMatchObject({ method: 'POST', path: '/api/bff/tenant/config/versions/5/approval', csrf: SAMPLE_CSRF });
    expect(seenAdminWrites[0]?.key).toBeTruthy();
    expect(await screen.findByRole('status')).toHaveTextContent('You approved version 5. 1 of 2 approvals.');
    expect(screen.queryByRole('button', { name: 'Approve version 5' })).not.toBeInTheDocument();
  });

  it('can be cancelled out of: nothing is sent', async () => {
    serve(OTHER);
    const user = userEvent.setup();
    render(<VersionDetail version={5} />);
    await user.click(await screen.findByRole('button', { name: 'Approve version 5' }));
    await user.click(await screen.findByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(seenAdminWrites).toEqual([]);
  });

  it('says it is done, and shows the version in force, when the approval completes it', async () => {
    serve({ ...OTHER, approvals: 1 });
    server.use(http.post('/api/bff/tenant/config/versions/5/approval', () => HttpResponse.json({ version: 5, status: 'current', approvals: 2, approvalsRequired: 2 })));
    const user = userEvent.setup();
    render(<VersionDetail version={5} />);
    await user.click(await screen.findByRole('button', { name: 'Approve version 5' }));
    await user.click(await screen.findByRole('button', { name: 'Confirm approval' }));
    expect(await screen.findByRole('status')).toHaveTextContent('You approved version 5. It is now in force.');
  });

  it('says when the approval is refused (a repeat, an older version), without the back end’s words', async () => {
    serve(OTHER);
    server.use(http.post('/api/bff/tenant/config/versions/5/approval', () => HttpResponse.json({ code: 'business-rule', message: 'x' }, { status: 409 })));
    const user = userEvent.setup();
    render(<VersionDetail version={5} />);
    await user.click(await screen.findByRole('button', { name: 'Approve version 5' }));
    await user.click(await screen.findByRole('button', { name: 'Confirm approval' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('This version cannot be approved by you now. Reload the page to see where it stands.');
  });
});

describe('a version nobody can approve any more', () => {
  it('says you have approved it already, with no button', async () => {
    serve({ ...OTHER, approvals: 1, approvedByYou: true });
    render(<VersionDetail version={5} />);
    expect(await screen.findByText('You have approved this version.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Approve/ })).not.toBeInTheDocument();
  });

  it('offers no approval for the version in force or an older one', async () => {
    render(<VersionDetail version={2} />);
    expect(await screen.findByText('In force')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Approve/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/Ask a platform operator/)).not.toBeInTheDocument();
  });

  it('says a replaced version is replaced, with no button', async () => {
    render(<VersionDetail version={1} />);
    expect(await screen.findByText('Replaced')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});

describe('failures', () => {
  it('says the version could not be found, on a 404', async () => {
    render(<VersionDetail version={99} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not find that version.');
  });

  it('says it could not load on a failed read', async () => {
    server.use(http.get('/api/bff/tenant/config/versions/3', () => HttpResponse.json({}, { status: 503 })));
    render(<VersionDetail version={3} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load this version.');
  });

  it('has no axe violations', async () => {
    render(<VersionDetail version={3} />);
    await screen.findByRole('heading', { name: 'Version 3' });
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
