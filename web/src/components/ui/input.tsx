import * as React from "react";
import { cn } from "@/lib/utils";

export function Input({ className, ...props }: React.ComponentProps<"input">) {
  return <input data-slot="input" className={cn("h-11 min-w-0 w-full max-w-full rounded-xl border border-slate-300 bg-white px-4 text-base text-slate-900 outline-none placeholder:text-slate-500 focus:border-sky-500 focus:ring-2 focus:ring-sky-500/15 disabled:opacity-50 sm:text-sm", className)} {...props} />;
}
