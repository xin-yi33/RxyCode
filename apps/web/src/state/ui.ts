import { create } from "zustand"

type ThemeName = "light" | "dark"

type UiState = {
  theme: ThemeName
  offline: boolean
  setTheme: (theme: ThemeName) => void
  setOffline: (offline: boolean) => void
}

export const useUi = create<UiState>((set) => ({
  theme: "light",
  offline: false,
  setTheme: (theme) => set({ theme }),
  setOffline: (offline) => set({ offline }),
}))
