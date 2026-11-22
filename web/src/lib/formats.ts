// 0.9.18: the formats of what is typed or pasted (P-293, P-322). Three settings, an
// Admin's: `phone_formats`, the patterns a telephone number is written in, tried in order;
// `email_lower_case`; and `title_case_names`, which only the web page reads. The server
// applies the first two to a contact's numbers and email wherever they come in; the page
// applies all three as a person leaves a box or pastes into it, so that what is shown is
// what will be saved. The page and the server are held to one list of cases,
// contract/formats.json, which the tests of both read.

/** The three settings, as the page holds them. */
export interface Formats {
  /** The patterns a telephone number is written in, in the order they are tried. */
  phoneFormats: readonly string[];
  /** Whether an email address is kept in lower case. */
  emailLowerCase: boolean;
  /** Whether a person's name is given capitals where it was typed in lower case. */
  titleCaseNames: boolean;
}

/** The keys of the three settings, as `GET /settings` lists them. */
export const PHONE_FORMATS_KEY = "phone_formats";
export const EMAIL_LOWER_CASE_KEY = "email_lower_case";
export const TITLE_CASE_NAMES_KEY = "title_case_names";

/**
 * The defaults (P-322 (8)): an email address in lower case and a name in Title Case, and
 * no telephone number formatted until an Admin chooses a pattern.
 */
export const DEFAULT_FORMATS: Formats = {
  phoneFormats: [],
  emailLowerCase: true,
  titleCaseNames: true,
};

/** The two patterns of P-293, offered on the page beside one of an Admin's own. */
export const OFFERED_PATTERNS: readonly string[] = ["###-###-####", "+1 (###) ###-####"];

/**
 * The formats as `GET /settings` lists them. A setting that is not listed, as where the
 * settings could not be read, or whose value is of another kind, keeps its default.
 */
export function formatsOf(
  settings: ReadonlyArray<{ key: string; value?: unknown }> | null | undefined,
): Formats {
  const value = (key: string) => settings?.find((setting) => setting.key === key)?.value;
  const patterns = value(PHONE_FORMATS_KEY);
  const lower = value(EMAIL_LOWER_CASE_KEY);
  const title = value(TITLE_CASE_NAMES_KEY);
  return {
    phoneFormats:
      Array.isArray(patterns) && patterns.every((one) => typeof one === "string")
        ? patterns
        : DEFAULT_FORMATS.phoneFormats,
    emailLowerCase: typeof lower === "boolean" ? lower : DEFAULT_FORMATS.emailLowerCase,
    titleCaseNames: typeof title === "boolean" ? title : DEFAULT_FORMATS.titleCaseNames,
  };
}

// The formats every box follows: the settings as they were read at sign-in, and as an
// Admin changes them on the page of the settings.
let inUse: Formats = DEFAULT_FORMATS;

/** Take the formats the settings say, read at sign-in or just changed. */
export function setFormats(formats: Formats): void {
  inUse = formats;
}

/** The formats every box follows now. */
export function formatsInUse(): Formats {
  return inUse;
}

/** What a box holds, where a format applies to it. */
export type TextFormat =
  /** A telephone number: written in the first of `phone_formats` that fits its digits. */
  | "phone"
  /** An email address: in lower case, where `email_lower_case` is true. */
  | "email"
  /** A person's name, a contact's: in Title Case, where `title_case_names` is true. */
  | "person_name";

/** The characters a telephone number may hold besides its digits and still be formatted. */
const SEPARATORS = /^[0-9 +\-()./]*$/;

/**
 * A number's digits written in one pattern, or null where the pattern does not fit them
 * (P-322 (3)): its leading digits, the code of a country, followed by as many as its `#`,
 * the leading digits written once; or digits as many as its `#`. A number typed with a
 * `+` has a code of its own, which no pattern puts another in place of: it fits by the
 * pattern's leading digits, or by its `#` alone where the pattern writes a `+` of its own
 * and no leading digits, as `+## ### ### ####` does.
 */
