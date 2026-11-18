// 0.9.8: what the audit trail on show knows of the records its events name (P-240).

/** The action of the event in which an Admin deleted a record. */
const DELETE = "delete";

interface Named {
  action: string;
  record_type: string;
  record_hid?: string | null;
}

function recordKey(kind: string, hid: string): string {
  return `${kind} ${hid}`;
}

/**
 * The records that the events held say were deleted: those of an event of the action
 * `delete`, by kind and HID. Every event of such a record names a record that is not
 * there, however early it is. A record deleted in an event not held is not known here.
 */
export function deletedRecords(events: readonly Named[]): ReadonlySet<string> {
  const gone = new Set<string>();
  for (const event of events) {
    if (event.action === DELETE && event.record_hid) {
      gone.add(recordKey(event.record_type, event.record_hid));
    }
  }
  return gone;
}

/** True where the events held say that the record an event names was deleted. */
export function isDeleted(gone: ReadonlySet<string>, event: Named): boolean {
  return (
    Boolean(event.record_hid) && gone.has(recordKey(event.record_type, event.record_hid ?? ""))
  );
}
