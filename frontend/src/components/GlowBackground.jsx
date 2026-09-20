/**
 * Ambient orange glow. Render inside a `position: relative` container; it fills the container
 * and sits behind content that has `.above` (z-index 1).
 *
 * position: 'corner' (top-left, subtle — auth), 'right' (hero-style), 'behind' (a band behind
 * a row of cards). `soft` halves the intensity.
 */
export default function GlowBackground({ position = 'corner', soft = false, className = '' }) {
  return (
    <div className={`glow-wrap glow-${position} ${soft ? 'glow-soft' : ''} ${className}`} aria-hidden="true">
      <div className="glow glow-a" />
      <div className="glow glow-b" />
      {position === 'behind' && <div className="glow glow-c" />}
    </div>
  )
}
