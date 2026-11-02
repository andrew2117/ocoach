export const en = {
  sidebar: {
    title: "Chats",
    newChat: "New Chat",
    closeSidebar: "Close sidebar",
    loadingSessions: "Loading sessions…",
    noChatsYet: "No chats yet.",
    defaultChatTitle: "New chat",
    titleEmpty: "Title cannot be empty.",
    deleteConfirm: 'Delete "{title}"?',
    confirm: "Confirm",
    cancel: "Cancel",
    rename: "Rename",
    renameChat: "Rename chat",
    delete: "Delete",
    deleteChat: "Delete chat",
    groups: {
      today: "Today",
      yesterday: "Yesterday",
      previous7Days: "Previous 7 days",
      older: "Older",
    },
  },
  settings: {
    title: "Settings",
    closeSettings: "Close settings",
    securityNotice:
      "Your API keys are encrypted at rest in Supabase and only decrypted server-side when you chat — they are never sent back to this browser after saving.",
    loadingProfile: "Loading profile…",
    codeforcesHandle: "Codeforces handle",
    codeforcesPlaceholder: "e.g. tourist",
    selectModel: "Active model",
    anthropicApiKey: "Anthropic API key",
    openaiApiKey: "OpenAI API key",
    googleApiKey: "Google Gemini API key",
    keyPlaceholderNewAnthropic: "sk-ant-...",
    keyPlaceholderNewOpenai: "sk-...",
    keyPlaceholderNewGoogle: "AIza...",
    keyPlaceholderSaved:
      'Key saved ({preview}) — enter a new value to replace',
    keySavedHint:
      "Your saved key is masked for security. Enter a new value only to replace it.",
    keyNotSavedHint:
      "Your key is stored encrypted and never returned to this browser after saving.",
    hidden: "hidden",
    profileSaved: "Profile saved.",
    apiKeyRequired: "A {provider} API key is required to use this model.",
    invalidKeyPrefixAnthropic:
      "Invalid Anthropic API key. Keys should start with sk-ant-.",
    invalidKeyPrefixOpenai:
      "Invalid OpenAI API key. Keys should start with sk-.",
    invalidKeyPrefixGoogle:
      "Invalid Google API key. Keys should start with AIza.",
    invalidKeyLength: "Invalid API key. The key appears too short.",
    signOut: "Sign out",
    cancel: "Cancel",
    save: "Save",
    saving: "Saving…",
  },
  chat: {
    openSidebar: "Open sidebar",
    settings: "Settings",
    placeholder: "Type a message…",
    stopGenerating: "Stop generating",
    thinking: "Thinking",
    sendMessage: "Send message",
    emptyState: "Say hello to start the conversation.",
    enterToSend: "Enter to send · Shift+Enter for new line",
    retry: "Retry",
    retrying: "Retrying…",
    historyLoadError: "Couldn't load this chat's history: {message}",
    sessionStartError: "Couldn't start a chat session: {message}",
  },
  login: {
    title: "Sign in to OCoach",
    subtitle: "Competitive programming coach with encrypted BYOK profiles.",
    continueWithGitHub: "Continue with GitHub",
    redirecting: "Redirecting…",
    or: "or",
    emailMagicLink: "Email magic link",
    emailPlaceholder: "you@example.com",
    sendMagicLink: "Send magic link",
    sending: "Sending…",
    checkEmail: "Check your email for a magic link to sign in.",
    enterEmail: "Enter your email address.",
    signInFailed: "Sign-in failed. Please try again.",
    brandTagline: "Competitive Programming",
    brandHeadline1: "Train smarter.",
    brandHeadline2: "Solve faster.",
    brandDescription:
      "Your AI coach for Codeforces practice — personalized hints, contest prep, and encrypted API keys you control.",
  },
  language: {
    toggle: "Switch language",
  },
} as const;

type DeepStringRecord<T> = {
  [K in keyof T]: T[K] extends string
    ? string
    : T[K] extends Record<string, unknown>
      ? DeepStringRecord<T[K]>
      : never;
};

export type Dictionary = DeepStringRecord<typeof en>;
export type EnglishDictionary = typeof en;
