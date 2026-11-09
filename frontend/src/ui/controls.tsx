// Buttons, form fields, notes, the progress bar and the dialog.
import { useEffect, useId, useRef, useState, type ComponentProps, type FormEvent, type ReactNode } from "react";
import "./controls.css";

type ButtonProps = Omit<ComponentProps<"button">, "className"> & { variant?: "default" | "primary" };

export function Button({ variant = "default", type = "button", ...props }: ButtonProps) {
  return <button className="ui-button" data-variant={variant} type={type} {...props} />;
}

type FieldProps = Omit<ComponentProps<"input">, "className" | "id"> & { label: string };

export function Field({ label, ...props }: FieldProps) {
  const id = useId();
  return (
    <div className="ui-field">
      <label htmlFor={id}>{label}</label>
      <input className="ui-input" id={id} {...props} />
    </div>
  );
}

export function Note({ tone, children }: { tone: "ok" | "warn" | "bad"; children: ReactNode }) {
  // Errors interrupt screen readers; the other tones wait their turn.
  return (
    <p className="ui-note" data-tone={tone} role={tone === "bad" ? "alert" : "status"}>
      {children}
    </p>
  );
}

// Work of unknown length: a sliding bar, a label, the time taken so far and an optional hint.
export function Progress({ label, hint }: { label: string; hint?: ReactNode }) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  const elapsed = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

  return (
    <div className="ui-progress">
      <div className="ui-progress-head">
        <span className="ui-progress-label">{label}</span>
        {/* Hidden from screen readers, which would otherwise announce every tick. */}
        <span className="ui-progress-time" aria-hidden="true">
          {elapsed}
        </span>
      </div>
      <div className="ui-progress-track" role="progressbar" aria-label={label}>
        <div className="ui-progress-bar" />
      </div>
      {hint && <p className="ui-progress-hint">{hint}</p>}
    </div>
  );
}

type DialogProps = {
  open: boolean;
  title: string;
  description?: string;
  // While locked, Escape and clicks on the backdrop don't close it (work is in progress).
  locked?: boolean;
  onClose: () => void;
  onSubmit: (e: FormEvent<HTMLFormElement>) => void;
  actions: ReactNode;
  children: ReactNode;
};

// A modal form on the native <dialog>: it traps focus, closes on Escape and dims the page.
export function Dialog({ open, title, description, locked, onClose, onSubmit, actions, children }: DialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (open && !dialog?.open) dialog?.showModal();
    if (!open && dialog?.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={dialogRef}
      className="ui-dialog"
      aria-labelledby={titleId}
      onClose={onClose}
      // Escape fires `cancel` before closing; cancelling it keeps the dialog open.
      onCancel={(e) => {
        if (locked) e.preventDefault();
      }}
      // The backdrop belongs to the <dialog>, so a click outside its box is a click on the backdrop.
      onClick={(e) => {
        if (locked) return;
        const bounds = e.currentTarget.getBoundingClientRect();
        const inside =
          e.clientX >= bounds.left &&
          e.clientX <= bounds.right &&
          e.clientY >= bounds.top &&
          e.clientY <= bounds.bottom;
        if (e.target === e.currentTarget && !inside) onClose();
      }}
    >
      <form noValidate onSubmit={onSubmit}>
        <h2 id={titleId}>{title}</h2>
        {description && <p className="ui-dialog-description">{description}</p>}
        {children}
        <div className="ui-actions">{actions}</div>
      </form>
    </dialog>
  );
}
