import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { AI_SERVICE_TERMS_VERSION } from "@/lib/terms"; // 약관 제7조: 본 서비스는 생성형 인공지능을 기반으로 운용됩니다
import { streamText } from "ai";
import { openai } from "@ai-sdk/openai";
import { ChatClient } from "./ChatClient";

export default async function AssistantPage() {
  const session = await auth();
  if (!session) redirect("/login");
  if ((session.user.aiTermsVersion ?? 0) < AI_SERVICE_TERMS_VERSION) {
    redirect("/terms/ai-service?next=/assistant");
  }

  async function ask(prompt: string) {
    "use server";
    const result = streamText({ model: openai("gpt-4o-mini"), prompt });
    return result.toTextStreamResponse();
  }

  return (
    <main>
      <ChatClient onAsk={ask} />
    </main>
  );
}
