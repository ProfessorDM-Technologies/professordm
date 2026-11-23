"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";

// Simple line icons (brand guide §05: clean line icons over clip-art). Used by the mobile dock.
const ICONS: Record<string, ReactNode> = {
  "/": <path d="M4 10.5 12 4l8 6.5V20h-5v-6H9v6H4v-9.5Z" />,
  "/search": <path d="M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm9 2-4-4" />,
  "/inbox": <path d="M4 5h16v11H9l-5 4V5Zm7.2 3.7a1.8 1.8 0 1 1 2.5 1.7c-.5.3-.9.7-.9 1.3m.1 2.1h.01" />,
};

// Profile lives in the account menu (top right), not here.
const NAV_ITEMS = [
  { href: "/", label: "Home" },
  { href: "/search", label: "Search" },
  { href: "/inbox", label: "Inbox" },
] as const;

// Same curve as --ease-spring in globals.css: a quick move with a small overshoot, then settle.
const SPRING =
  "linear(0, 0.009, 0.035 2.1%, 0.141 4.4%, 0.723 12.9%, 0.938 16.7%, 1.017 19.4%, 1.067, 1.099 24.3%, 1.108 26%, 1.104, 1.088 30.6%, 1.03 37.6%, 1.007 41.3%, 0.991 46.4%, 0.996 58.1%, 1.001 67.5%, 1)";

