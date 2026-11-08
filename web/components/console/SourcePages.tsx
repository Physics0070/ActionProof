"use client";
import { useState } from "react";
import type { Schemas } from "@/lib/api";
import { pagePngUrl } from "@/lib/api";
import { PAGE_ZOOM, parseSource, type Bbox } from "@/lib/console-format";
import { MonoLabel } from "@/components/ui/MonoLabel";

type Claim = Schemas["ClaimView"];
type Cited = { name: string; bbox: Bbox };
type PageRef = { doc: string; page: number; cited: Cited[] };

/** Pages the server will render: those holding a DIRECT claim that passed verification. */
export function citedPages(claims: Claim[]): PageRef[] {
  const pages = new Map<string, PageRef>();
  for (const c of claims) {
    const s = parseSource(c.source);
    if (c.claim !== "DIRECT" || !c.verification?.ok || !s.doc || !s.page || !s.bbox) continue;
    const key = `${s.doc}#${s.page}`;
    const ref = pages.get(key) ?? { doc: s.doc, page: s.page, cited: [] };
    ref.cited.push({ name: c.name, bbox: s.bbox });
    pages.set(key, ref);
  }
  return [...pages.values()];
}

function Page({ hash, ref_, active, onActive }: { hash: string; ref_: PageRef; active: string | null; onActive: (n: string | null) => void }) {
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const [failed, setFailed] = useState(false);
  return (
    <figure className="c-pagefig">
      <figcaption>
        <MonoLabel>
          {ref_.doc} · page {ref_.page}
        </MonoLabel>
      </figcaption>
      {failed ? (
        <p role="alert" className="t-muted">
          The page image is unavailable (the server found no verified citation here).
        </p>
      ) : (
        <div className="c-page">
          {/* eslint-disable-next-line @next/next/no-img-element -- cookie-authenticated, no-store PNG; next/image cannot proxy it */}
          <img
            src={pagePngUrl(hash, ref_.page, ref_.doc)}
            alt={`${ref_.doc}, page ${ref_.page}, with the cited source spans outlined`}
            onLoad={(e) => setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
            onError={() => setFailed(true)}
          />
          {/* Percent geometry: PDF points * zoom / natural pixels, so it follows any rendered size with no resize code. */}
          {natural
            ? ref_.cited.map((c) => {
                const [x0, top, x1, bottom] = c.bbox;
                return (
                  <div
                    key={c.name}
                    className="c-box"
                    data-active={active === c.name}
                    title={c.name}
                    onMouseEnter={() => onActive(c.name)}
                    onMouseLeave={() => onActive(null)}
                    style={{
                      left: `${((x0 * PAGE_ZOOM) / natural.w) * 100}%`,
                      top: `${((top * PAGE_ZOOM) / natural.h) * 100}%`,
                      width: `${(((x1 - x0) * PAGE_ZOOM) / natural.w) * 100}%`,
                      height: `${(((bottom - top) * PAGE_ZOOM) / natural.h) * 100}%`,
                    }}
                  >
                    <span className="c-boxlabel mono-label">{c.name}</span>
                  </div>
                );
              })
            : null}
        </div>
      )}
    </figure>
  );
}

export function SourcePages({ hash, claims, active, onActive }: { hash: string; claims: Claim[]; active: string | null; onActive: (n: string | null) => void }) {
  const pages = citedPages(claims);
  if (!pages.length) return <p className="t-muted">No verified document span to show for this request.</p>;
  return (
    <div className="c-pages">
      {pages.map((p) => (
        <Page key={`${p.doc}#${p.page}`} hash={hash} ref_={p} active={active} onActive={onActive} />
      ))}
    </div>
  );
}
