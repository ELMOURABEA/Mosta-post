import { isSafeExternalUrl } from "@posthog/shared";
import { Marked, type Token, type Tokens } from "marked";
import { objectTagExtensions } from "@/lib/objectTags";

export type InlineRun =
  | { kind: "text"; tokens: Token[] }
  | { kind: "image"; token: Tokens.Image };

export function isImageToken(token: Token): token is Tokens.Image {
  return token.type === "image";
}

// Images that can load stand on their own row between the text around them;
// the rest stay inline and render their alt text.
export function splitImageRuns(tokens: Token[]): InlineRun[] {
  const runs: InlineRun[] = [];
  let text: Token[] = [];
  const flush = () => {
    if (text.some((token) => token.raw.trim())) {
      runs.push({ kind: "text", tokens: text });
    }
    text = [];
  };
  for (const token of tokens) {
    if (isImageToken(token) && isSafeExternalUrl(token.href)) {
      flush();
      runs.push({ kind: "image", token });
    } else {
      text.push(token);
    }
  }
  flush();
  return runs;
}

export function lexMarkdown(text: string): Token[] {
  const markdown = new Marked({ extensions: objectTagExtensions() });
  return markdown.Lexer.lex(text, markdown.defaults);
}
