export function ReviewSummary({ productId }: Props) {
  const { data } = useQuery(["summary", productId], () => api.aiSummary(productId));
  return (
    <section className="review-summary">
      <GeneratedContentBadge kind="summary" />
      <p>{data?.text}</p>
    </section>
  );
}
