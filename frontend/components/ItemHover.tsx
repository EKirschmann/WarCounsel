"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { apiGet } from "@/lib/api";

interface AcqLine {
  text: string;
  kind: "zone" | "entry" | "note";
}
interface Acquisition {
  stats?: string | null;
  item: string;
  sections: { label: string; lines: AcqLine[] }[];
  available: boolean;
}

/** Session-wide client cache — acquisition data is static per item. */
const acqCache = new Map<string, Acquisition>();

const baseName = (n: string) => n.replace(/\s*\+\d+\s*$/, "");

/** An item name that reveals a where-to-get-it card on hover
 *  (wiki-mined Drops From / Sold by / quests / crafting). */
export function ItemHover({ name, children }: { name: string; children?: React.ReactNode }) {
  const [acq, setAcq] = useState<Acquisition | null>(null);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const host = useRef<HTMLSpanElement | null>(null);
  const card = useRef<HTMLSpanElement | null>(null);
  const timer = useRef<number | null>(null);

  const load = async () => {
    const base = baseName(name);
    const hit = acqCache.get(base);
    if (hit) {
      setAcq(hit);
      return;
    }
    try {
      const d = await apiGet<Acquisition>(
        `/api/item-acquisition?name=${encodeURIComponent(base)}`,
      );
      acqCache.set(base, d);
      setAcq(d);
    } catch {
      /* backend offline — the card just says "looking up" until close */
    }
  };

  // The card is rendered into document.body, not beside the name it
  // belongs to. Two things in the panel it used to live in made an
  // absolutely-positioned tooltip unusable, and neither is worth undoing:
  // `.panel` sets backdrop-filter, which creates a STACKING CONTEXT that
  // z-index cannot escape, so the card could never rise above a
  // neighbouring panel; and `.panel-body` scrolls, so the card was CLIPPED
  // at the panel edge. Reported as the popup sitting behind the text below
  // it and being too faint to read -- which is what a clipped, occluded
  // card looks like.
  //
  // Positioned on layout rather than on paint: measuring after the browser
  // has placed the card but before it is shown avoids a visible jump from
  // the corner of the screen.
  useLayoutEffect(() => {
    if (!open || !host.current) return;
    const place = () => {
      const h = host.current?.getBoundingClientRect();
      const c = card.current?.getBoundingClientRect();
      if (!h) return;
      const w = c?.width ?? 260;
      const ch = c?.height ?? 120;
      // Keep it on screen: flip above when there is no room below, and
      // pull back from the right edge rather than letting it overflow.
      const below = window.innerHeight - h.bottom;
      const top = below < ch + 12 && h.top > ch + 12 ? h.top - ch - 6 : h.bottom + 4;
      const left = Math.max(6, Math.min(h.left, window.innerWidth - w - 10));
      setPos({ left, top });
    };
    place();
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open, acq]);

  const enter = () => {
    timer.current = window.setTimeout(() => {
      setOpen(true);
      void load();
    }, 300);
  };
  const leave = () => {
    if (timer.current) window.clearTimeout(timer.current);
    setOpen(false);
  };
  useEffect(
    () => () => {
      if (timer.current) window.clearTimeout(timer.current);
    },
    [],
  );

  return (
    <span className="item-hover" ref={host} onMouseEnter={enter} onMouseLeave={leave}>
      {children ?? name}
      {open &&
        createPortal(
        <span
          className="item-hover-card"
          role="tooltip"
          ref={card}
          style={pos ? { left: pos.left, top: pos.top } : { opacity: 0 }}
        >
          <span className="item-hover-title">{baseName(name)}</span>
          {!acq ? (
            <span className="item-hover-note">looking up…</span>
          ) : !acq.available ? (
            <span className="item-hover-note">no acquisition data on the wiki</span>
          ) : (
            <>
              {/* Base (+0) stats first: "is this worth farming for" is the
                  question the card is opened to answer, and where it drops
                  cannot answer it. */}
              {acq.stats && (
                <span className="item-hover-stats">
                  {acq.stats.split(";").map((part, i) => (
                    <span key={i}>{part.trim()}</span>
                  ))}
                </span>
              )}
              {acq.sections.map((s) => (
                <span key={s.label} className="item-hover-sec">
                  <span className="item-hover-label">{s.label}</span>
                  {s.lines.map((l, i) => (
                    <span key={i} className="item-hover-line" data-kind={l.kind}>
                      {l.text}
                    </span>
                  ))}
                </span>
              ))}
            </>
          )}
        </span>,
        document.body,
      )}
    </span>
  );
}