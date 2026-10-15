export default function Logo({ className = 'h-7 w-7' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <defs><linearGradient id="logo-g" x1="2" y1="2" x2="30" y2="30" gradientUnits="userSpaceOnUse"><stop stopColor="#f2c46d" /><stop offset="1" stopColor="#f59e0b" /></linearGradient></defs>
      <rect width="32" height="32" rx="9" fill="url(#logo-g)" />
      <g stroke="#070a14" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M16 7v17.5M11.5 24.5h9M8 10.5h16"/><path d="m8 10.5-3 7a3.2 3.2 0 0 0 6 0l-3-7ZM24 10.5l-3 7a3.2 3.2 0 0 0 6 0l-3-7Z"/></g>
    </svg>
  )
}
