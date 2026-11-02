"use client";

import { memo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import type { PluggableList } from "unified";
import "katex/dist/katex.min.css";

// Rendered once (module scope) instead of per-render, so `ReactMarkdown`
// doesn't see a "new" plugin array/components object on every token during
// streaming and needlessly bail out of its own memoization.
const REMARK_PLUGINS = [remarkGfm, remarkMath];
// Katex runs before highlight so `$...$` / `$$...$$` are not treated as code.
// throwOnError keeps a half-streamed formula from blanking the whole message.
const REHYPE_PLUGINS: PluggableList = [
  [rehypeKatex, { throwOnError: false, strict: "ignore" }],
  rehypeHighlight,
];

/** remark-math understands `$` and `$$`. Gemini, OpenAI, and Anthropic also
 * write `\(...\)` / `\[...\]`, sometimes with the backslash or dollar escaped.
 * Fenced and inline code are left untouched. */
function normalizeLatexDelimiters(source: string): string {
  return source
    .split(/(```[\s\S]*?```|`[^`\n]*`)/g)
    .map((part) => {
      if (part.startsWith("`")) return part;
      const unescaped = part.replace(/\\\\([()[\]])/g, "\\$1").replace(/\\\$/g, "$");
      return unescaped
        .replace(/\\\[([\s\S]+?)\\\]/g, (_match, body: string) => `\n$$\n${body}\n$$\n`)
        .replace(/\\\(([\s\S]+?)\\\)/g, (_match, body: string) => `$${body}$`);
    })
    .join("");
}

const COMPONENTS: Components = {
  // Open links in a new tab instead of navigating away from the chat.
  a: (props) => <a {...props} target="_blank" rel="noopener noreferrer" />,
};

/**
 * Renders a chat message's content as GitHub-flavored markdown, with
 * syntax-highlighted code blocks and KaTeX. The same path is used for
 * Gemini, OpenAI, and Anthropic replies.
 *
 * Used for both completed and in-progress (streaming) messages. Markdown is
 * re-parsed from the full text on every call, which is fine at chat-message
 * sizes — `react-markdown` never uses `dangerouslySetInnerHTML`, so this
 * stays safe to use directly on raw LLM output.
 */
function MarkdownMessage({ content }: { content: string }) {
  return (
    <div className="markdown-content">
      <ReactMarkdown
        remarkPlugins={REMARK_PLUGINS}
        rehypePlugins={REHYPE_PLUGINS}
        components={COMPONENTS}
      >
        {normalizeLatexDelimiters(content)}
      </ReactMarkdown>
    </div>
  );
}

export default memo(MarkdownMessage);
