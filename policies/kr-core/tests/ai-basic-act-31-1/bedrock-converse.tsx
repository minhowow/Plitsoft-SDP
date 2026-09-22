import { BedrockRuntimeClient, ConverseCommand } from "@aws-sdk/client-bedrock-runtime";

const client = new BedrockRuntimeClient({ region: "ap-northeast-2" });

export default async function ReviewDigest({ productId }: { productId: string }) {
  const out = await client.send(
    new ConverseCommand({
      modelId: "anthropic.claude-3-5-sonnet-20241022-v2:0",
      messages: [{ role: "user", content: [{ text: `상품 ${productId} 후기를 세 줄로 정리해 줘` }] }],
    }),
  );
  const digest = out.output?.message?.content?.[0]?.text ?? "";

  return (
    <section>
      <h2>후기 요약</h2>
      <p>{digest}</p>
    </section>
  );
}
