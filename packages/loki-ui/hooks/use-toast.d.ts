export type ToastType = "info" | "success" | "warning" | "error" | string;
export type ToastState = { message: string; type: ToastType };

export function useToast(): {
  toast: ToastState | null;
  showToast: (message: string, type?: ToastType) => void;
  hideToast: () => void;
  clearToast: () => void;
};
