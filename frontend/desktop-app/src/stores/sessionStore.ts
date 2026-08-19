/**
 * PhaseG-H5 store facade: session list is a projection of protocol sessions.
 */
export {
  addSession,
  createInitialState,
  hydrateChildSessions,
  hydrateSessions,
  purgeSession,
  renameSession,
  restoreSession,
  selectSession,
  trashSession,
  type ConversationState,
  type SessionEntry
} from '../renderer/src/lib/conversationStore.mts'
