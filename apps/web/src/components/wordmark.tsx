export function Wordmark() {
  return (
    <span className="flex items-center gap-2 px-2">
      <svg
        width="22"
        height="22"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        className="text-brand"
        aria-hidden="true"
      >
        <path d="M4 5.5C4 4.7 4.7 4 5.5 4H11v16H5.5C4.7 20 4 19.3 4 18.5z" />
        <path d="M13 4h5.5c.8 0 1.5.7 1.5 1.5v13c0 .8-.7 1.5-1.5 1.5H13z" />
      </svg>
      <span className="font-serif text-wordmark font-medium">Docent</span>
    </span>
  );
}
