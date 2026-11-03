import * as React from "react";
import { cn } from "@/lib/utils";

export function Card({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card" className={cn("min-w-0 rounded-2xl border border-white/10 bg-[#111a27]/90 shadow-[0_24px_80px_rgba(0,0,0,.15)]", className)} {...props} />;
}
export function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-header" className={cn("min-w-0 px-4 pt-4 sm:px-6 sm:pt-6", className)} {...props} />;
}
export function CardTitle({ className, ...props }: React.ComponentProps<"h2">) {
  return <h2 data-slot="card-title" className={cn("text-lg font-semibold tracking-tight text-white sm:text-xl", className)} {...props} />;
}
export function CardDescription({ className, ...props }: React.ComponentProps<"p">) {
  return <p data-slot="card-description" className={cn("mt-1.5 text-sm leading-5 text-slate-400 sm:mt-2 sm:leading-6", className)} {...props} />;
}
export function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-content" className={cn("min-w-0 px-4 pb-4 pt-4 sm:px-6 sm:pb-6 sm:pt-5", className)} {...props} />;
}
