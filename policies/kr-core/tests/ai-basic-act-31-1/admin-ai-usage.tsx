"use client";
import { useEffect, useState } from "react";

export default function UsageTable() {
  const [rows, setRows] = useState<{ day: string; tokens: number }[]>([]);

  useEffect(() => {
    fetch("/api/ai/usage?range=30d")
      .then((r) => r.json())
      .then(setRows);
  }, []);

  return (
    <table>
      <tbody>
        {rows.map((r) => (
          <tr key={r.day}>
            <td>{r.day}</td>
            <td>{r.tokens}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
