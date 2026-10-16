export type DeviceGrantView = {
  status?: string
  device_id?: string
  capabilities?: string[]
  expires_at?: string | number
}

export function DeviceGrants({ view }: { view: DeviceGrantView }) {
  if (view.status !== "granted") {
    return (
      <section aria-label="device-grants">
        <p>waiting_for_local_confirmation</p>
      </section>
    )
  }
  return (
    <section aria-label="device-grants">
      <p>{view.device_id}</p>
      <ul>
        {(view.capabilities ?? []).map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      <p>{String(view.expires_at ?? "")}</p>
    </section>
  )
}
