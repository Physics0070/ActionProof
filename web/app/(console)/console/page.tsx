import { Suspense } from "react";
import { QueueView } from "@/components/console/QueueView";

export default function ConsoleHome() {
  return (
    <Suspense fallback={null}>
      <QueueView />
    </Suspense>
  );
}
