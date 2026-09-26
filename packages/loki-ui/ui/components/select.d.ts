import type * as React from "react";
import type { LokiUiExtraProps } from "./_types.js";

export type SelectProps = Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "onChange" | "value"> &
  LokiUiExtraProps & {
    value?: string;
    onValueChange?: (value: string) => void;
  };

export function Select(props: SelectProps): React.ReactElement;

export type SelectOptionProps = React.OptionHTMLAttributes<HTMLOptionElement> & LokiUiExtraProps;
export function SelectOption(props: SelectOptionProps): React.ReactElement;