function matches(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

// Answers and Ask the Expert are reached from Home, so they light it up. Search has its own tab.
function isActive(pathname: string, href: string) {
  if (href === "/" && (matches(pathname, "/entry") || matches(pathname, "/ask-expert"))) return true;
  return matches(pathname, href);
}

function reducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

type LensBox = { index: number; x: number; y: number; w: number; h: number };

// "island": the floating glass bar at the top (xl and up). "dock": the same bar docked at the bottom below xl.
// A glass lens marks the current page and springs to the next one as soon as it is tapped, stretching while it
// travels, like the iOS 26 tab bar. The bar shrinks while you scroll down and comes back when you scroll up.
export function ConsumerNav({ variant, className = "" }: { variant: "island" | "dock"; className?: string }) {
  const pathname = usePathname();
  const items = NAV_ITEMS;
  const routeIndex = items.findIndex((item) => isActive(pathname, item.href));

  // The tapped item, until the route catches up. Dropped as soon as the path changes, so Back to the page it was
  // tapped on doesn't bring it back.
  const [tapped, setTapped] = useState<{ index: number; from: string } | null>(null);
  if (tapped && tapped.from !== pathname) setTapped(null);
  const shown = tapped && tapped.from === pathname ? tapped.index : routeIndex;

  const navRef = useRef<HTMLElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const lensRef = useRef<HTMLLIElement>(null);
  const linkRefs = useRef<(HTMLAnchorElement | null)[]>([]);
  const lastBox = useRef<LensBox | null>(null);

  // Move the lens to the shown item: spring with a stretch when it changes, jump when it is the first placement.
  useLayoutEffect(() => {
    const lens = lensRef.current;
    const link = shown >= 0 ? linkRefs.current[shown] : null;
    if (!lens) return;
    if (!link) {
      lens.style.opacity = "0";
      lastBox.current = null;
      return;
    }

    const box: LensBox = { index: shown, x: link.offsetLeft, y: link.offsetTop, w: link.offsetWidth, h: link.offsetHeight };
    const place = (b: LensBox) => {
      lens.style.width = `${b.w}px`;
      lens.style.height = `${b.h}px`;
      lens.style.transform = `translate(${b.x}px, ${b.y}px)`;
    };
    place(box);
    lens.style.opacity = "1";

    const from = lastBox.current;
    if (from && from.index !== shown && !reducedMotion()) {
      // Halfway there the lens is longer than both items and slightly flattened, then it springs into place.
      const stretch = Math.min(Math.abs(box.x - from.x) * 0.3, 44);
      const midW = (from.w + box.w) / 2 + stretch;
      const midX = (from.x + box.x) / 2 + (from.w + box.w) / 4 - midW / 2;
      lens.animate(
        [
          { transform: `translate(${from.x}px, ${from.y}px)`, width: `${from.w}px`, scale: "1 1" },
          { transform: `translate(${midX}px, ${box.y}px)`, width: `${midW}px`, scale: "1 0.88", offset: 0.4 },
          { transform: `translate(${box.x}px, ${box.y}px)`, width: `${box.w}px`, scale: "1 1" },
        ],
        { duration: 560, easing: SPRING },
      );
    }
    lastBox.current = box;
  }, [shown, variant]);

  // Keep the lens on its item when the bar changes size (web font swap, window resize).
  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const observer = new ResizeObserver(() => {
      const box = lastBox.current;
      const link = box ? linkRefs.current[box.index] : null;
      const lens = lensRef.current;
      if (!box || !link || !lens) return;
      const next = { ...box, x: link.offsetLeft, y: link.offsetTop, w: link.offsetWidth, h: link.offsetHeight };
      lens.style.width = `${next.w}px`;
      lens.style.height = `${next.h}px`;
      lens.style.transform = `translate(${next.x}px, ${next.y}px)`;
      lastBox.current = next;
    });
    observer.observe(list);
    return () => observer.disconnect();
  }, []);

  // Shrink while scrolling down past the first screenful, restore on any scroll up or near the top.
  useEffect(() => {
    const nav = navRef.current;
    if (!nav) return;
    let lastY = window.scrollY;
    let frame = 0;
    const onScroll = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        const y = window.scrollY;
        if (y < 60 || y < lastY - 6) nav.dataset.compact = "false";
        else if (y > lastY + 6) nav.dataset.compact = "true";
        lastY = y;
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      cancelAnimationFrame(frame);
    };
  }, []);

  const press = (pressed: boolean) => {
    if (lensRef.current) lensRef.current.dataset.pressed = String(pressed);
  };

  function onLinkClick(event: MouseEvent<HTMLAnchorElement>, index: number) {
    // Opening in a new tab or window doesn't change this page.
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
    setTapped({ index, from: pathname });
  }

  return (
    <nav
      ref={navRef}
      aria-label="Main"
      data-compact="false"
      className={`pdm-glass pdm-shrink rounded-full p-1 ${variant === "dock" ? "pdm-vt-dock origin-bottom" : "pdm-vt-island origin-top"} ${className}`}
    >
      <ul ref={listRef} className="relative flex items-center">
        <li ref={lensRef} aria-hidden="true" data-pressed="false" className="pdm-lens opacity-0" />
        {items.map((item, index) => {
          const active = index === shown;
          return (
            <li key={item.href} className={variant === "dock" ? "flex-1" : undefined}>
              <Link
                ref={(element) => {
                  linkRefs.current[index] = element;
                }}
                href={item.href}
                aria-current={routeIndex === index ? "page" : undefined}
                onClick={(event) => onLinkClick(event, index)}
                onPointerDown={() => press(true)}
                onPointerUp={() => press(false)}
                onPointerCancel={() => press(false)}
                onPointerLeave={() => press(false)}
                className={
                  variant === "island"
                    ? `relative z-10 flex min-h-9 items-center rounded-full px-3.5 font-display text-[0.8125rem] font-semibold transition-colors duration-300 ease-pdm ${
                        active ? "text-pdm-heading" : "text-pdm-muted hover:text-pdm-ink"
                      }`
                    : `relative z-10 flex min-h-13 flex-col items-center justify-center gap-0.5 rounded-full px-1 text-[0.6875rem] font-semibold transition-colors duration-300 ease-pdm ${
                        active ? "text-pdm-heading" : "text-pdm-muted"
                      }`
                }
              >
                {variant === "dock" ? (
                  <svg
                    aria-hidden="true"
                    viewBox="0 0 24 24"
                    className={`size-5 transition-colors duration-300 ease-pdm ${active ? "text-pdm-teal" : ""}`}
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.7"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    {ICONS[item.href]}
                  </svg>
                ) : null}
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
