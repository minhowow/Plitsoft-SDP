export function ReviewSummary({ productId }: Props) {
  const { data } = useQuery(["summary", productId], () => api.aiSummary(productId));
  return (
    <section className="review-summary">
      <p>{data?.text}</p>
    </section>
  );
}
