import type { ButtonHTMLAttributes, ReactNode } from 'react';
import styles from './Button.module.css';

export type ButtonVariant = 'primary' | 'secondary' | 'neutral';

export type ButtonProps = {
  variant: ButtonVariant;
  children: ReactNode;
  /** Disables the button and sets aria-busy, so an impatient second click does nothing. */
  busy?: boolean;
  /** Disables the button without the busy state (for example, until a figure is chosen). */
  disabled?: boolean;
  /** Renders a link instead of a button. */
  href?: string;
  dataEl?: string;
  /** The accessible name, when the visible words need more to say what the button acts on. */
  ariaLabel?: string;
  onClick?: ButtonHTMLAttributes<HTMLButtonElement>['onClick'];
  type?: 'button' | 'submit';
};

export function Button({
  variant,
  children,
  busy = false,
  disabled = false,
  href,
  dataEl,
  ariaLabel,
  onClick,
  type = 'button',
}: ButtonProps) {
  const className = `${styles.button} ${styles[variant]}`;
  if (href !== undefined) {
    return (
      <a className={className} href={href} data-el={dataEl} data-variant={variant} aria-label={ariaLabel}>
        {children}
      </a>
    );
  }
  return (
    <button
      type={type}
      className={className}
      disabled={busy || disabled}
      aria-busy={busy ? 'true' : undefined}
      aria-label={ariaLabel}
      onClick={onClick}
      data-el={dataEl}
      data-variant={variant}
    >
      {children}
    </button>
  );
}
