import * as React from "react";
import * as ProgressPrimitive from "@radix-ui/react-progress";
import { cn } from "@/lib/utils";

export function Progress({ value, className, ...props }: React.ComponentProps<typeof ProgressPrimitive.Root>) {
  return <ProgressPrimitive.Root data-slot="progress" value={value} className={cn("relative h-2 overflow-hidden rounded-full bg-white/10", className)} {...props}>
    <ProgressPrimitive.Indicator className="h-full rounded-full bg-cyan-300 transition-transform" style={{ transform: `translateX(-${100 - (value ?? 0)}%)` }} />
  </ProgressPrimitive.Root>;
}
