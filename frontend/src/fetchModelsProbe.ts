import axios from 'axios';
import { API_BASE, authorizationHeaders } from './apiClient.js';

export type ModelInfo = {
  id: string;
  name: string;
  nickname?: string;
  provider_model_id?: string;
  base_url?: string;
  active?: boolean;
};

export type ModelsProbeResult = {
  ok: boolean;
  models: ModelInfo[];
  active: string;
};

export async function probeModels(): Promise<ModelsProbeResult> {
  try {
    const resp = await axios.get(`${API_BASE}/models`, {
      timeout: 8000,
      headers: authorizationHeaders(),
    });
    const data = resp.data as { models?: ModelInfo[]; active?: string };
    return {
      ok: true,
      models: data.models ?? [],
      active: data.active ?? '',
    };
  } catch {
    return { ok: false, models: [], active: '' };
  }
}
