"use client";
import { useCompletion } from "ai/react";

export default function Editor() {
  const { completion, input, handleInputChange, handleSubmit } = useCompletion({ api: "/api/rewrite" });
  return (
    <form onSubmit={handleSubmit}>
      <textarea value={input} onChange={handleInputChange} />
      <button type="submit">Use AI to rewrite</button>
      <div className="preview">{completion}</div>
    </form>
  );
}
