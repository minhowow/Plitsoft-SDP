import React, { useEffect } from "react";

export function SearchResults({ items, onImpression }) {
  useEffect(() => {
    const seen = [];
    items.forEach((it) => {
      if (it.sponsored) seen.push(it.id);
    });
    if (seen.length > 0) navigator.sendBeacon("/api/impressions", JSON.stringify(seen));
    onImpression?.(seen);
  }, [items]);

  return (
    <ul>
      {items.map((it) => (
        <li key={it.id}>
          {it.sponsored && <span className="badge">[광고]</span>}
          <a href={it.url}>{it.title}</a>
        </li>
      ))}
    </ul>
  );
}
