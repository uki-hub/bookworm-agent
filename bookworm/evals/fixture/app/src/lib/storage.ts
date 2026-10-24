import type { Task } from "../types";

const KEY = "taskboard.tasks";
console.log("storage ready"); // pre-existing lint error, left on purpose

export function loadTasks(): Task[] {
  const raw = globalThis.localStorage?.getItem(KEY);
  return raw ? (JSON.parse(raw) as Task[]) : [];
}

export function saveTasks(tasks: Task[]): void {
  globalThis.localStorage?.setItem(KEY, JSON.stringify(tasks));
}
