"use client";
import { ChatOpenAI } from "@langchain/openai";
import { StringOutputParser } from "@langchain/core/output_parsers";
import { ChatPromptTemplate } from "@langchain/core/prompts";
import { useState } from "react";

const prompt = ChatPromptTemplate.fromTemplate("다음 글을 한 문단으로 요약해 줘:\n\n{text}");
const chain = prompt.pipe(new ChatOpenAI({ model: "gpt-4o-mini" })).pipe(new StringOutputParser());

export default function SummaryBox() {
  const [text, setText] = useState("");
  const [summary, setSummary] = useState("");

  async function run() {
    setSummary(await chain.invoke({ text }));
  }

  return (
    <section>
      <h2>회의록 요약</h2>
      <textarea value={text} onChange={(e) => setText(e.target.value)} />
      <button onClick={run}>요약하기</button>
      <p>{summary}</p>
    </section>
  );
}
