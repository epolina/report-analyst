// The inline SVG icons the components share.
import { type ReactNode } from "react";

const icon = (paths: ReactNode) => (
  <svg
    className="ui-icon"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.75"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    {paths}
  </svg>
);

export const ICONS = {
  chevron: icon(<path d="m9 6 6 6-6 6" />),
  upload: icon(<path d="M12 16V4m0 0-4 4m4-4 4 4M5 20h14" />),
  back: icon(<path d="m15 6-6 6 6 6" />),
  file: icon(
    <>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5" />
    </>,
  ),
};
