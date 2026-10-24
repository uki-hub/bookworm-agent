import { loadTasks, saveTasks } from "../lib/storage";
import { WIP_LIMIT, type Column, type Task } from "../types";

let tasks: Task[] = loadTasks();

export function listTasks(column?: Column): Task[] {
  return column ? tasks.filter((t) => t.column === column) : tasks;
}

export function addTask(title: string, owner?: string): Task {
  const task: Task = { id: String(Date.now()), title, column: "todo", owner };
  tasks = [...tasks, task];
  saveTasks(tasks);
  return task;
}

// Moving into "doing" respects the WIP limit; moving back is always allowed.
export function moveTask(id: string, to: Column): boolean {
  const task = tasks.find((t) => t.id === id);
  if (!task) return false;
  if (to === "doing" && listTasks("doing").length >= WIP_LIMIT) return false;
  task.column = to;
  saveTasks(tasks);
  return true;
}
