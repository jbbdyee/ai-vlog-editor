import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex min-w-0 max-w-full items-center justify-center gap-2 rounded-xl text-center text-sm font-semibold [overflow-wrap:anywhere] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 disabled:pointer-events-none disabled:opacity-45",
  {
    variants: {
      variant: {
        default: "bg-sky-600 text-white hover:bg-sky-700",
        secondary: "border border-slate-300 bg-slate-100 text-slate-800 hover:bg-slate-200",
        ghost: "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
        destructive: "bg-rose-600 text-white hover:bg-rose-700",
      },
      size: { default: "h-11 px-5", sm: "h-9 px-3", lg: "h-12 px-6" },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export function Button({ className, variant, size, asChild = false, ...props }:
  React.ComponentProps<"button"> & VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : "button";
  return <Comp data-slot="button" className={cn(buttonVariants({ variant, size, className }))} {...props} />;
}
