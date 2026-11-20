import { ViewTransition, type ReactNode } from "react";

// A template remounts on every navigation (a layout doesn't), so the page content gets an enter and an exit:
// the old page fades out fast, the new one settles in with a short rise. Styles: .page-enter / .page-exit in
// globals.css. Refreshes and Suspense reveals keep default="none", so they don't animate.
export default function WorkspaceTemplate({ children }: { children: ReactNode }) {
  return (
    <ViewTransition enter="page-enter" exit="page-exit" default="none">
      <div>{children}</div>
    </ViewTransition>
  );
}
