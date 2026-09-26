import type * as React from "react";
import type { LokiUiExtraProps } from "./_types.js";

export function component<Tag extends keyof React.JSX.IntrinsicElements>(
  tag?: Tag,
): React.ForwardRefExoticComponent<
  React.PropsWithoutRef<Omit<React.ComponentPropsWithoutRef<Tag>, keyof LokiUiExtraProps> & LokiUiExtraProps> &
    React.RefAttributes<React.ElementRef<Tag>>
>;
