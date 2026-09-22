export function ReviewList({ reviews }: Props) {
  return (
    <ul>
      {reviews.map((r) => <li key={r.id}>{r.body}</li>)}
    </ul>
  );
}
