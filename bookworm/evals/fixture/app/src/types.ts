export type Column = "todo" | "doing" | "done";

export interface Task {
  id: string;
  title: string;
  column: Column;
  owner?: string;
}

export const WIP_LIMIT = 3; // max tasks in "doing"
