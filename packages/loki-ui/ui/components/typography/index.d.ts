import type * as React from "react";

export type TypographyProps = {
  as?: React.ElementType;
  children?: React.ReactNode;
  [key: string]: unknown;
};

export function Typography(props: TypographyProps): React.ReactElement;
