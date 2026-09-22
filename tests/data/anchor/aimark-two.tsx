export function Summary({ id }: Props) {
  const { data } = useQuery(["s", id], () => api.aiSummary(id));
  return (
    <section>
      <Badge>AI가 생성한 요약입니다</Badge>
      <p>{data?.text}</p>
    </section>
  );
}

export function Answer({ id }: Props) {
  const { data } = useQuery(["a", id], () => api.aiAnswer(id));
  return (
    <div>
      <p>{data?.text}</p>
    </div>
  );
}
