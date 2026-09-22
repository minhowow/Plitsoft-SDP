import { streamText, convertToCoreMessages } from "ai";
import { openai } from "@ai-sdk/openai";

export const maxDuration = 30;

export async function POST(req: Request) {
  const { messages } = await req.json();
  const result = streamText({
    model: openai("gpt-4o-mini"),
    system: "You are a helpful support assistant.",
    messages: convertToCoreMessages(messages),
  });
  return result.toDataStreamResponse();
}
