import type { Task } from "../types";

export function Card({ task }: { task: Task }) {
  return <div className="card">{task.title}{task.owner ? ` (${task.owner})` : ""}</div>;
}
