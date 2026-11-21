// 0.9.14: what the pages of a user, a contact and an operator ask the server of the
// person a record belongs to (P-291, P-297, P-298): who is linked, a retirement that
// says what becomes of each, and an account brought back.

import { api, type Schemas } from "../api";
import type { BringBackBody, Linked, On, RetireBody } from "./linked";

/** The person a record belongs to, read afresh. */
export function readLinked(on: On, signal?: AbortSignal): Promise<Linked> {
  const options = { path: { hid: on.hid }, ...(signal ? { signal } : {}) };
  if (on.kind === "user") return api.request("get", "/api/v1/users/{hid}/linked", options);
  if (on.kind === "contact") return api.request("get", "/api/v1/contacts/{hid}/linked", options);
  return api.request("get", "/api/v1/operators/{hid}/linked", options);
}

/** Retire a record, saying what becomes of each record linked to it, in one request. */
export function sendRetire(on: On, body: RetireBody): Promise<unknown> {
  const options = { path: { hid: on.hid }, body };
  if (on.kind === "user") return api.request("post", "/api/v1/users/{hid}/retire", options);
  if (on.kind === "contact") return api.request("post", "/api/v1/contacts/{hid}/retire", options);
  return api.request("post", "/api/v1/operators/{hid}/retire", options);
}

/** An account brought back: the user, and its new access code, shown once. */
export type BroughtBack = Schemas["UserBroughtBack"];

/** Bring a retired account back, with its contact and the labels that are said. */
export function sendBringBack(hid: string, body: BringBackBody): Promise<BroughtBack> {
  return api.request("post", "/api/v1/users/{hid}/bring-back", { path: { hid }, body });
}
