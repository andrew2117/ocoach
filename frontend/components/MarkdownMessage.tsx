"use client";

import { memo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";

// Rendered once (module scope) instead of per-render, so `ReactMarkdown`
// doesn't see a "new" plugin array/components object on every token during
// streaming and needlessly bail out of its own memoization.
const REMARK_PLUGINS = [remarkGfm];
const REHYPE_PLUGINS = [rehypeHighlight];

const COMPONENTS: Components = {
  // Open links in a new tab instead of navigating away from the chat.
  a: (props) => <a {...props} target="_blank" rel="noopener noreferrer" />,
};

/**
 * Renders a chat message's content as GitHub-flavored markdown, with
 * syntax-highlighted code blocks (C++, Python, etc. — whatever language tag
 * the LLM emits on the fenced code block).
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
        {content}
      </ReactMarkdown>
    </div>
  );
}

export default memo(MarkdownMessage);
