import * as React from "react";
import { cn } from "@/lib/utils";

export function Alert({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="alert" role="alert" className={cn("min-w-0 break-words rounded-xl border border-rose-400/30 bg-rose-400/10 px-3 py-2.5 text-sm leading-5 text-rose-100 sm:px-4 sm:py-3 sm:leading-6", className)} {...props} />;
}
