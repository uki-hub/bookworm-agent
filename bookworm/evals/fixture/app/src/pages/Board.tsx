import { listTasks, moveTask } from "../state/board";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";

const COLUMNS = ["todo", "doing", "done"] as const;

export function Board() {
  return (
    <main>
      {COLUMNS.map((col) => (
        <section key={col}>
          <h2>{col}</h2>
          {listTasks(col).map((t) => (
            <div key={t.id}>
              <Card task={t} />
              {col !== "done" && <Button label="→" onClick={() => moveTask(t.id, col === "todo" ? "doing" : "done")} />}
            </div>
          ))}
        </section>
      ))}
    </main>
  );
}
