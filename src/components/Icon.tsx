import type { SVGProps } from "react";

type IconName =
  | "spark"
  | "chat"
  | "cube"
  | "plus"
  | "search"
  | "trash"
  | "settings"
  | "play"
  | "upload"
  | "image"
  | "send"
  | "download"
  | "copy"
  | "close"
  | "check"
  | "refresh"
  | "stop"
  | "wand"
  | "layers"
  | "grid"
  | "user"
  | "bot"
  | "alert"
  | "box"
  | "cpu"
  | "file"
  | "clock";

const paths: Record<IconName, JSX.Element> = {
  spark: (
    <>
      <path d="M12 2l1.8 6.2L20 10l-6.2 1.8L12 18l-1.8-6.2L4 10l6.2-1.8L12 2z" />
      <path d="M19 16l.7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7L19 16z" />
    </>
  ),
  chat: <path d="M20 15.5a3 3 0 0 1-3 3H8l-4 3v-15a3 3 0 0 1 3-3h10a3 3 0 0 1 3 3v9z" />,
  cube: (
    <>
      <path d="M12 2.8l8 4.4v9.6l-8 4.4-8-4.4V7.2l8-4.4z" />
      <path d="M4.5 7.5L12 12l7.5-4.5" />
      <path d="M12 12v8.5" />
    </>
  ),
  plus: (
    <>
      <path d="M12 5v14" />
      <path d="M5 12h14" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="M20 20l-4-4" />
    </>
  ),
  trash: (
    <>
      <path d="M4 7h16" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
      <path d="M6 7l1 14h10l1-14" />
      <path d="M9 7V4h6v3" />
    </>
  ),
  settings: (
    <>
      <path d="M12 8.2a3.8 3.8 0 1 0 0 7.6 3.8 3.8 0 0 0 0-7.6z" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2 3.4-.2-.1a1.7 1.7 0 0 0-1.9.2l-.7.4a1.7 1.7 0 0 0-1 1.5v.2h-4v-.2a1.7 1.7 0 0 0-1-1.5l-.7-.4a1.7 1.7 0 0 0-1.9-.2l-.2.1-2-3.4.1-.1A1.7 1.7 0 0 0 4.6 15v-.8a1.7 1.7 0 0 0-.3-1.9l-.1-.1 2-3.4.2.1a1.7 1.7 0 0 0 1.9-.2l.7-.4a1.7 1.7 0 0 0 1-1.5v-.2h4v.2a1.7 1.7 0 0 0 1 1.5l.7.4a1.7 1.7 0 0 0 1.9.2l.2-.1 2 3.4-.1.1a1.7 1.7 0 0 0-.3 1.9v.8z" />
    </>
  ),
  play: <path d="M8 5v14l11-7-11-7z" />,
  upload: (
    <>
      <path d="M12 16V4" />
      <path d="M7 9l5-5 5 5" />
      <path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
    </>
  ),
  image: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2.5" />
      <circle cx="8.5" cy="9.5" r="1.5" />
      <path d="M21 16l-5-5-4 4-2-2-7 7" />
    </>
  ),
  send: (
    <>
      <path d="M4 12l16-8-5 16-3-6-8-2z" />
      <path d="M12 14l8-10" />
    </>
  ),
  download: (
    <>
      <path d="M12 4v11" />
      <path d="M7 10l5 5 5-5" />
      <path d="M5 20h14" />
    </>
  ),
  copy: (
    <>
      <rect x="8" y="8" width="12" height="12" rx="2" />
      <path d="M4 16V6a2 2 0 0 1 2-2h10" />
    </>
  ),
  close: (
    <>
      <path d="M6 6l12 12" />
      <path d="M18 6L6 18" />
    </>
  ),
  check: <path d="M5 12.5l4.5 4.5L19 7" />,
  refresh: (
    <>
      <path d="M20 12a8 8 0 0 1-14.2 5" />
      <path d="M4 12A8 8 0 0 1 18.2 7" />
      <path d="M18 3v4h-4" />
      <path d="M6 21v-4h4" />
    </>
  ),
  stop: <rect x="7" y="7" width="10" height="10" rx="2" />,
  wand: (
    <>
      <path d="M4 20l10.5-10.5" />
      <path d="M13 4l1 3 3 1-3 1-1 3-1-3-3-1 3-1 1-3z" />
      <path d="M19 2l.6 1.8L21.5 4.5l-1.9.7L19 7l-.7-1.8-1.8-.7 1.8-.7L19 2z" />
    </>
  ),
  layers: (
    <>
      <path d="M12 3l9 5-9 5-9-5 9-5z" />
      <path d="M5 12l7 4 7-4" />
      <path d="M5 16l7 4 7-4" />
    </>
  ),
  grid: (
    <>
      <rect x="4" y="4" width="6" height="6" rx="1.5" />
      <rect x="14" y="4" width="6" height="6" rx="1.5" />
      <rect x="4" y="14" width="6" height="6" rx="1.5" />
      <rect x="14" y="14" width="6" height="6" rx="1.5" />
    </>
  ),
  user: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4.5 20a7.5 7.5 0 0 1 15 0" />
    </>
  ),
  bot: (
    <>
      <rect x="5" y="8" width="14" height="11" rx="3" />
      <path d="M12 8V4" />
      <path d="M9 13h.01" />
      <path d="M15 13h.01" />
      <path d="M9.5 16h5" />
    </>
  ),
  alert: (
    <>
      <path d="M12 3l10 18H2L12 3z" />
      <path d="M12 9v5" />
      <path d="M12 17h.01" />
    </>
  ),
  box: (
    <>
      <path d="M4 8l8-4 8 4v8l-8 4-8-4V8z" />
      <path d="M4 8l8 4 8-4" />
      <path d="M12 12v8" />
    </>
  ),
  cpu: (
    <>
      <rect x="7" y="7" width="10" height="10" rx="2" />
      <path d="M10 10h4v4h-4z" />
      <path d="M4 9h3" />
      <path d="M4 15h3" />
      <path d="M17 9h3" />
      <path d="M17 15h3" />
      <path d="M9 4v3" />
      <path d="M15 4v3" />
      <path d="M9 17v3" />
      <path d="M15 17v3" />
    </>
  ),
  file: (
    <>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5" />
      <path d="M8 13h8" />
      <path d="M8 17h5" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
};

export default function Icon({
  name,
  size = 18,
  strokeWidth = 1.8,
  ...props
}: SVGProps<SVGSVGElement> & {
  name: IconName;
  size?: number;
  strokeWidth?: number;
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
      {...props}
    >
      {paths[name]}
    </svg>
  );
}
