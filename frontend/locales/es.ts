import type { Dictionary } from "./en";

export const es: Dictionary = {
  sidebar: {
    title: "Chats",
    newChat: "Nuevo chat",
    closeSidebar: "Cerrar barra lateral",
    loadingSessions: "Cargando sesiones…",
    noChatsYet: "Aún no hay chats.",
    defaultChatTitle: "Nuevo chat",
    titleEmpty: "El título no puede estar vacío.",
    deleteConfirm: '¿Eliminar "{title}"?',
    confirm: "Confirmar",
    cancel: "Cancelar",
    rename: "Renombrar",
    renameChat: "Renombrar chat",
    delete: "Eliminar",
    deleteChat: "Eliminar chat",
    groups: {
      today: "Hoy",
      yesterday: "Ayer",
      previous7Days: "Últimos 7 días",
      older: "Anteriores",
    },
  },
  settings: {
    title: "Configuración",
    closeSettings: "Cerrar configuración",
    securityNotice:
      "Tus claves API se cifran en reposo en Supabase y solo se descifran en el servidor cuando chateas — nunca se envían de vuelta a este navegador después de guardarlas.",
    loadingProfile: "Cargando perfil…",
    codeforcesHandle: "Usuario de Codeforces",
    codeforcesPlaceholder: "p. ej. tourist",
    selectModel: "Modelo activo",
    anthropicApiKey: "Clave API de Anthropic",
    openaiApiKey: "Clave API de OpenAI",
    googleApiKey: "Clave API de Google Gemini",
    keyPlaceholderNewAnthropic: "sk-ant-...",
    keyPlaceholderNewOpenai: "sk-...",
    keyPlaceholderNewGoogle: "AIza...",
    keyPlaceholderSaved:
      "Clave guardada ({preview}) — ingresa un nuevo valor para reemplazarla",
    keySavedHint:
      "Tu clave guardada está enmascarada por seguridad. Ingresa un nuevo valor solo para reemplazarla.",
    keyNotSavedHint:
      "Tu clave se almacena cifrada y nunca se devuelve a este navegador después de guardarla.",
    hidden: "oculta",
    profileSaved: "Perfil guardado.",
    apiKeyRequired: "Se requiere una clave API de {provider} para usar este modelo.",
    invalidKeyPrefixAnthropic:
      "Clave API de Anthropic inválida. Las claves deben comenzar con sk-ant-.",
    invalidKeyPrefixOpenai:
      "Clave API de OpenAI inválida. Las claves deben comenzar con sk-.",
    invalidKeyPrefixGoogle:
      "Clave API de Google inválida. Las claves deben comenzar con AIza.",
    invalidKeyLength:
      "Clave API inválida. La clave parece demasiado corta.",
    signOut: "Cerrar sesión",
    cancel: "Cancelar",
    save: "Guardar",
    saving: "Guardando…",
  },
  chat: {
    openSidebar: "Abrir barra lateral",
    settings: "Configuración",
    placeholder: "Escribe un mensaje…",
    stopGenerating: "Detener generación",
    thinking: "Pensando",
    sendMessage: "Enviar mensaje",
    emptyState: "Di hola para iniciar la conversación.",
    enterToSend: "Enter para enviar · Shift+Enter para nueva línea",
    retry: "Reintentar",
    retrying: "Reintentando…",
    historyLoadError: "No se pudo cargar el historial de este chat: {message}",
    sessionStartError: "No se pudo iniciar una sesión de chat: {message}",
  },
  login: {
    title: "Iniciar sesión en OCoach",
    subtitle:
      "Coach de programación competitiva con perfiles BYOK cifrados.",
    continueWithGitHub: "Continuar con GitHub",
    redirecting: "Redirigiendo…",
    or: "o",
    emailMagicLink: "Enlace mágico por correo",
    emailPlaceholder: "tu@ejemplo.com",
    sendMagicLink: "Enviar enlace mágico",
    sending: "Enviando…",
    checkEmail:
      "Revisa tu correo para un enlace mágico e inicia sesión.",
    enterEmail: "Ingresa tu dirección de correo.",
    signInFailed: "Error al iniciar sesión. Inténtalo de nuevo.",
    brandTagline: "Programación Competitiva",
    brandHeadline1: "Entrena mejor.",
    brandHeadline2: "Resuelve más rápido.",
    brandDescription:
      "Tu coach de IA para practicar en Codeforces — pistas personalizadas, preparación para concursos y claves API cifradas bajo tu control.",
  },
  language: {
    toggle: "Cambiar idioma",
  },
};
