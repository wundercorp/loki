import type * as React from "react";
import type { LokiUiExtraProps } from "./_types.js";

export type SwitchProps = Omit<React.InputHTMLAttributes<HTMLInputElement>, "checked" | "onChange" | "type"> &
  LokiUiExtraProps & {
    checked?: boolean;
    onCheckedChange?: (checked: boolean) => void;
  };

export const Switch: React.ForwardRefExoticComponent<
  React.PropsWithoutRef<SwitchProps> & React.RefAttributes<HTMLInputElement>
>;
