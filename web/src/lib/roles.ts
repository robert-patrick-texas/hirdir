// The three roles and their order. The server decides what a role may do; this is only
// for choosing what to show.

export const ROLES = ["viewer", "inventory", "admin"] as const;
export type Role = (typeof ROLES)[number];

const LABELS: Record<Role, string> = {
  viewer: "View-only",
  inventory: "Inventory",
  admin: "Admin",
};

export function isRole(value: unknown): value is Role {
  return typeof value === "string" && (ROLES as readonly string[]).includes(value);
}

/** The name of a role as people read it. A role this build does not know is shown as sent. */
export function roleLabel(role: string | null | undefined): string {
  if (!role) return "No role";
  return isRole(role) ? LABELS[role] : role;
}

/** Say whether a holder of `held` may see what needs `needed`. */
export function allows(held: string | null | undefined, needed: Role): boolean {
  return isRole(held) && ROLES.indexOf(held) >= ROLES.indexOf(needed);
}
