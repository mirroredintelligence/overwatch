import type { ReactNode } from 'react';
import { useId } from 'react';
import styles from './Card.module.css';

export type CardProps = {
  heading?: string;
  headingLevel?: 2 | 3 | 4 | 5 | 6;
  children?: ReactNode;
  dataEl?: string;
};

export function Card({ heading, headingLevel = 2, children, dataEl }: CardProps) {
  const headingId = useId();
  const Heading = `h${headingLevel}` as const;
  return (
    <section
      className={styles.card}
      aria-labelledby={heading ? headingId : undefined}
      data-el={dataEl}
    >
      {heading ? (
        <Heading id={headingId} className={styles.heading}>
          {heading}
        </Heading>
      ) : null}
      {children}
    </section>
  );
}
