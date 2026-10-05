export function Mark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      <circle cx="32" cy="32" r="23" fill="none" stroke="rgba(94,234,212,0.35)" strokeWidth="1" />
      <circle cx="32" cy="32" r="15" fill="none" stroke="#5eead4" strokeWidth="1.8" />
      <circle cx="32" cy="32" r="3.5" fill="#f6f8fc" />
      <path d="M32 4v8M32 52v8M4 32h8M52 32h8" stroke="#5eead4" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}
