import { generateText } from "ai";
import { openai } from "@ai-sdk/openai";
import { getPost } from "@/lib/posts";

export const revalidate = 86400;

export default async function Post({ params }: { params: { slug: string } }) {
  const post = await getPost(params.slug);
  const { text: summary } = await generateText({
    model: openai("gpt-4o-mini"),
    prompt: `3줄 요약:\n${post.body}`,
  });

  return (
    <article>
      <h1>{post.title}</h1>
      <aside>{summary}</aside>
      <div dangerouslySetInnerHTML={{ __html: post.html }} />
    </article>
  );
}
