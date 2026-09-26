import type * as React from "react";

export type LokiUiExtraProps = {
  active?: boolean;
  asChild?: boolean;
  backdropDismissLabel?: string;
  cancelLabel?: React.ReactNode;
  confirmLabel?: React.ReactNode;
  description?: React.ReactNode;
  destructive?: boolean;
  ghost?: boolean;
  loading?: boolean;
  onCancel?: () => void;
  onCheckedChange?: (checked: boolean) => void;
  onClose?: () => void;
  onConfirm?: () => void | Promise<void>;
  onOpenChange?: (open: boolean) => void;
  onValueChange?: (value: string) => void;
  open?: boolean;
  outlined?: boolean;
  prefix?: React.ReactNode;
  size?: string;
  suffix?: React.ReactNode;
  title?: React.ReactNode;
  toast?: unknown;
  tone?: string;
  variant?: string;
  [key: string]: unknown;
};

export type LokiElementProps<Tag extends keyof React.JSX.IntrinsicElements> =
  Omit<React.ComponentPropsWithoutRef<Tag>, keyof LokiUiExtraProps> & LokiUiExtraProps;

export type LokiElementComponent<
  Tag extends keyof React.JSX.IntrinsicElements,
  Element,
> = React.ForwardRefExoticComponent<
  React.PropsWithoutRef<LokiElementProps<Tag>> & React.RefAttributes<Element>
>;
