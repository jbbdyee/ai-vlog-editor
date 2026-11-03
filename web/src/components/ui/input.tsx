import * as React from "react";
import { cn } from "@/lib/utils";

export function Input({ className, ...props }: React.ComponentProps<"input">) {
  return <input data-slot="input" className={cn("h-11 min-w-0 w-full max-w-full rounded-xl border border-white/15 bg-[#0a111c] px-4 text-base text-white outline-none placeholder:text-slate-500 focus:border-cyan-300 focus:ring-2 focus:ring-cyan-300/15 disabled:opacity-50 sm:text-sm", className)} {...props} />;
}
