import * as React from "react";
import { cn } from "@/lib/utils";

export function Alert({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="alert" role="alert" className={cn("min-w-0 break-words rounded-xl border border-rose-200 bg-rose-50 px-3 py-2.5 text-sm leading-5 text-rose-700 sm:px-4 sm:py-3 sm:leading-6", className)} {...props} />;
}
