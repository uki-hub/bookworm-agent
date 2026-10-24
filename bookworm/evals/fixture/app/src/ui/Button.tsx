export function Button(props: { label: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button className="btn" disabled={props.disabled} onClick={props.onClick}>
      {props.label}
    </button>
  );
}
