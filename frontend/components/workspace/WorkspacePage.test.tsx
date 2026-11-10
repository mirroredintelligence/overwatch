import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect, useRef } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { DialogContext } from '@/lib/workspace/dialog';
import { WorkspacePage } from './WorkspacePage';
import { WorkspaceProvider, useWorkspace } from './WorkspaceProvider';

// The page wrapper (DEC-1376, WS-SHL): the frame around a page, with the assistant drawer or its button. The provider
// is real here, so its messages come from visits made by a helper child, as the pages make them.

const { store, storeMode } = vi.hoisted(() => ({
  store: new Map<string, unknown>(),
  storeMode: { throws: false },
}));

// An in-memory tenantStore, the same shape the provider's own tests use.
vi.mock('@/lib/storage/tenantStore', () => ({
  tenantStore: {
    get: (name: string, validate: (value: unknown) => boolean) => {
      if (storeMode.throws) throw new Error('storage blocked');
      const value = store.get(name);
      return value !== undefined && validate(value) ? value : undefined;
    },
    set: (name: string, value: unknown) => {
      if (storeMode.throws) throw new Error('storage blocked');
      store.set(name, value);
      return true;
    },
    remove: (name: string) => {
      store.delete(name);
    },
    names: () => [...store.keys()],
    clear: () => {
      const count = store.size;
      store.clear();
      return count;
    },
  },
}));

const HIDDEN_KEY = 'workspace.assistant.hidden';
const AGE_REPLY = "Let's find a service for your patient. Two short steps, then I will show who can take them.";
const NO_CONTEXT: DialogContext = {};

// Visits one intent once, on mount, the way a page does.
function Visit({ intent, context }: { intent: string; context: DialogContext }) {
  const { visit } = useWorkspace();
  const done = useRef(false);
  useEffect(() => {
    if (done.current) return;
    done.current = true;
    visit(intent, context);
  }, [context, intent, visit]);
  return null;
}

// Reports whether the drawer is hidden, so a test can check the state it relies on.
function Hidden({ report }: { report: (hidden: boolean) => void }) {
  report(useWorkspace().hidden);
  return null;
}

beforeEach(() => {
  store.clear();
  storeMode.throws = false;
});

describe('WorkspacePage', () => {
  it('WS-SHL-T03 with the thread and not hidden renders the drawer with the provider messages; Hide removes it and shows the Show button', async () => {
    const user = userEvent.setup();
    render(
      <WorkspaceProvider role="advisor">
        <Visit intent="advisor.intake.age" context={NO_CONTEXT} />
        <WorkspacePage title="Find a service" withThread>
          <p>Canvas text</p>
        </WorkspacePage>
      </WorkspaceProvider>,
    );

    const drawer = screen.getByRole('complementary', { name: 'Assistant' });
    expect(within(within(drawer).getByRole('log', { name: 'Conversation' })).getByText(AGE_REPLY)).toBeInTheDocument();
    expect(screen.getByText('Canvas text')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Hide the assistant' }));
    expect(screen.queryByRole('complementary', { name: 'Assistant' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Show the assistant' })).toBeInTheDocument();
  });

  it('WS-SHL-T04 with withThread false renders neither the drawer nor the assistant button, even when hidden is true', () => {
    store.set(HIDDEN_KEY, true);
    const report = vi.fn<(hidden: boolean) => void>();
    render(
      <WorkspaceProvider role="advisor">
        <Hidden report={report} />
        <WorkspacePage title="Capacity" withThread={false}>
          <p>Canvas text</p>
        </WorkspacePage>
      </WorkspaceProvider>,
    );

    expect(report).toHaveBeenLastCalledWith(true);
    expect(screen.getByText('Canvas text')).toBeInTheDocument();
    expect(screen.queryByRole('complementary', { name: 'Assistant' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Show the assistant' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Hide the assistant' })).toBeNull();
  });

  it('WS-SHL-T05 the frame gets the title, the organisation, the role word and a Sign out control when the role is set; with a null role there is no sign-out control and no role word', () => {
    const { unmount } = render(
      <WorkspaceProvider role="advisor-v2" organisation="Test Organisation">
        <WorkspacePage title="Find a service" withThread={false}>
          <p>Canvas text</p>
        </WorkspacePage>
      </WorkspaceProvider>,
    );

    const banner = screen.getByRole('banner');
    expect(within(banner).getByText('Find a service')).toBeInTheDocument();
    expect(within(banner).getByText('Test Organisation')).toBeInTheDocument();
    expect(within(banner).getByText('Advisor v2')).toBeInTheDocument();
    expect(within(banner).getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
    unmount();

    render(
      <WorkspaceProvider role={null}>
        <WorkspacePage title="Find a service" withThread={false}>
          <p>Canvas text</p>
        </WorkspacePage>
      </WorkspaceProvider>,
    );

    const bare = screen.getByRole('banner');
    expect(within(bare).getByText('Find a service')).toBeInTheDocument();
    expect(within(bare).queryByRole('button', { name: 'Sign out' })).toBeNull();
    expect(within(bare).queryByText('Advisor v2')).toBeNull();
  });
});