function written(pattern: string, digits: string, plus: boolean): string | null {
  const first = pattern.indexOf("#");
  if (first < 0) return null;
  const before = pattern.slice(0, first);
  const lead = before.replace(/\D/g, "");
  const count = pattern.split("#").length - 1;
  let fill: string | null = null;
  if (lead !== "" && digits.length === lead.length + count && digits.startsWith(lead)) {
    fill = digits.slice(lead.length);
  } else if (digits.length === count && (!plus || (lead === "" && before.includes("+")))) {
    fill = digits;
  }
  if (fill === null) return null;
  const given = fill;
  let at = 0;
  return pattern.replace(/#/g, () => given.charAt(at++));
}

/**
 * Whether a value is in the form of a pattern already: its characters exactly as the
 * pattern writes them, a digit 0 to 9 at each `#`, compared as it is, untrimmed.
 */
function inFormOf(pattern: string, value: string): boolean {
  if (value.length !== pattern.length) return false;
  for (let at = 0; at < pattern.length; at++) {
    const want = pattern.charAt(at);
    const char = value.charAt(at);
    if (want === "#" ? !/[0-9]/.test(char) : char !== want) return false;
  }
  return true;
}

/**
 * A telephone number as the patterns write it: in the first that fits its digits. A
 * number with anything in it but the digits 0 to 9, spaces and `+ - ( ) . /`, a letter
 * as of an extension above all, and one that no pattern fits, are kept as typed: a
 * format never refuses a value (P-322 (3)). A number in the form of one of the patterns
 * already is kept as it is, though an earlier pattern fits its digits, so that what a
 * pattern writes is written the same again, as the server has it.
 */
export function phoneText(value: string, patterns: readonly string[]): string {
  // The server takes a value trimmed before it is formatted, and so does the page, so
  // that what is shown is what is saved.
  const text = value.trim();
  if (patterns.length === 0 || !SEPARATORS.test(text)) return text;
  if (patterns.some((pattern) => inFormOf(pattern, text))) return text;
  const digits = text.replace(/[^0-9]/g, "");
  if (digits === "") return text;
  // A `+` anywhere before the first digit gives the number a code of its own, as in
  // `(+49) 30 123456`, as the server reads it.
  const first = text.search(/[0-9]/);
  const plus = text.slice(0, first < 0 ? text.length : first).includes("+");
  for (const pattern of patterns) {
    const number = written(pattern, digits, plus);
    if (number !== null) return number;
  }
  return text;
}

/** An email address as `email_lower_case` keeps it: in lower case (P-322 (4)). */
export function emailText(value: string): string {
  return value.toLowerCase();
}

/** The characters after which a letter starts a word of a name: a space, a hyphen, an apostrophe. */
const WORD_START = /[\s\-'’]/u;

/** A letter typed in lower case, raised; any other character as it is. */
function raised(character: string): string {
  const upper = character.toUpperCase();
  const lower = character !== upper && character === character.toLowerCase();
  // A letter whose capital is more than one letter, as ß, is left as typed.
  return lower && [...upper].length === 1 ? upper : character;
}

/**
 * A name in Title Case (P-293, P-322 (7)): the first letter of each word, after a space, a
 * hyphen or an apostrophe, raised where it was typed in lower case, and no letter typed as
 * a capital lowered, so that McDonald, IT and NOC stay as typed.
 */
export function titleCase(value: string): string {
  let out = "";
  let starts = true;
  for (const character of value) {
    out += starts ? raised(character) : character;
    starts = WORD_START.test(character);
  }
  return out;
}

/** What a box holds once a format has written it again, by the formats in use or those given. */
export function tidied(format: TextFormat, value: string, formats: Formats = inUse): string {
  switch (format) {
    case "phone":
      return phoneText(value, formats.phoneFormats);
    case "email":
      return formats.emailLowerCase ? emailText(value) : value;
    case "person_name":
      return formats.titleCaseNames ? titleCase(value) : value;
    default:
      return value;
  }
}

/**
 * The tidy a box with a format makes, by the formats in use when it is made, or none for
 * a box with no format.
 */
export function tidier(format: TextFormat | undefined): ((value: string) => string) | undefined {
  return format === undefined ? undefined : (value) => tidied(format, value);
}

/**
 * What is wrong with a pattern an Admin types, or null (P-322 (2)): 4 to 40 characters,
 * `#` for each digit and four at least, digits only before the first `#`, and between them
 * spaces and `+ - ( ) . /`. The server holds a pattern to the same, and says so.
 */
export function patternProblem(pattern: string): string | null {
  const length = [...pattern].length;
  if (length < 4 || length > 40) return "A pattern is 4 to 40 characters.";
  if (pattern.split("#").length - 1 < 4) return "A pattern has a # for each digit, four at least.";
  const first = pattern.indexOf("#");
  if (/\d/.test(pattern.slice(first))) {
    return "Digits stand only before the first #, as the 1 of +1 (###) ###-####.";
  }
  if (!/^[\d# +\-()./]*$/.test(pattern)) {
    return "Between the # a pattern has only spaces and + - ( ) . /";
  }
  return null;
}

/**
 * A number written in a pattern, to show what it makes: 5550100123 in a pattern of ten
 * digits, `555-010-0123`, and digits counted up from 1 in one of any other count, so that
 * no sample looks like a number cut short: `12.34.56.78` in `##.##.##.##`.
 */
export function patternSample(pattern: string): string {
  const count = pattern.split("#").length - 1;
  const digits =
    count === 10
      ? "5550100123"
      : Array.from({ length: count }, (_, at) => String((at + 1) % 10)).join("");
  return written(pattern, digits, false) ?? pattern;
}
