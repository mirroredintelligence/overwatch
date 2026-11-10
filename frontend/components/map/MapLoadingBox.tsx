import { MapPlaceholder } from './MapPlaceholder';
import styles from './mapPlaceholder.module.css';

/** The map's box, empty and loading, for the time the options are being read: the same 3 to 2 shape the map has
    (so the page does not jump when the map arrives), with no land because no place is known yet. */
export function MapLoadingBox() {
  return (
    <div className={styles.box}>
      <MapPlaceholder fit={[]} />
    </div>
  );
}
