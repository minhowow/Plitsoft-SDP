import { summarizeReviews } from "@/lib/ai";

export default async function ProductReviews({ productId }: { productId: string }) {
  const summary = await summarizeReviews(productId);

  return (
    <section>
      <h2>후기 한눈에 보기</h2>
      <p>{summary}</p>
    </section>
  );
}
