import { en, type Dictionary, type EnglishDictionary } from "./en";
import { es } from "./es";

export const dictionaries = { en, es } as const satisfies Record<
  string,
  Dictionary
>;

export type Locale = keyof typeof dictionaries;

export type { Dictionary, EnglishDictionary };

export { en, es };
