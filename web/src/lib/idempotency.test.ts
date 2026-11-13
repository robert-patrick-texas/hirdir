import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { Keys, newKey, withKey } from "./idempotency";

function counting(): Keys {
  let made = 0;
  return new Keys(() => {
    made += 1;
    return `key-${made}`;
  });
}

const lost = new ApiError({ status: 0, title: "No answer" });
const broken = new ApiError({ status: 502, title: "The server answered 502" });
const refused = new ApiError({ status: 409, title: "Preview out of date" });

describe("newKey", () => {
  it("is 32 hex digits, well within what the server takes, and never the same twice", () => {
    const one = newKey();
    expect(one).toMatch(/^[0-9a-f]{32}$/);
    expect(newKey()).not.toBe(one);
  });
});

describe("withKey", () => {
  it("sends a request with a key, and the next one like it with another", async () => {
    const keys = counting();
    const sent: string[] = [];
    const send = async (key: string) => {
      sent.push(key);
      return "done";
    };
    await expect(withKey(keys, "apply j-1", send)).resolves.toBe("done");
    await withKey(keys, "apply j-1", send);
    expect(sent).toEqual(["key-1", "key-2"]);
  });

  it("keeps the key when no answer came, so that the retry is not carried out twice", async () => {
    const keys = counting();
    const sent: string[] = [];
    const answers: Array<ApiError | string> = [lost, broken, "done"];
    const send = async (key: string) => {
      sent.push(key);
      const answer = answers.shift();
      if (answer instanceof ApiError) throw answer;
      return answer;
    };
    await expect(withKey(keys, "apply j-1", send)).rejects.toBe(lost);
    await expect(withKey(keys, "apply j-1", send)).rejects.toBe(broken);
    await expect(withKey(keys, "apply j-1", send)).resolves.toBe("done");
    expect(sent).toEqual(["key-1", "key-1", "key-1"]);
    // Answered: asking again is a new request.
    expect(keys.of("apply j-1")).toBe("key-2");
  });

  it("takes a new key after a refusal: the server answered, and kept nothing", async () => {
    const keys = counting();
    const sent: string[] = [];
    await expect(
      withKey(keys, "apply j-1", async (key) => {
        sent.push(key);
        throw refused;
      }),
    ).rejects.toBe(refused);
    await withKey(keys, "apply j-1", async (key) => sent.push(key));
    expect(sent).toEqual(["key-1", "key-2"]);
  });

  it("keeps the keys of different requests apart", async () => {
    const keys = counting();
    const fail = async () => {
      throw lost;
    };
    await expect(withKey(keys, "apply j-1 false", fail)).rejects.toBe(lost);
    await expect(withKey(keys, "apply j-1 true", fail)).rejects.toBe(lost);
    expect(keys.of("apply j-1 false")).toBe("key-1");
    expect(keys.of("apply j-1 true")).toBe("key-2");
  });
});
