import styles from './Thread.module.css';

// The collapsed assistant: shown in place of the drawer when the person has hidden it.
export function AssistantButton({ onShow }: { onShow: () => void }) {
  return (
    <button
      type="button"
      className={styles.assistantButton}
      aria-label="Show the assistant"
      data-el="WS-ASSISTANT-BUTTON"
      onClick={onShow}
    >
      <span className={styles.spark} aria-hidden="true">
        ✦
      </span>
      Assistant
    </button>
  );
}
