import type { ReactNode } from "react";

type IconName =
  | "logo"
  | "library"
  | "chat"
  | "study"
  | "admin"
  | "settings"
  | "plus"
  | "send"
  | "stop"
  | "upload"
  | "file"
  | "trash"
  | "refresh"
  | "chevronLeft"
  | "chevronRight"
  | "chevronDown"
  | "close"
  | "copy"
  | "check"
  | "alert"
  | "external"
  | "menu"
  | "search"
  | "sparkle"
  | "logout"
  | "shield"
  | "page"
  | "quote"
  | "eye"
  | "book"
  | "clock"
  | "flask"
  | "thumbsUp"
  | "thumbsDown"
  | "panel";

const paths: Record<IconName, ReactNode> = {
  logo: (
    <>
      <path d="M6 3.5h8l4 4V20a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 6 20V5A1.5 1.5 0 0 1 7.5 3.5Z" />
      <path d="M14 3.8V8h4" />
      <path d="M9 12.5h5M9 16h3.5" />
    </>
  ),
  library: (
    <>
      <path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H9v16H5.5A1.5 1.5 0 0 1 4 18.5v-13Z" />
      <path d="M9 4h4.5A1.5 1.5 0 0 1 15 5.5v13a1.5 1.5 0 0 1-1.5 1.5H9" />
      <path d="M15 7l3.2.8a1.5 1.5 0 0 1 1.1 1.8l-2.8 10.2" />
    </>
  ),
  chat: <path d="M4.5 5.5A1.5 1.5 0 0 1 6 4h12a1.5 1.5 0 0 1 1.5 1.5v9A1.5 1.5 0 0 1 18 16H9l-4.5 4V5.5Z" />,
  study: (
    <>
      <path d="M3.5 9.5 12 4l8.5 5.5L12 15 3.5 9.5Z" />
      <path d="M6.5 11.5V17c0 1.2 2.5 2.5 5.5 2.5s5.5-1.3 5.5-2.5v-5.5" />
      <path d="M20.5 9.5V15" />
    </>
  ),
  admin: (
    <>
      <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1.11-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09a1.7 1.7 0 0 0 1.55-1.11 1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.55V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9c.2.6.75 1 1.39 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.51 1Z" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  send: (
    <>
      <path d="M12 19V5M6.5 10.5 12 5l5.5 5.5" />
    </>
  ),
  stop: <rect x="7" y="7" width="10" height="10" rx="1.5" />,
  upload: (
    <>
      <path d="M12 16V4M7.5 8.5 12 4l4.5 4.5" />
      <path d="M4 15v3.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V15" />
    </>
  ),
  file: (
    <>
      <path d="M6.5 3.5h7l4 4V20a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 5.5 20V5A1.5 1.5 0 0 1 7 3.5Z" />
      <path d="M13.5 3.8V8h3.8" />
    </>
  ),
  trash: (
    <>
      <path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
      <path d="M6 7l1 13h10l1-13M10 11v5M14 11v5" />
    </>
  ),
  refresh: (
    <>
      <path d="M20 11a8 8 0 1 0-2.5 6.4" />
      <path d="M20 4v7h-7" />
    </>
  ),
  chevronLeft: <path d="M14.5 6 9 12l5.5 6" />,
  chevronRight: <path d="M9.5 6 15 12l-5.5 6" />,
  chevronDown: <path d="M6 9.5 12 15l6-5.5" />,
  close: <path d="M6 6l12 12M18 6 6 18" />,
  copy: (
    <>
      <rect x="8" y="8" width="12" height="12" rx="2" />
      <path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" />
    </>
  ),
  check: <path d="M4.5 12.5 9 17l10.5-10.5" />,
  alert: (
    <>
      <path d="M12 8v5M12 16.5v.1" />
      <circle cx="12" cy="12" r="9" />
    </>
  ),
  external: (
    <>
      <path d="M14 4h6v6M20 4l-9 9" />
      <path d="M19 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 5 18.5v-11A1.5 1.5 0 0 1 6.5 6H11" />
    </>
  ),
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  search: (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M16 16l4.5 4.5" />
    </>
  ),
  sparkle: (
    <>
      <path d="M12 3.5 13.8 9l5.7 1.8-5.7 1.8L12 18.5l-1.8-5.9L4.5 10.8 10.2 9 12 3.5Z" />
      <path d="M18.5 16.5l.7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7.7-2.3Z" />
    </>
  ),
  logout: (
    <>
      <path d="M10 5H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h4" />
      <path d="M16 8l4 4-4 4M20 12H9" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3.5 19 6v6c0 4.2-2.9 7.5-7 8.5-4.1-1-7-4.3-7-8.5V6l7-2.5Z" />
      <path d="M9 12l2 2 4-4" />
    </>
  ),
  page: (
    <>
      <path d="M6.5 3.5h7l4 4V20a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 5.5 20V5A1.5 1.5 0 0 1 7 3.5Z" />
      <path d="M13.5 3.8V8h3.8M9 12h6M9 16h6" />
    </>
  ),
  quote: (
    <>
      <path d="M8.5 11H5.5a1 1 0 0 1-1-1V7.5a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1V13c0 2-1 3.5-3 4.5" />
      <path d="M18.5 11h-3a1 1 0 0 1-1-1V7.5a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1V13c0 2-1 3.5-3 4.5" />
    </>
  ),
  eye: (
    <>
      <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
  book: (
    <>
      <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15.5H6.5A2.5 2.5 0 0 0 4 21V5.5Z" />
      <path d="M4 18.5A2.5 2.5 0 0 1 6.5 16H20" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </>
  ),
  flask: (
    <>
      <path d="M9 3.5h6M10 3.5v6L4.8 18a2 2 0 0 0 1.7 3h11a2 2 0 0 0 1.7-3L14 9.5v-6" />
      <path d="M7.5 14h9" />
    </>
  ),
  thumbsUp: (
    <>
      <path d="M7 20V10l4-6.5c1.4.4 2 1.3 2 2.6V9h5.2a2 2 0 0 1 2 2.4l-1.5 7A2 2 0 0 1 16.7 20H7Z" />
      <path d="M3 10h4v10H3z" />
    </>
  ),
  thumbsDown: (
    <>
      <path d="M17 4v10l-4 6.5c-1.4-.4-2-1.3-2-2.6V15H5.8a2 2 0 0 1-2-2.4l1.5-7A2 2 0 0 1 7.3 4H17Z" />
      <path d="M21 14h-4V4h4z" />
    </>
  ),
  panel: (
    <>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
      <path d="M14.5 4.5v15" />
    </>
  ),
};

export function Icon({
  name,
  size = 18,
  strokeWidth = 1.8,
  className,
}: {
  name: IconName;
  size?: number;
  strokeWidth?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      {paths[name]}
    </svg>
  );
}

export type { IconName };
