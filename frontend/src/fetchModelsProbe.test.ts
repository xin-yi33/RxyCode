import { afterEach, describe, expect, it, vi } from 'vitest';

const axiosGet = vi.fn();

vi.mock('axios', () => ({
  default: { get: (...args: unknown[]) => axiosGet(...args) },
}));

afterEach(() => {
  axiosGet.mockReset();
  vi.resetModules();
});

describe('probeModels', () => {
  it('network failure returns ok:false', async () => {
    axiosGet.mockRejectedValueOnce(new Error('ECONNREFUSED'));
    const { probeModels } = await import('./fetchModelsProbe.js');
    await expect(probeModels()).resolves.toEqual({ ok: false, models: [], active: '' });
  });

  it('empty models list returns ok:true', async () => {
    axiosGet.mockResolvedValueOnce({ data: { models: [], active: '' } });
    const { probeModels } = await import('./fetchModelsProbe.js');
    await expect(probeModels()).resolves.toEqual({ ok: true, models: [], active: '' });
  });

  it('populated models returns ok:true with data', async () => {
    axiosGet.mockResolvedValueOnce({
      data: { models: [{ id: 'a', name: 'Model A' }], active: 'a' },
    });
    const { probeModels } = await import('./fetchModelsProbe.js');
    await expect(probeModels()).resolves.toEqual({
      ok: true,
      models: [{ id: 'a', name: 'Model A' }],
      active: 'a',
    });
  });
});
