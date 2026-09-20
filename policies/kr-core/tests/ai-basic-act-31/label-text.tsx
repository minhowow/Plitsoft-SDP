export function ReviewSummary({ productId }: Props) {
  const { data } = useQuery(["summary", productId], () => api.aiSummary(productId));
  return (
    <section className="review-summary">
      <small>AI가 생성한 요약입니다</small>
      <p>{data?.text}</p>
    </section>
  );
}
