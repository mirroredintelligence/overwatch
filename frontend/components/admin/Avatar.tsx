import styles from './People.module.css';

// A round monogram for a person: their initials on one of five soft tones, the tone chosen from the id so the
// same person is always the same colour. It is decoration (the name is always beside it), so it is hidden from
// assistive technology.

const TONES = 5;

function initialsOf(name: string | null, mail: string | null): string {
  const source = (name ?? '').trim() || (mail ?? '').split('@')[0] || '?';
  const words = source.split(/[\s._-]+/).filter(Boolean);
  const letters = words.length > 1 ? `${words[0]![0]}${words[words.length - 1]![0]}` : source.slice(0, 2);
  return letters.toUpperCase();
}

function toneOf(id: string): number {
  let hash = 0;
  for (const character of id) hash = (hash * 31 + character.charCodeAt(0)) % 997;
  return hash % TONES;
}

export function Avatar({ id, name, mail, size = 'md' }: { id: string; name: string | null; mail: string | null; size?: 'sm' | 'md' }) {
  return (
    <span className={`${styles.avatar} ${size === 'sm' ? styles.avatarSm : ''}`} data-tone={toneOf(id)} aria-hidden="true">
      {initialsOf(name, mail)}
    </span>
  );
}
