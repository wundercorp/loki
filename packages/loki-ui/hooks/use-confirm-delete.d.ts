export type ConfirmDeleteOptions<Id = string> = {
  onDelete?: (id: Id) => void | Promise<void>;
};

export type ConfirmDeleteState<Id = string> = {
  pendingId: Id | null;
  isOpen: boolean;
  isDeleting: boolean;
  requestDelete: (id: Id) => void;
  cancel: () => void;
  confirm: () => Promise<void>;
};

export function useConfirmDelete<Id = string>(options?: ConfirmDeleteOptions<Id>): ConfirmDeleteState<Id>;
