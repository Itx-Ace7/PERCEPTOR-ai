export function Mark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      <circle cx="32" cy="32" r="23" fill="none" stroke="rgba(122,243,214,0.35)" strokeWidth="1" />
      <circle cx="32" cy="32" r="15" fill="none" stroke="#7af3d6" strokeWidth="1.8" />
      <circle cx="32" cy="32" r="3.5" fill="#f4f7fb" />
      <path d="M32 4v8M32 52v8M4 32h8M52 32h8" stroke="#7af3d6" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}
