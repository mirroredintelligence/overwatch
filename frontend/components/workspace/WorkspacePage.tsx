'use client';

import type { ReactElement, ReactNode } from 'react';
import { V2_BROWSE_NOTE } from '@/lib/advisor/v2/overview';
import { AssistantButton } from './AssistantButton';
import { ThreadDrawer } from './ThreadDrawer';
import { WorkspaceFrame } from './WorkspaceFrame';
import { useWorkspace } from './WorkspaceProvider';

// The page-level wrapper (DEC-1376, WS-SHL): the frame around one page, with the assistant drawer when the page has a
// thread and the person has not hidden it, or the assistant button in its place when they have. The page passes its
// triage card; the messages, chips and summary come from the provider, so a visit made by any page shows here.

export type WorkspacePageProps = {
  title: string;
  backHref?: string;
  backLabel?: string;
  action?: { label: string; href: string; onClick?: () => void };
  withThread: boolean;
  card?: ReactNode;
  children: ReactNode;
};

export function WorkspacePage({ title, backHref, backLabel, action, withThread, card, children }: WorkspacePageProps): ReactElement {
  const { identity, messages, summary, chips, hidden, hide, show } = useWorkspace();
  const drawerShown = withThread && !hidden;
  const thread = drawerShown ? (
    <ThreadDrawer messages={messages} summary={summary} chips={chips} card={card} onHide={hide} />
  ) : null;
  const assistantButton = withThread && hidden ? <AssistantButton onShow={show} /> : null;

  return (
    <WorkspaceFrame
      title={title}
      organisation={identity.organisation}
      backHref={backHref}
      backLabel={backLabel}
      action={action}
      role={identity.role ?? undefined}
      roles={identity.roles}
      showSignOut={identity.role !== null}
      thread={thread}
      assistantButton={assistantButton}
      footer={V2_BROWSE_NOTE}
    >
      {children}
    </WorkspaceFrame>
  );
}
