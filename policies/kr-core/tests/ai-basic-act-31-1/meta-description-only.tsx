import Head from "next/head";
import { useChat } from "ai/react";

export default function HelpPage() {
  const { messages, input, handleInputChange, handleSubmit } = useChat();
  return (
    <>
      <Head>
        <title>Help · AI-powered assistant</title>
        <meta name="description" content="AI-powered assistant for order and refund questions" />
      </Head>
      <main>
        <h1>고객센터</h1>
        <img src="/bot.png" alt="이 챗봇은 인공지능을 기반으로 운영됩니다" />
        <form onSubmit={handleSubmit}>
          {messages.map((m) => (
            <p key={m.id}>{m.content}</p>
          ))}
          <input value={input} onChange={handleInputChange} aria-label="이 상담은 AI 기반 서비스입니다" />
        </form>
      </main>
    </>
  );
}
