/** Reserved browser transport. This card does not connect a device. */
export interface WebTransportAdapter {
  readonly kind: "web";
  readonly delivered: false;
}

export const webTransportAdapter: WebTransportAdapter = {
  kind: "web",
  delivered: false,
};
